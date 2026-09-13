'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

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

class FakeEventTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    this.listeners.set(type, listeners.filter(item => item !== listener));
  }

  dispatchEvent(event) {
    event.target ||= this;
    for (const listener of this.listeners.get(event.type) || []) listener(event);
    return !event.defaultPrevented;
  }
}

class FakeElement extends FakeEventTarget {
  constructor(document, tagName = 'div') {
    super();
    this.document = document;
    this.tagName = tagName;
    this.children = [];
    this.style = {};
    this.dataset = {};
    this.attributes = {};
    this.className = '';
    this.innerHTML = '';
    this.textContent = '';
    this.classList = { toggle() {} };
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
    this.innerHTML = '';
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  focus() {
    this.document.activeElement = this;
    this.document.focusCount += 1;
  }
}

class FakeCustomEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.detail = options.detail;
    this.bubbles = Boolean(options.bubbles);
    this.defaultPrevented = false;
  }

  preventDefault() {
    this.defaultPrevented = true;
  }
}

function readShellScript() {
  const template = fs.readFileSync(
    path.resolve(__dirname, '../../src/claude_prospector/templates/dashboard.html'),
    'utf8',
  );
  const scripts = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  return scripts.at(-1)[1];
}

function bootShell() {
  const window = new FakeEventTarget();
  const document = {
    activeElement: null,
    focusCount: 0,
    elements: {},
    createElement(tagName) { return new FakeElement(this, tagName); },
    getElementById(id) { return this.elements[id]; },
    querySelectorAll(selector) {
      return selector === '.view-toggle button' ? this.buttons : [];
    },
  };
  const container = new FakeElement(document);
  const sub = new FakeElement(document);
  document.elements['view-container'] = container;
  document.elements['shell-sub'] = sub;
  document.buttons = ['basic', 'detail', 'advanced', 'mcp', 'agents', 'skills'].map(view => {
    const button = new FakeElement(document, 'button');
    button.dataset.view = view;
    return button;
  });

  const entries = [{state: null, hash: ''}];
  let index = 0;
  const location = {
    pathname: '/dashboard.html',
    search: '',
    get hash() { return entries[index].hash; },
  };
  const history = {
    get state() { return entries[index].state == null ? null : plain(entries[index].state); },
    pushState(state, _title, url) {
      entries.splice(index + 1);
      entries.push({state, hash: new URL(url, 'https://example.test').hash});
      index += 1;
    },
    replaceState(state, _title, url) {
      entries[index] = {state, hash: new URL(url, 'https://example.test').hash};
    },
    back() {
      index -= 1;
      window.dispatchEvent(new FakeCustomEvent('popstate'));
      window.dispatchEvent(new FakeCustomEvent('hashchange'));
    },
  };
  const renderCalls = [];
  const cleanupCalls = [];
  const metrics = {sessionRenderCount: 0};
  const renderView = view => (_root, state = {}) => {
    renderCalls.push({view, state: {...state}});
    return () => cleanupCalls.push(view);
  };
  window.DATA = {sessions: [{session_id: 'A'}, {session_id: 'B'}]};
  window.location = location;
  window.scrollTo = () => {};
  const context = vm.createContext({
    window,
    document,
    history,
    CustomEvent: FakeCustomEvent,
    URLSearchParams,
    URL,
    console,
    CP: {applyChartDefaults() {}, sessionAnalytics: A},
    renderEconomicsBasic: renderView('basic'),
    renderLayoutBDiag: renderView('detail'),
    renderEconomics: renderView('advanced'),
    renderMcpUsage: renderView('mcp'),
    renderAgents: renderView('agents'),
    renderSkills: renderView('skills'),
  });
  vm.runInContext(
    fs.readFileSync(path.resolve(__dirname, '../../src/claude_prospector/static/views/session-detail.js'), 'utf8'),
    context,
  );
  context.renderSessionDetail = (...args) => {
    metrics.sessionRenderCount += 1;
    const cleanup = window.renderSessionDetail(...args);
    return () => {
      cleanupCalls.push('session');
      cleanup();
    };
  };
  vm.runInContext(readShellScript(), context);

  return {
    window, document, history, location, renderCalls, cleanupCalls, metrics,
    buttons: document.buttons,
  };
}

