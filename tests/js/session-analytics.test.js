'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

global.window = {};
require(path.resolve(__dirname, '../../src/claude_prospector/static/cp-utils.js'));
const A = window.CP.sessionAnalytics;

const TOKEN_KEYS = [
  'input_tokens', 'output_tokens', 'cache_read_tokens',
  'cache_creation_tokens', 'total_tokens',
];

function sameTimestampEvents() {
  const timestamp = '2026-09-13T10:00:00Z';
  return {
    responses: [{timestamp, agent: 'main', total_tokens: 1}],
    skills: [{timestamp, agent: 'main', skill: 'python'}],
    commands: [{timestamp, agent: 'main', name: '/compact'}],
    mcp: [{timestamp, agent: 'main', server: 'github', method: 'get_issue'}],
  };
}

function rangeForResponse(response) {
  const start = Date.parse(response.timestamp);
  return {start, end: start + 1};
}

test('bucket totals reconcile for every effort series', () => {
  const session = require('../fixtures/session-analytics/long-concurrent-agents.json');
  const buckets = A.bucketResponses(session.agent_activity, {
    start: Date.parse(session.start_time),
    end: Date.parse(session.end_time) + 1,
    width: 600,
  });
  assert.equal(
    buckets.reduce((total, bucket) => total + bucket.total_tokens, 0),
    1000,
  );
  assert.deepEqual(
    buckets.reduce((totals, bucket) => {
      for (const effortTokens of Object.values(bucket.by_effort)) totals += effortTokens;
      return totals;
    }, 0),
    1000,
  );
});

test('All ignores the brush and By time period applies it', () => {
  const session = require('../fixtures/session-analytics/short-single-agent.json');
  const active = new Set(['main']);
  assert.equal(A.scopeSession(session, active, 'all', {start: 0, end: 1}).responses.length, 3);
  assert.equal(
    A.scopeSession(session, active, 'period', {
      start: Date.parse(session.agent_activity[1].timestamp),
      end: Date.parse(session.agent_activity[2].timestamp),
    }).responses.length,
    1,
  );
});

test('disabling a child makes ancestors indeterminate', () => {
  const session = require('../fixtures/session-analytics/deep-nested-agents.json');
  const paths = session.agent_paths.map(parts => parts.join('→'));
  let active = new Set(paths);
  active = A.setSubtree(active, 'main→left', false, paths);
  assert.equal(A.selectionState(active, 'main', paths), 'indeterminate');
  assert.equal(active.has('main→left→worker'), false);
  assert.equal(active.has('main→right→worker'), true);
});

test('exact bars require twelve pixels per response', () => {
  assert.equal(A.usesExactBars(new Array(10).fill({}), 120), true);
  assert.equal(A.usesExactBars(new Array(11).fill({}), 120), false);
});

test('a dense long session stays continuous until the selected range narrows', () => {
  const fixture = require('../fixtures/session-analytics/long-concurrent-agents.json');
  const seed = fixture.agent_activity[0];
  const dense = Array.from({length: 101}, (_, index) => Object.freeze({
    ...seed,
    timestamp: new Date(Date.parse(fixture.start_time) + index * 1000).toISOString(),
  }));
  assert.equal(A.usesExactBars(dense, 1200), false);
  assert.equal(A.usesExactBars(dense.slice(0, 20), 1200), true);
  assert.equal(fixture.agent_activity.length, 4);
});

test('full paths with the same leaf stay independent', () => {
  const paths = ['main', 'main→left', 'main→left→worker', 'main→right', 'main→right→worker'];
  const active = A.setSubtree(new Set(paths), 'main→left→worker', false, paths);
  assert.equal(active.has('main→left→worker'), false);
  assert.equal(active.has('main→right→worker'), true);
});

test('ledger uses deterministic tie order without claiming causality', () => {
  const ledger = A.mergeLedger(sameTimestampEvents());
  assert.deepEqual(ledger.map(event => event.kind), ['response', 'skill', 'command', 'mcp']);
});

test('ranges are half-open and exclude missing timestamps', () => {
  const response = {timestamp: '2026-09-13T10:00:00Z'};
  assert.equal(A.inRange(response, rangeForResponse(response)), true);
  assert.equal(A.inRange(response, {start: Date.parse(response.timestamp) + 1, end: Date.parse(response.timestamp) + 2}), false);
  assert.equal(A.inRange({timestamp: null}, rangeForResponse(response)), false);
});

