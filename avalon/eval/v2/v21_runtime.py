"""Durable decisions and atomic pure-Game commits; no rule or belief changes."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import threading
import time
import uuid

from avalon.llm import ChatClient,LLMError
from avalon.eval.simulation import canonical,digest
from .live import BudgetLedger,BudgetStop
from .v21_contract import (configure_transport,menu_context,decode_menu,legal_menu,
                           validate_legal_action,correction_feedback,POLICY_CURRENT,ADAPTER_REVISION)
from .v21_audit import failure_class


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('w') as f:f.write(canonical(value)+'\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def json_read(path):return json.loads(Path(path).read_text())


class Cancelled(RuntimeError):pass
class StaleState(RuntimeError):pass


class DurableBudget(BudgetLedger):
    """Pending HTTP attempts survive process death; unknown usage stays reserved."""
    def __init__(self,folder,cny,max_calls):
        super().__init__(cny,max_calls);self.folder=Path(folder);self.requests=self.folder/'requests'
        self.requests.mkdir(parents=True,exist_ok=True)
        for path in self.requests.glob('*.request.json'):
            item=json_read(path);result=path.with_name(path.name.replace('.request.json','.response.json'))
            self.calls+=1
            if result.exists():
                row=json_read(result);self.charged+=row['budget_charged_cny'];self.estimated+=row['estimated_cny'] or 0
                self.unknown+=row['usage_status']=='unavailable'
                for k,v in row['transport'].get('usage',{}).items():self.usage[k]=self.usage.get(k,0)+v
            else:self.charged+=item['reservation']['cny'];self.unknown+=1
        if self.charged>self.limit:raise BudgetStop('Restored reservations exceed approved budget')

    def begin(self,payload,metadata):
        reservation=self.reserve(payload);uid=uuid.uuid4().hex
        atomic_json(self.requests/(uid+'.request.json'),{'attempt_uid':uid,'reservation':reservation,**metadata})
        return uid,reservation

    def finish(self,uid,row):atomic_json(self.requests/(uid+'.response.json'),row)


class Session:
    """A checkpoint is an initial deterministic game plus legal decisions/commits.

    Recovery rebuilds a NEW, side-effect-free Game and beliefs from original
    private views + public events. It verifies every context and state digest.
    It does not resubmit accepted decisions to the model or double-pay resources
    in a surviving Game. Sealed ballots are accepted individually and committed
    together by the existing simulation loop.
    """
    def __init__(self,path,identity,stop_after=None):
        self.path=Path(path);self.identity=identity;self.lock=threading.RLock()
        self.data=json_read(path) if self.path.exists() else {'identity':identity,'decisions':[], 'commits':[],'pending_commit':None}
        if self.data['identity']!=identity:raise ValueError('incompatible_resume')
        self.decision_cursor=self.commit_cursor=0;self.stop_after=stop_after
        self.applied={};self.current=None;self.cached=0
        self.save()

    def save(self):atomic_json(self.path,self.data)

    def choose(self,context,client):
        with self.lock:
            i=self.decision_cursor;self.decision_cursor+=1
            binding={'game_id':self.identity['game_id'],'observer_id':context['view']['self'],
                'decision_id':f"{self.identity['game_id']}:d{i:04d}",'state_version':digest(context['view']),
                'context_hash':digest(context),'index':i}
            self.current=binding
            if i<len(self.data['decisions']):
                previous=self.data['decisions'][i]
                if previous['binding']!=binding:raise StaleState('checkpoint_mismatch')
                if previous['status'] in {'accepted','executed'}:
                    self.cached+=1;return deepcopy(previous['validated_action'])
                if previous['status']=='failed':raise RuntimeError('Recorded failed decision remains failed; new configuration requires new run_id')
            else:
                context_path=self.path.parent/'contexts'/f'{i:04d}.json'
                atomic_json(context_path,context)
                self.data['decisions'].append({'binding':binding,'status':'pending','context_path':str(context_path)})
                self.save()
            if self.stop_after is not None and i>=self.stop_after:raise Cancelled('intentional_checkpoint_test')
        try:
            if hasattr(client,'bind'):client.bind(binding)
            action=client.complete(context)
            validate_legal_action(action,context['view'])
            self.accept(binding,action)
            return action
        except (BudgetStop,Cancelled):raise
        except Exception as e:
            with self.lock:
                self.data['decisions'][i].update(status='failed',error=type(e).__name__+': '+str(e));self.save()
            raise

    def accept(self,binding,action):
        with self.lock:
            if self.current!=binding:raise StaleState('stale_state')
            row=self.data['decisions'][binding['index']]
            if row['status'] in {'accepted','executed'}:
                if row['validated_action']!=action:raise StaleState('conflicting_idempotency_key')
                return False
            row.update(status='accepted',validated_action=deepcopy(action),accepted_utc=datetime.now(timezone.utc).isoformat())
            self.save();return True

    @staticmethod
    def game_hash(game):
        return digest({'events':game.events,'views':{p:game.view(p) for p in game.ids},'winner':game.winner})

    def submit(self,game,key,method,args,kwargs):
        with self.lock:
            action_hash=digest([method,args,kwargs])
            if key in self.applied:
                if self.applied[key]!=action_hash:raise StaleState('conflicting_idempotency_key')
                return False
            index=self.commit_cursor;before=self.game_hash(game)
            if index<len(self.data['commits']):
                old=self.data['commits'][index]
                if old['key']!=key or old['before']!=before or old['action_hash']!=action_hash:raise StaleState('checkpoint_mismatch')
            else:
                self.data['pending_commit']={'key':key,'before':before,'action_hash':action_hash,
                    'method':method,'args':deepcopy(args),'kwargs':deepcopy(kwargs)};self.save()
            # Production validation and mutation run on a detached transaction.
            # A rejected action cannot partially spend AP or emit public events.
            candidate=deepcopy(game);getattr(candidate,method)(*args,**kwargs)
            after=self.game_hash(candidate)
            if index<len(self.data['commits']):
                if self.data['commits'][index]['after']!=after:raise StaleState('checkpoint_mismatch')
            else:
                self.data['commits'].append({**self.data['pending_commit'],'after':after,
                    'decisions_through':self.decision_cursor,'event_seq':len(candidate.events)})
                for r in self.data['decisions'][:self.decision_cursor]:
                    if r['status']=='accepted':r.update(status='executed',executed_action=deepcopy(r['validated_action']),commit_key=key)
                self.data['pending_commit']=None;self.save()
            game.__dict__=candidate.__dict__
            self.applied[key]=action_hash;self.commit_cursor+=1
            return True

    def commit(self,game,method,*args,**kwargs):
        return self.submit(game,f"{self.identity['game_id']}:c{self.commit_cursor:04d}",method,args,kwargs)


class MenuClient:
    def __init__(self,settings,budget,metadata,policy=POLICY_CURRENT,cancel=None):
        self.settings=settings;self.transport=configure_transport(ChatClient(settings))
        self.budget=budget;self.metadata=metadata;self.policy=policy;self.cancel=cancel or threading.Event()
        self.calls=self.context_bytes=self.external_calls=0;self.binding={};self.usage={}
        self.transport_retries=2;self.corrections=2

    def bind(self,binding):self.binding=deepcopy(binding)

    def complete(self,context):
        self.calls+=1;self.context_bytes+=len(canonical(context).encode())
        supplied=menu_context(context,self.policy);menu=supplied['action_menu']
        if len(menu)==1 and not menu[0]['parameters']:
            action=deepcopy(menu[0]['action']);validate_legal_action(action,context['view']);return action
        transport_used=corrections_used=attempt=0
        while True:
            if self.cancel.is_set():raise Cancelled('cancelled')
            payload=self.transport.request_payload(supplied)
            meta={**self.metadata,**self.binding,'adapter_revision':ADAPTER_REVISION,'policy_revision':self.policy,
                'phase':context['view']['phase'],'observer_role':context['view']['role'],
                'started_utc':datetime.now(timezone.utc).isoformat(),'retry_index':attempt,
                'transport_retries_used':transport_used,'corrections_used':corrections_used,
                'context':deepcopy(supplied),'model_context_hash':digest(supplied),'client_cache_hit':False}
            uid,reservation=self.budget.begin(payload,meta);self.external_calls+=1
            row={**meta,'attempt_uid':uid,'reservation':reservation,'accepted':False,'fallback':False}
            t=time.perf_counter();error=None
            try:
                raw=self.transport.complete(supplied);row['raw_response']=raw
                action,details=decode_menu(raw,context,supplied);row.update(details,accepted=True)
            except (LLMError,ValueError,TypeError,KeyError) as e:
                error=e;reason=str(e) if not isinstance(e,LLMError) else e.validation_reason
                code=str(e) if isinstance(e,LLMError) else 'invalid_plan'
                row.update(error=code,validation_reason=reason,failure_class=failure_class(code,reason))
            finally:
                telemetry=deepcopy(self.transport.last_call);usage=telemetry.get('usage',{})
                accounting=self.budget.settle(reservation,usage,meta['started_utc'])
                row.update(transport=telemetry,**accounting,elapsed_seconds=time.perf_counter()-t,
                    ended_utc=datetime.now(timezone.utc).isoformat())
                self.budget.finish(uid,row)
            if error is None:return action
            if isinstance(error,LLMError) and str(error).startswith(('http_','timeout','connection')):
                if not error.retryable or transport_used>=self.transport_retries:raise error
                transport_used+=1;self.cancel.wait(min(self.settings.retry_delay*2**(transport_used-1),10))
            else:
                if isinstance(error,LLMError) and not error.retryable:raise error
                if corrections_used>=self.corrections:raise RuntimeError('correction_limit: '+str(error))
                corrections_used+=1
                supplied['validation_feedback']={**correction_feedback(row.get('raw_response'),supplied,row['validation_reason']),
                    'error':row['error'],
                    'rejected_action':row.get('raw_response',{}).get('recommended_action'),
                    'correction_number':corrections_used}
            attempt+=1