function openSession(shell, sessionId, returnView, returnState) {
  shell.window.dispatchEvent(new FakeCustomEvent('economy:open-session', {
    detail: {sessionId, returnView, returnState},
  }));
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('paired Back events retain the Breakdown return state once', () => {
  const shell = bootShell();

  openSession(shell, 'A', 'detail', {period: '24h', tab: 'sessions'});
  assert.equal(shell.document.activeElement.textContent, 'Session A');
  shell.history.back();

  assert.equal(shell.location.hash, '');
  assert.deepEqual(plain(shell.history.state), {
    dashboardView: 'detail', returnState: {period: '24h', tab: 'sessions'},
  });
  assert.deepEqual(shell.renderCalls.at(-1), {
    view: 'detail', state: {period: '24h', tab: 'sessions'},
  });
  assert.deepEqual(shell.cleanupCalls, ['basic', 'session']);
});

test('shell tab transition clears a stale session route before opening another session', () => {
  const shell = bootShell();

  openSession(shell, 'A', 'basic');
  shell.buttons.find(button => button.dataset.view === 'detail')
    .dispatchEvent(new FakeCustomEvent('click'));
  assert.equal(shell.location.hash, '');
  assert.deepEqual(plain(shell.history.state), {dashboardView: 'detail'});

  openSession(shell, 'B', 'detail', {period: '24h', tab: 'sessions'});
  shell.history.back();

  assert.equal(shell.location.hash, '');
  assert.deepEqual(plain(shell.history.state), {
    dashboardView: 'detail', returnState: {period: '24h', tab: 'sessions'},
  });
  assert.deepEqual(shell.renderCalls.at(-1), {
    view: 'detail', state: {period: '24h', tab: 'sessions'},
  });
  assert.deepEqual(shell.cleanupCalls, ['basic', 'session', 'detail', 'session']);
});

test('keyboard shell tab transition clears a stale session route', () => {
  const shell = bootShell();

  openSession(shell, 'A', 'basic');
  shell.buttons.find(button => button.dataset.view === 'basic')
    .dispatchEvent({type: 'keydown', key: 'ArrowRight', preventDefault() {}});

  assert.equal(shell.location.hash, '');
  assert.deepEqual(plain(shell.history.state), {dashboardView: 'detail'});
  assert.deepEqual(shell.renderCalls.at(-1), {view: 'detail', state: {}});
});

test('reopening the same session after a shell tab transition renders it again', () => {
  const shell = bootShell();

  openSession(shell, 'A', 'basic');
  shell.buttons.find(button => button.dataset.view === 'detail')
    .dispatchEvent(new FakeCustomEvent('click'));
  openSession(shell, 'A', 'detail');

  assert.equal(shell.location.hash, '#session=A');
  assert.deepEqual(plain(shell.history.state), {sessionRoute: true});
  assert.equal(shell.metrics.sessionRenderCount, 2);
  assert.equal(shell.document.activeElement.textContent, 'Session A');
  assert.equal(shell.document.focusCount, 2);
  assert.deepEqual(shell.cleanupCalls, ['basic', 'session', 'detail']);
});

test('parseRoute accepts one encoded session key only', () => {
  assert.deepEqual(
    A.parseRoute('#session=abc%2F123'),
    {kind: 'session', sessionId: 'abc/123'},
  );
  assert.deepEqual(
    A.parseRoute('#session='),
    {kind: 'not-found', sessionId: ''},
  );
  assert.deepEqual(A.parseRoute('#unknown=value'), {kind: 'dashboard'});
  assert.deepEqual(A.parseRoute('#session=one&session=two'), {kind: 'dashboard'});
});

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