test('every fixture token component reconciles to its response rows', () => {
  const cases = [
    ['short-single-agent', {input_tokens: 6, output_tokens: 54, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 60}],
    ['long-concurrent-agents', {input_tokens: 100, output_tokens: 900, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 1000}],
    ['deep-nested-agents', {input_tokens: 0, output_tokens: 5, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 5}],
  ];
  for (const [name, expected] of cases) {
    const session = require(`../fixtures/session-analytics/${name}.json`);
    const totals = A.sumTokens(session.agent_activity);
    for (const key of TOKEN_KEYS) {
      assert.equal(totals[key], expected[key], `${name} ${key}`);
    }
  }
});

test('bucket token components reconcile for every fixture', () => {
  const cases = [
    ['short-single-agent', {input_tokens: 6, output_tokens: 54, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 60}],
    ['long-concurrent-agents', {input_tokens: 100, output_tokens: 900, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 1000}],
    ['deep-nested-agents', {input_tokens: 0, output_tokens: 5, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 5}],
  ];
  for (const [name, expected] of cases) {
    const session = require(`../fixtures/session-analytics/${name}.json`);
    const buckets = A.bucketResponses(session.agent_activity, {
      start: Date.parse(session.start_time),
      end: Date.parse(session.end_time) + 1,
      width: 600,
    });
    for (const key of TOKEN_KEYS) {
      assert.equal(
        buckets.reduce((total, bucket) => total + bucket[key], 0),
        expected[key],
        `${name} ${key}`,
      );
    }
  }
});

test('agent tree retains repeated worker leaves under their full paths', () => {
  const tree = A.buildAgentTree(['main→right→worker', 'main→left', 'main', 'main→right', 'main→left→worker']);
  assert.deepEqual(tree, [{
    path: 'main', label: 'main', children: [
      {path: 'main→left', label: 'left', children: [{path: 'main→left→worker', label: 'worker', children: []}]},
      {path: 'main→right', label: 'right', children: [{path: 'main→right→worker', label: 'worker', children: []}]},
    ],
  }]);
});

test('agent tree connects an implicit parent between a root and grandchild', () => {
  const tree = A.buildAgentTree(['main', 'main→left→worker']);
  assert.deepEqual(tree, [{
    path: 'main', label: 'main', children: [{
      path: 'main→left', label: 'left', children: [{
        path: 'main→left→worker', label: 'worker', children: [],
      }],
    }],
  }]);
});

test('agent tree connects every missing intermediate ancestor', () => {
  const tree = A.buildAgentTree(['main', 'main→alpha→beta→worker']);
  assert.deepEqual(tree, [{
    path: 'main', label: 'main', children: [{
      path: 'main→alpha', label: 'alpha', children: [{
        path: 'main→alpha→beta', label: 'beta', children: [{
          path: 'main→alpha→beta→worker', label: 'worker', children: [],
        }],
      }],
    }],
  }]);
});

test('MCP payloads preserve collected zero, not collected, and unavailable states', () => {
  const short = require('../fixtures/session-analytics/short-single-agent.json');
  const deep = require('../fixtures/session-analytics/deep-nested-agents.json');
  const unavailable = {...deep, mcp_collection: {calls: 'unavailable', result_sizes: 'unavailable'}, mcp_activity: null};
  const active = new Set(['main']);
  assert.equal(short.mcp_collection.calls, 'not_collected');
  assert.equal(A.scopeSession(short, active, 'all', {start: 0, end: 1}).mcp, null);
  assert.equal(deep.mcp_collection.calls, 'collected');
  assert.deepEqual(A.scopeSession(deep, active, 'all', {start: 0, end: 1}).mcp, []);
  assert.equal(unavailable.mcp_collection.calls, 'unavailable');
  assert.equal(A.scopeSession(unavailable, active, 'all', {start: 0, end: 1}).mcp, null);
});

test('period filtering applies exact full paths to every activity type', () => {
  const session = require('../fixtures/session-analytics/long-concurrent-agents.json');
  const scoped = A.scopeSession(session, new Set(['main→worker']), 'period', {
    start: Date.parse('2026-09-13T10:00:01Z'),
    end: Date.parse('2026-09-13T10:00:02Z'),
  });
  assert.equal(scoped.responses.length, 1);
  assert.equal(scoped.skills.length, 1);
  assert.equal(scoped.commands.length, 0);
  assert.equal(scoped.mcp.length, 0);
});

test('ledger places missing timestamps after timestamped activity in source order', () => {
  const ledger = A.mergeLedger({
    responses: [{timestamp: null, total_tokens: 1}],
    skills: [{timestamp: '2026-09-13T10:00:00Z', skill: 'python'}],
    commands: [{name: '/compact'}],
    mcp: [],
  });
  assert.deepEqual(ledger.map(event => event.kind), ['skill', 'response', 'command']);
});
