/**
 * Browser transport for Avalon. The server is authoritative: this class never
 * guesses a phase, action, AP balance, mission result, or role.
 */
export class GameClient {
  constructor({ baseUrl = '', fetchImpl = globalThis.fetch.bind(globalThis) } = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.fetch = fetchImpl;
    this.state = null;
    this.mode = 'offline';
    this.merlinVotePolicy = 'baseline';
    this.discussionPolicy = 'baseline';
    this.csrfToken = '';
    this.connected = false;
    this.busy = false;
    this._advancing = false;
    this.error = '';
    this.uncertain = false;
    this.pending = null;
    this.listeners = new Set();
    this._requestCounter = 0;
  }

  subscribe(listener) {
    this.listeners.add(listener);
    listener(this.snapshot());
    return () => this.listeners.delete(listener);
  }

  snapshot() {
    return {
      state: this.state,
      mode: this.mode,
      merlinVotePolicy: this.merlinVotePolicy,
      discussionPolicy: this.discussionPolicy,
      connected: this.connected,
      busy: this.busy || this._advancing,
      error: this.error,
      uncertain: this.uncertain,
      pending: this.pending ? { command: this.pending.command } : null,
    };
  }

  _notify() {
    const value = this.snapshot();
    this.listeners.forEach((listener) => listener(value));
  }

  _url(path) { return `${this.baseUrl}${path}`; }

  async _json(path, options = {}) {
    let response;
    try {
      response = await this.fetch(this._url(path), {
        cache: 'no-store',
        ...options,
        headers: {
          Accept: 'application/json',
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
          ...(this.csrfToken ? { 'X-Avalon-Token': this.csrfToken } : {}),
          ...(options.headers || {}),
        },
      });
    } catch (error) {
      const wrapped = new Error('无法连接 Avalon 后端。请启动本地服务器后重试。');
      wrapped.cause = error;
      wrapped.network = true;
      throw wrapped;
    }
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* handled below */ }
    if (!response.ok) {
      const error = new Error(payload?.error || `后端请求失败（${response.status}）。`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  async connect() {
    this.error = '';
    this._notify();
    try {
      const payload = await this._json('/api/session', { method: 'GET' });
      this.mode = payload.mode || 'offline';
      this.merlinVotePolicy = payload.merlin_vote_policy === 'v5' ? 'v5' : 'baseline';
      this.discussionPolicy = payload.discussion_policy === 'engaged_v1' ? 'engaged_v1' : 'baseline';
      this.csrfToken = payload.csrf_token || '';
      this.state = payload.state || null;
      this.connected = true;
      this.uncertain = false;
      this.pending = null;
    } catch (error) {
      this.connected = false;
      this.error = error.message;
      throw error;
    }
    this._notify();
    return this.state;
  }

  async refresh() {
    try {
      const payload = await this._json('/api/state', { method: 'GET' });
      if (payload?.state) this.state = payload.state;
      this.connected = true;
      this.error = '';
      this._notify();
      return this.state;
    } catch (error) {
      this.connected = false;
      this.error = error.message;
      this._notify();
      throw error;
    }
  }

  async command(command, payload = {}) {
    if (this._advancing) return false;
    return this._command(command, payload);
  }

  async advanceAI() {
    if (this.busy || this._advancing || this.pending || !this.state?.can_advance || this.state.human_turn) return false;
    const votingPhase = ['VOTE', 'EXILE_VOTE'].includes(this.state.phase) ? this.state.phase : null;
    const limit = votingPhase ? Math.max(1, this.state.players?.length || 1) : 1;
    this._advancing = true;
    try {
      for (let index = 0; index < limit; index += 1) {
        const revision = this.state.revision;
        if (!await this._command('advance')) return false;
        if (this.state.revision <= revision) {
          this.error = '对局尚未推进，请刷新页面确认当前状态。';
          return false;
        }
        // Each ballot remains a separate versioned engine command. Never cross
        // a result gate, human choice, or phase boundary on the user's behalf.
        if (!votingPhase || this.state.phase !== votingPhase || !this.state.can_advance || this.state.human_turn) return true;
      }
      return true;
    } finally {
      this._advancing = false;
      this._notify();
    }
  }

  async _command(command, payload = {}) {
    if (this.busy) return false;
    if (this.pending) {
      this.error = '上次操作的结果尚未确认，请先重试刚才的操作。';
      this._notify();
      return false;
    }
    if (!this.connected || !this.csrfToken) {
      this.error = '尚未连接 Avalon 后端。';
      this._notify();
      return false;
    }
    const requestId = this._makeRequestId();
    const request = {
      request_id: requestId,
      revision: this.state?.revision ?? 0,
      command,
      payload,
    };
    this.pending = { ...request };
    this.busy = true;
    this.error = '';
    this.uncertain = false;
    this._notify();
    try {
      const result = await this._json('/api/command', {
        method: 'POST',
        body: JSON.stringify(request),
      });
      if (result?.state) this.state = result.state;
      if (result?.ok) {
        this.error = '';
        this.uncertain = false;
        this.pending = null;
      } else {
        this.error = result?.error || '操作未执行。';
        this.uncertain = false;
        this.pending = null;
      }
      this.connected = true;
      this.busy = false;
      this._notify();
      return Boolean(result?.ok);
    } catch (error) {
      this.busy = false;
      this.connected = !error.network;
      this.error = error.message;
      // Retain this request id. A user-triggered retry is idempotent if the
      // server committed before the browser lost its response.
      this.uncertain = Boolean(error.network);
      this._notify();
      return false;
    }
  }

  async retryPending() {
    if (!this.pending || this.busy || this._advancing) return false;
    const pending = this.pending;
    this.connected = true;
    this.busy = true;
    this.error = '';
    this.uncertain = false;
    this._notify();
    try {
      const result = await this._json('/api/command', {
        method: 'POST',
        body: JSON.stringify(pending),
      });
      if (result?.state) this.state = result.state;
      this.error = result?.ok ? '' : (result?.error || '操作未执行。');
      this.pending = result?.ok || result?.state ? null : pending;
      this.busy = false;
      this.uncertain = false;
      this.connected = true;
      this._notify();
      return Boolean(result?.ok);
    } catch (error) {
      this.busy = false;
      this.connected = !error.network;
      this.error = error.message;
      this.uncertain = Boolean(error.network);
      this._notify();
      return false;
    }
  }

  _makeRequestId() {
    this._requestCounter += 1;
    const uuid = globalThis.crypto?.randomUUID?.();
    return `web-${uuid || `${Date.now()}-${this._requestCounter}`}`;
  }
}
