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
    this.dispatchEvent({type: 'focus'});
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

function bootShell(sessions = [{session_id: 'A'}, {session_id: 'B'}]) {
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
  window.DATA = {sessions};
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
    CP: global.window.CP,
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

/** Find actual nodes built by the view, without duplicating render logic. */
function sessionNodes(shell) {
  const visit = node => [node, ...node.children.flatMap(visit)];
  return visit(shell.document.elements['view-container']);
}

function sessionNode(shell, predicate) {
  const node = sessionNodes(shell).find(predicate);
  assert.ok(node, 'Expected session control or panel to be rendered');
  return node;
}

function agentControl(shell, path) {
  return sessionNode(shell, node => node.dataset.agentPath === encodeURIComponent(path));
}

function scopedTotal(shell) {
  return sessionNode(shell, node => node.dataset.sessionPanel === 'total').textContent;
}

function toggleAgent(shell, path, checked) {
  const control = agentControl(shell, path);
  control.checked = checked;
  control.dispatchEvent({type: 'change'});
}

function freezeDeep(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freezeDeep);
    Object.freeze(value);
  }
  return value;
}

test('session shell renders semantic scan-first regions with all paths active', () => {
  const fixture = plain(require('../fixtures/session-analytics/deep-nested-agents.json'));
  fixture.project = '<img src=x onerror=alert(1)>';
  const session = freezeDeep(fixture);
  const shell = bootShell([session]);
  openSession(shell, 'deep', 'basic');

  assert.equal(shell.document.activeElement.textContent, 'Session deep');
  const controls = sessionNodes(shell).filter(node => node.dataset.agentPath);
  assert.equal(controls.length, 5);
  assert.ok(controls.every(node => node.tagName === 'input' && node.type === 'checkbox' && node.checked && !node.indeterminate));
  assert.equal(sessionNode(shell, node => node.attributes.role === 'tree').attributes['aria-label'], 'Agents included in analytics');
  assert.equal(sessionNode(shell, node => node.tagName === 'fieldset').attributes['aria-label'], 'Session analytics scope');
  const radios = sessionNodes(shell).filter(node => node.dataset.sessionScope);
  assert.deepEqual(radios.map(node => [node.type, node.value, node.checked]), [['radio', 'all', true], ['radio', 'period', false]]);
  assert.equal(sessionNode(shell, node => node.dataset.sessionPanel === 'total').attributes['aria-live'], 'polite');
  assert.equal(scopedTotal(shell), 'All: 5 tokens across 5 responses');
  assert.equal(sessionNode(shell, node => node.textContent === fixture.project).innerHTML, '');
  assert.deepEqual(sessionNodes(shell).filter(node => node.dataset.sessionPanel).map(node => node.dataset.sessionPanel),
    ['identity', 'overview', 'agent-filter', 'tracks', 'scope', 'total', 'detail', 'breakdowns', 'details', 'ledger']);
});

test('child changes preserve full-path independence and focused control', () => {
  const session = freezeDeep(plain(require('../fixtures/session-analytics/deep-nested-agents.json')));
  const shell = bootShell([session]);
  openSession(shell, 'deep', 'basic');
  toggleAgent(shell, 'main→left→worker', false);

  assert.equal(agentControl(shell, 'main→left→worker').checked, false);
  assert.equal(agentControl(shell, 'main→right→worker').checked, true);
  assert.equal(agentControl(shell, 'main→left').indeterminate, true);
  assert.equal(agentControl(shell, 'main').indeterminate, true);
  assert.equal(shell.document.activeElement, agentControl(shell, 'main→left→worker'));
  assert.equal(scopedTotal(shell), 'All: 4 tokens across 4 responses');
  assert.equal(session.agent_activity.length, 5);
});

