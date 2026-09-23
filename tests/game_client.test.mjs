import assert from 'node:assert/strict';
import test from 'node:test';

import { GameClient } from '../Assets/src/gameClient.js';

const players = Array.from({ length: 5 }, (_, index) => ({ id: `P${index + 1}` }));

function state(revision, phase = 'VOTE', extra = {}) {
  return {
    revision,
    phase,
    engine_phase: phase.toLowerCase(),
    players,
    human_turn: false,
    can_advance: true,
    ...extra,
  };
}

function response(payload) {
  return { ok: true, status: 200, json: async () => payload };
}

function session(initialState, replies) {
  const requests = [];
  let active = 0;
  let maxActive = 0;
  const fetchImpl = async (path, options) => {
    assert.equal(path, '/api/command');
    assert.equal(options.method, 'POST');
    const request = JSON.parse(options.body);
    requests.push(request);
    active += 1;
    maxActive = Math.max(maxActive, active);
    try {
      assert.ok(replies.length, 'unexpected extra AI request');
      const next = replies.shift();
      const result = typeof next === 'function' ? await next(request) : next;
      if (result instanceof Error) throw result;
      return response(result);
    } finally {
      active -= 1;
    }
  };
  const client = new GameClient({ fetchImpl });
  client.state = initialState;
  client.connected = true;
  client.csrfToken = 'test-token';
  return { client, requests, maxActive: () => maxActive };
}

test('VOTE advances one ballot at a time, with a fresh revision and request ID, then stops at the result', async () => {
  const { client, requests, maxActive } = session(state(15), [
    { ok: true, state: state(16) },
    { ok: true, state: state(17) },
    { ok: true, state: state(18, 'VOTE_RESULT', { can_advance: false }) },
  ]);

  await client.advanceAI();

  assert.deepEqual(requests.map((request) => request.revision), [15, 16, 17]);
  assert.deepEqual(requests.map((request) => request.command), ['advance', 'advance', 'advance']);
  assert.equal(new Set(requests.map((request) => request.request_id)).size, 3);
  assert.equal(maxActive(), 1);
  assert.equal(client.state.phase, 'VOTE_RESULT');
  assert.equal(client.snapshot().busy, false);
});

test('EXILE_VOTE stops when its result gate is reached', async () => {
  const { client, requests } = session(state(4, 'EXILE_VOTE'), [
    { ok: true, state: state(5, 'EXILE_VOTE') },
    { ok: true, state: state(6, 'EXILE_RESULT', { can_advance: false }) },
  ]);

  await client.advanceAI();

  assert.deepEqual(requests.map((request) => request.revision), [4, 5]);
  assert.equal(client.state.phase, 'EXILE_RESULT');
});

test('vote batch stops when the human turn arrives', async () => {
  const { client, requests } = session(state(20), [
    { ok: true, state: state(21, 'VOTE', { human_turn: true }) },
  ]);

  await client.advanceAI();

  assert.equal(requests.length, 1);
  assert.equal(client.state.human_turn, true);
});

test('vote batch stops when the server disables AI advancement', async () => {
  const { client, requests } = session(state(20), [
    { ok: true, state: state(21, 'VOTE', { can_advance: false }) },
  ]);

  await client.advanceAI();

  assert.equal(requests.length, 1);
  assert.equal(client.state.can_advance, false);
});

test('vote batch has a hard cap of players.length requests', async () => {
  const replies = Array.from({ length: players.length }, (_, index) => ({
    ok: true,
    state: state(index + 2),
  }));
  const { client, requests } = session(state(1), replies);

  await client.advanceAI();

  assert.equal(requests.length, players.length);
  assert.deepEqual(requests.map((request) => request.revision), [1, 2, 3, 4, 5]);
  assert.equal(client.state.can_advance, true);
});

test('ordinary discussion advances exactly one AI action', async () => {
  const { client, requests } = session(state(9, 'DISCUSSION'), [
    { ok: true, state: state(10, 'DISCUSSION') },
  ]);

  await client.advanceAI();

  assert.equal(requests.length, 1);
  assert.equal(client.state.revision, 10);
});

test('a network error stops the batch and retryPending resends the identical request', async () => {
  const { client, requests } = session(state(15), [
    new Error('connection lost'),
    { ok: true, state: state(16, 'VOTE_RESULT', { can_advance: false }) },
  ]);

  await client.advanceAI();

  assert.equal(requests.length, 1);
  assert.equal(client.state.revision, 15);
  assert.equal(client.uncertain, true);
  assert.deepEqual(client.pending, requests[0]);

  await client.retryPending();

  assert.equal(requests.length, 2);
  assert.deepEqual(requests[1], requests[0]);
  assert.equal(client.state.phase, 'VOTE_RESULT');
});

test('a rejected command stops the vote batch immediately', async () => {
  const { client, requests } = session(state(15), [
    { ok: false, error: 'AI 暂时无法行动。', state: state(15) },
  ]);

  await client.advanceAI();

  assert.equal(requests.length, 1);
  assert.equal(client.error, 'AI 暂时无法行动。');
  assert.equal(client.state.revision, 15);
});

test('concurrent AI and ordinary commands are blocked while a vote batch is pending', async () => {
  let release;
  const heldReply = new Promise((resolve) => { release = resolve; });
  const { client, requests } = session(state(30), [
    async () => heldReply,
  ]);

  const batch = client.advanceAI();
  assert.equal(requests.length, 1);
  assert.equal(client.snapshot().busy, true);

  const duplicate = client.advanceAI();
  const ordinary = client.command('advance');
  const retry = client.retryPending();
  await Promise.all([duplicate, ordinary, retry]);
  assert.equal(requests.length, 1);

  release({ ok: true, state: state(31, 'VOTE_RESULT', { can_advance: false }) });
  await batch;
  assert.equal(requests.length, 1);
  assert.equal(client.snapshot().busy, false);
});

test('a stale success reply does not trigger another ballot', async () => {
  const { client, requests } = session(state(15), [
    { ok: true, state: state(15) },
  ]);

  await client.advanceAI();

  assert.equal(requests.length, 1);
  assert.equal(client.state.revision, 15);
});
