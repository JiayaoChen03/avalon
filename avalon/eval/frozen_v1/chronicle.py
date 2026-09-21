"""The public event archive: append-only history, detached reads, bounded retrieval.

IDs use the existing game-wide sequence, e.g. R2-043 (not a per-round counter).
An optional JSONL journal persists independently of agents and their LLM contexts.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
from uuid import uuid4


EVIDENCE_KINDS = {"TEAM", "SOCIAL", "PASS", "VOTE", "TEAM_VOTE", "MISSION",
                  "STRONG_VOTE", "CHALLENGE", "CHALLENGE_RESPONSE", "CITE",
                  "HOLD", "REACT", "TEAM_REVISE", "DEATH", "REBIRTH", "ASSASSINATE",
                  "EXILE_NOMINATION", "EXILE_VOTE", "EXILE_RESULT"}
PUBLIC_KINDS = EVIDENCE_KINDS | {"START", "LEADER", "DIRECTION", "ROUND", "RESOLVE_REFRESH",
    "DISCUSSION_END", "REACTION_SKIP", "TEAM_LOCK", "COUNCIL_START", "ASSASSINATION_PHASE", "RESULT"}
MAX_RETRIEVED = 5


def new_chronicle_path():
    """Separate match journals: a new match never overwrites an older Chronicle."""
    return Path.home() / ".avalon" / "chronicles" / f"{uuid4().hex}.jsonl"


# No roles, private estimates, nested evidence, provider reasoning, or sealed cards.
CONTEXT_FIELDS = {"seq", "record_id", "kind", "round", "attempt", "actor", "target",
                  "card", "team", "votes", "approved", "approve", "success", "fail_count",
                  "public_writing", "statement", "citations", "evidence", "committed",
                  "strong", "removed", "added", "life", "cause", "origin_record",
                  "related_records", "nominated_by", "declined", "challenger", "challenge", "trigger",
                  "reason", "resolve_cost", "resolve_after", "speaking_order",
                  "safe_round", "discussion_stage", "choice", "counts", "exiled", "required_approvals",
                  "leader", "team_size", "successes", "failures", "fail_threshold", "resolve",
                  "max_resolve", "direction", "order", "expired_reactions", "mission_record", "winner"}


def record_id(event):
    return f"R{event['round']}-{event['seq']:03d}"


def involves(event, pid):
    return (pid in (event.get("actor"), event.get("target"), event.get("removed"), event.get("added"))
            or pid in event.get("team", []) or pid in event.get("votes", {}))


def context_record(event):
    """A bounded public projection; never recursively embed cited records."""
    safe = {k: deepcopy(v) for k, v in event.items() if k in CONTEXT_FIELDS}
    safe["record_id"] = record_id(event)
    if event["kind"] == "START":
        safe["players"] = [{"id": p["id"], "name": p["name"]} for p in event.get("players", [])]
    # Keep the old statement name readable by existing clients, with one prose field.
    if "public_writing" in safe:
        safe.pop("statement", None)
    return safe


class Chronicle:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self._records = []
        self._by_id = {}
        if self.path is not None and self.path.exists():
            with self.path.open(encoding="utf-8") as stream:
                for line in stream:
                    self._append(json.loads(line), persist=False)

    def __len__(self):
        return len(self._records)

    def __eq__(self, other):
        if not isinstance(other, Chronicle):
            return NotImplemented
        return self.path == other.path and self._records == other._records

    @property
    def records(self):
        return deepcopy(self._records)

    def recent(self, limit=8):
        return deepcopy(self._records[-limit:]) if limit > 0 else []

    def since(self, cursor):
        """Deliver only new events to observers without copying the whole archive."""
        return deepcopy(self._records[cursor:])

    def append_record(self, event):
        """Host-only write boundary. Models are given a ChronicleReader instead."""
        return self._append(event, persist=True)

    def _append(self, event, *, persist):
        event = deepcopy(event)
        if (type(event.get("seq")) is not int or event["seq"] != len(self) + 1
                or type(event.get("round")) is not int or event["round"] < 1
                or not isinstance(event.get("kind"), str)):
            raise ValueError("Invalid Chronicle sequence")
        rid = record_id(event)
        if event.get("record_id", rid) != rid:
            raise ValueError("Invalid Chronicle record ID")
        event["record_id"] = rid
        if persist and self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        self._records.append(event)
        self._by_id[rid] = event
        return deepcopy(event)

    def get_record(self, reference):
        if type(reference) is int and 1 <= reference <= len(self):
            return deepcopy(self._records[reference - 1])
        if isinstance(reference, str) and reference in self._by_id:
            return deepcopy(self._by_id[reference])
        raise ValueError("Evidence must refer to existing public actions")

    def reader(self):
        return ChronicleReader(self)


class ChronicleReader:
    """Read capability; no append, replace, clear, or raw archive access."""
    def __init__(self, chronicle):
        self.__chronicle = chronicle

    def get_record(self, reference):
        event = self.__chronicle.get_record(reference)
        if event["kind"] not in EVIDENCE_KINDS:
            raise ValueError("Evidence must refer to existing public actions")
        return context_record(event)

    def observations_since(self, cursor):
        """Role-neutral observation stream, excluding receipts and post-game reveals."""
        return [context_record(e) for e in self.__chronicle.since(cursor) if e["kind"] in PUBLIC_KINDS]

    def validate_citations(self, citations):
        if (not isinstance(citations, list) or len(citations) > 3
                or any(not isinstance(rid, str) for rid in citations)
                or len(set(citations)) != len(citations)):
            raise ValueError("Invalid Chronicle citations")
        return [self.get_record(rid) for rid in citations]

    def search_records(self, query="", *, target=None, record_ids=(), limit=MAX_RETRIEVED):
        """Inspectable metadata/keyword ranking; references and targets outrank recency.

        English keywords and Chinese bigrams work without an embedding service.
        Search never includes role reveals or individual mission receipts.
        """
        limit = min(MAX_RETRIEVED, max(0, limit))
        terms = re.findall(r"[a-z0-9_-]+|[\u4e00-\u9fff]{2,}", query.lower()[:240])
        terms = [part for term in terms for part in
                 ([term[i:i+2] for i in range(len(term)-1)] if re.fullmatch(r"[\u4e00-\u9fff]+", term) else [term])]
        refs = set(record_ids)
        ranked = []
        for event in self.__chronicle._records:
            if event["kind"] not in EVIDENCE_KINDS:
                continue
            explicit = event["record_id"] in refs or event["seq"] in refs
            related = target is not None and involves(event, target)
            text = json.dumps(context_record(event), ensure_ascii=False).lower() if terms else ""
            matches = sum(term in text for term in terms)
            if (terms or target or refs) and not (explicit or related or matches):
                continue
            salient = event.get("card") in {"ACCUSE", "DEFEND"} or event["kind"] in {"MISSION", "DEATH", "ASSASSINATE"}
            score = 100 * explicit + 25 * related + min(20, 3 * matches) + 5 * salient
            ranked.append((score, event["seq"], event))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [context_record(event) for _, _, event in ranked[:limit]]