test('parent toggles its entire subtree and empty selection can select all', () => {
  const session = require('../fixtures/session-analytics/deep-nested-agents.json');
  const shell = bootShell([session]);
  openSession(shell, 'deep', 'basic');
  toggleAgent(shell, 'main→left', false);
  assert.equal(agentControl(shell, 'main→left→worker').checked, false);
  assert.equal(scopedTotal(shell), 'All: 3 tokens across 3 responses');
  toggleAgent(shell, 'main', false);
  assert.ok(sessionNodes(shell).some(node => node.textContent === 'No agents selected'));
  assert.equal(scopedTotal(shell), 'All: 0 tokens across 0 responses');
  sessionNode(shell, node => node.tagName === 'button' && node.textContent === 'Select all').dispatchEvent({type: 'click'});
  assert.equal(scopedTotal(shell), 'All: 5 tokens across 5 responses');
  assert.ok(sessionNodes(shell).filter(node => node.dataset.agentPath).every(node => node.checked && !node.indeterminate));
  assert.equal(shell.document.activeElement, agentControl(shell, 'main'));
});

test('scope excludes untimed records only in period mode and keeps overview domain', () => {
  const fixture = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  fixture.agent_activity.push({...fixture.agent_activity[0], timestamp: null, total_tokens: 7});
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');
  const overview = () => sessionNode(shell, node => node.dataset.sessionPanel === 'overview');
  assert.equal(scopedTotal(shell), 'All: 67 tokens across 4 responses');
  const liveTotal = sessionNode(shell, node => node.dataset.sessionPanel === 'total');
  const domain = {...overview().dataset};
  const period = sessionNode(shell, node => node.dataset.sessionScope === 'period');
  period.checked = true;
  period.dispatchEvent({type: 'change'});
  assert.equal(scopedTotal(shell), 'By time period: 60 tokens across 3 responses');
  assert.equal(sessionNode(shell, node => node.dataset.sessionPanel === 'total'), liveTotal,
    'Live region must stay mounted so assistive technology can announce changes');
  assert.deepEqual(overview().dataset, domain);
  assert.equal(shell.document.activeElement.dataset.sessionScope, 'period');
  const all = sessionNode(shell, node => node.dataset.sessionScope === 'all');
  all.checked = true;
  all.dispatchEvent({type: 'change'});
  assert.equal(scopedTotal(shell), 'All: 67 tokens across 4 responses');
});

test('legacy agent labels remain selectable without inventing missing times', () => {
  const session = freezeDeep({session_id: 'legacy', agent_activity: [{agent: 'main→worker', total_tokens: 9}]});
  const shell = bootShell([session]);
  openSession(shell, 'legacy', 'basic');
  assert.equal(agentControl(shell, 'main→worker').checked, true);
  assert.equal(scopedTotal(shell), 'All: 9 tokens across 1 response');
  assert.ok(sessionNodes(shell).some(node => node.textContent === 'Timeline unavailable: no valid timestamps recorded.'));
  assert.equal(sessionNode(shell, node => node.dataset.sessionScope === 'period').disabled, true);
  assert.equal(sessionNode(shell, node => node.dataset.sessionPanel === 'overview').dataset.start, undefined);
  assert.ok(sessionNodes(shell).some(node => node.textContent === 'Not recorded'));
});

test('mixed untimed response disclosure follows active agents in All and period', () => {
  const fixture = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  fixture.agent_activity.push(
    {...fixture.agent_activity[0], timestamp: null, total_tokens: 7},
    {...fixture.agent_activity[0], agent: 'main→worker', agent_path: ['main', 'worker'], timestamp: null, total_tokens: 11},
  );
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');
  const missingTime = () => sessionNode(shell, node => node.dataset.sessionMissingTime !== undefined).textContent;
  assert.equal(scopedTotal(shell), 'All: 78 tokens across 5 responses');
  assert.equal(missingTime(), '2 active responses have no recorded time. Included in All; excluded from By time period and timelines.');
  assert.ok(sessionNodes(shell).some(node => node.textContent === '3 responses across the whole session'));

  const period = sessionNode(shell, node => node.dataset.sessionScope === 'period');
  period.checked = true;
  period.dispatchEvent({type: 'change'});
  assert.equal(scopedTotal(shell), 'By time period: 60 tokens across 3 responses');
  assert.equal(missingTime(), '2 active responses have no recorded time. Included in All; excluded from By time period and timelines.');
  toggleAgent(shell, 'main→worker', false);
  assert.equal(scopedTotal(shell), 'By time period: 60 tokens across 3 responses');
  assert.equal(missingTime(), '1 active response has no recorded time. Included in All; excluded from By time period and timelines.');
  const all = sessionNode(shell, node => node.dataset.sessionScope === 'all');
  all.checked = true;
  all.dispatchEvent({type: 'change'});
  assert.equal(scopedTotal(shell), 'All: 67 tokens across 4 responses');
  assert.equal(missingTime(), '1 active response has no recorded time. Included in All; excluded from By time period and timelines.');
  toggleAgent(shell, 'main', false);
  assert.equal(scopedTotal(shell), 'All: 0 tokens across 0 responses');
  assert.equal(sessionNodes(shell).filter(node => node.dataset.sessionMissingTime !== undefined).length, 0);
});

test('missing attribution and empty activity have explicit states', () => {
  const shell = bootShell([{session_id: 'missing', agent_activity: [{total_tokens: 8}]}]);
  openSession(shell, 'missing', 'basic');
  assert.ok(sessionNodes(shell).some(node => node.textContent === 'Agent paths unavailable.'));
  assert.ok(sessionNodes(shell).some(node => node.textContent === '1 record without an agent path is excluded from analytics.'));
  const empty = bootShell([{session_id: 'empty', agent_paths: [['main']], agent_activity: []}]);
  openSession(empty, 'empty', 'basic');
  assert.ok(sessionNodes(empty).some(node => node.textContent === 'No records in this scope.'));
});

function pressAgentKey(shell, path, key, extra = {}) {
  const event = {type: 'keydown', key, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; }, ...extra};
  agentControl(shell, path).dispatchEvent(event);
  return event;
}

function treeTabStops(shell) {
  return sessionNodes(shell).filter(node => node.dataset.agentPath && node.tabIndex === 0)
    .map(node => decodeURIComponent(node.dataset.agentPath));
}

test('agent tree declares multiple selection and provides one roving checkbox tab stop', () => {
  const shell = bootShell([require('../fixtures/session-analytics/deep-nested-agents.json')]);
  openSession(shell, 'deep', 'basic');
  const tree = sessionNode(shell, node => node.attributes.role === 'tree');
  assert.equal(tree.attributes['aria-multiselectable'], 'true');
  assert.deepEqual(treeTabStops(shell), ['main']);
  const items = sessionNodes(shell).filter(node => node.attributes.role === 'treeitem');
  assert.ok(items.every(node => node.tabIndex === undefined || node.tabIndex === -1));
  assert.deepEqual(items.map(node => [node.attributes['aria-label'], node.attributes['aria-expanded']]), [
    ['main', 'true'], ['main→left', 'true'], ['main→left→worker', undefined],
    ['main→right', 'true'], ['main→right→worker', undefined],
  ]);
  agentControl(shell, 'main→right→worker').focus();
  assert.deepEqual(treeTabStops(shell), ['main→right→worker']);
  assert.equal(scopedTotal(shell), 'All: 5 tokens across 5 responses');
  const period = sessionNode(shell, node => node.dataset.sessionScope === 'period');
  period.checked = true;
  period.dispatchEvent({type: 'change'});
  assert.deepEqual(treeTabStops(shell), ['main→right→worker']);
  assert.equal(shell.document.activeElement.dataset.sessionScope, 'period');
});

test('tree arrow and boundary keys follow visible full-path order without changing selection', () => {
  const shell = bootShell([require('../fixtures/session-analytics/deep-nested-agents.json')]);
  openSession(shell, 'deep', 'basic');
  agentControl(shell, 'main').focus();
  for (const [from, key, destination] of [
    ['main', 'ArrowUp', 'main'],
    ['main', 'ArrowLeft', 'main'],
    ['main', 'ArrowDown', 'main→left'],
    ['main→left', 'ArrowRight', 'main→left→worker'],
    ['main→left→worker', 'ArrowRight', 'main→left→worker'],
    ['main→left→worker', 'ArrowDown', 'main→right'],
    ['main→right', 'ArrowRight', 'main→right→worker'],
    ['main→right→worker', 'ArrowLeft', 'main→right'],
    ['main→right', 'ArrowUp', 'main→left→worker'],
    ['main→left→worker', 'Home', 'main'],
    ['main', 'End', 'main→right→worker'],
    ['main→right→worker', 'ArrowDown', 'main→right→worker'],
  ]) {
    const event = pressAgentKey(shell, from, key);
    assert.equal(event.defaultPrevented, true, `${key} should not scroll the page`);
    assert.equal(shell.document.activeElement, agentControl(shell, destination), `${from} ${key}`);
    assert.deepEqual(treeTabStops(shell), [destination]);
    assert.equal(scopedTotal(shell), 'All: 5 tokens across 5 responses');
  }
  assert.equal(pressAgentKey(shell, 'main→right→worker', 'Tab').defaultPrevented, false);
});

test('tree Space and Enter toggle subtrees once and retain the focused full path', () => {
  const shell = bootShell([require('../fixtures/session-analytics/deep-nested-agents.json')]);
  openSession(shell, 'deep', 'basic');
  agentControl(shell, 'main→left').focus();
  const oldControl = agentControl(shell, 'main→left');
  assert.equal(pressAgentKey(shell, 'main→left', ' ').defaultPrevented, true);
  assert.equal(scopedTotal(shell), 'All: 3 tokens across 3 responses');
  assert.equal(agentControl(shell, 'main→left').checked, false);
  assert.equal(agentControl(shell, 'main→left→worker').checked, false);
  assert.equal(agentControl(shell, 'main→right→worker').checked, true);
  assert.equal(agentControl(shell, 'main').indeterminate, true);
  assert.equal(sessionNode(shell, node => node.attributes.role === 'treeitem' && node.attributes['aria-label'] === 'main').attributes['aria-checked'], 'mixed');
  assert.equal(shell.document.activeElement, agentControl(shell, 'main→left'));
  assert.deepEqual(treeTabStops(shell), ['main→left']);
  assert.ok([...oldControl.listeners.values()].every(list => list.length === 0));
  assert.equal(pressAgentKey(shell, 'main→left', ' ', {repeat: true}).defaultPrevented, true);
  assert.equal(scopedTotal(shell), 'All: 3 tokens across 3 responses');
  assert.equal(pressAgentKey(shell, 'main→left', 'Enter').defaultPrevented, true);
  assert.equal(scopedTotal(shell), 'All: 5 tokens across 5 responses');
  assert.equal(shell.document.activeElement, agentControl(shell, 'main→left'));
  toggleAgent(shell, 'main→right→worker', false);
  assert.equal(scopedTotal(shell), 'All: 4 tokens across 4 responses');
  assert.deepEqual(treeTabStops(shell), ['main→right→worker']);
  assert.equal(shell.document.activeElement, agentControl(shell, 'main→right→worker'));
});

test('cleanup removes stale listeners and destroys only session chart instances', () => {
  const session = require('../fixtures/session-analytics/short-single-agent.json');
  const shell = bootShell([session]);
  openSession(shell, 'short', 'basic');
  const oldBack = sessionNode(shell, node => node.textContent === 'Back to dashboard');
  const oldCheckbox = agentControl(shell, 'main');
  let sessionDestroyed = 0;
  let otherDestroyed = 0;
  global.window.CP.registerChart('session-test', {destroy() { sessionDestroyed += 1; }});
  global.window.CP.registerChart('other-test', {destroy() { otherDestroyed += 1; }});
  shell.buttons.find(button => button.dataset.view === 'detail').dispatchEvent({type: 'click'});
  oldBack.dispatchEvent({type: 'click'});
  oldCheckbox.dispatchEvent({type: 'change'});
  assert.deepEqual(plain(shell.history.state), {dashboardView: 'detail'});
  assert.equal(sessionDestroyed, 1);
  assert.equal(otherDestroyed, 0);
  assert.ok([...oldBack.listeners.values(), ...oldCheckbox.listeners.values()].every(list => list.length === 0));
  global.window.CP.destroyChart('other-test');
});

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
