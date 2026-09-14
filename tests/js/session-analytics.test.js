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

  querySelectorAll(tagName) {
    return this.children.flatMap(child => [
      ...(child.tagName === tagName ? [child] : []), ...child.querySelectorAll(tagName),
    ]);
  }

  getBoundingClientRect() {
    return {left: 0, top: 0, width: this.document.chartWidth, height: 160};
  }

  setPointerCapture(pointerId) { this.capturedPointer = pointerId; }

  releasePointerCapture(pointerId) {
    if (this.capturedPointer === pointerId) this.capturedPointer = null;
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
    chartWidth: 600,
    elements: {},
    createElement(tagName) { return new FakeElement(this, tagName); },
    createElementNS(namespace, tagName) {
      const node = new FakeElement(this, tagName);
      node.namespaceURI = namespace;
      return node;
    },
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
  const resizeObservers = [];
  window.ResizeObserver = class {
    constructor(callback) { this.callback = callback; this.disconnected = false; resizeObservers.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  };
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
    window, document, history, location, renderCalls, cleanupCalls, metrics, resizeObservers,
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
    ['identity', 'overview', 'agent-filter', 'tracks', 'scope', 'total', 'detail', 'breakdowns', 'details',
      'agents', 'skills', 'commands', 'facts', 'mcp', 'responses', 'ledger']);
});

/** Read the native disclosure and its actual table cells. */
function activityPanel(shell, name) {
  return sessionNode(shell, node => node.dataset.sessionPanel === name);
}

function activityRows(shell, name) {
  const body = activityPanel(shell, name).querySelectorAll('tbody')[0];
  assert.ok(body, `Expected ${name} to expose its complete table`);
  return body.children
    .map(row => row.children.map(cell => cell.textContent));
}

function nodeText(node) {
  return [node.textContent, ...node.children.map(nodeText)].join(' ');
}

/** Read the values displayed by a specific labelled table. */
function tableRows(shell, key, caption) {
  const table = sessionNode(shell, node => node.dataset.chartTable === key
    && (!caption || node.children.some(child => child.tagName === 'caption' && child.textContent === caption)));
  return table.querySelectorAll('tbody')[0].children.map(row => row.children.map(cell => cell.textContent));
}

test('scoped breakdowns reconcile effort, normalized and full models, and components in All, period, and child selection', () => {
  const session = freezeDeep({session_id: 'breakdowns',
    agent_paths: [['main'], ['main', 'worker']],
    agent_activity: [
      {timestamp: '2026-09-13T10:00:00Z', agent: 'main', effort_key: 'low', model: 'sonnet', model_full: 'sonnet-one',
        input_tokens: 1, output_tokens: 2, cache_read_tokens: 3, cache_creation_tokens: 4, total_tokens: 10},
      {timestamp: '2026-09-13T10:01:00Z', agent: 'main→worker', effort_key: 'high', model: 'sonnet', model_full: 'sonnet-two',
        input_tokens: 5, output_tokens: 6, cache_read_tokens: 7, cache_creation_tokens: 8, total_tokens: 26},
      {timestamp: '2026-09-13T10:02:00Z', agent: 'main→worker', effort_key: 'high', model: 'opus', model_full: 'opus-one',
        input_tokens: 0, output_tokens: 3, cache_read_tokens: 2, cache_creation_tokens: 1, total_tokens: 6},
    ]});
  const shell = bootShell([session]);
  openSession(shell, session.session_id, 'basic');
  assert.deepEqual(tableRows(shell, 'breakdown-effort'), [
    ['low', '1', '1', '2', '3', '4', '10'], ['high', '2', '5', '9', '9', '9', '32'],
  ]);
  assert.deepEqual(tableRows(shell, 'breakdown-model'), [
    ['sonnet', '2', '6', '8', '10', '12', '36'], ['opus', '1', '0', '3', '2', '1', '6'],
  ]);
  assert.deepEqual(tableRows(shell, 'breakdown-model-full'), [
    ['sonnet-one', '1', '1', '2', '3', '4', '10'], ['sonnet-two', '1', '5', '6', '7', '8', '26'],
    ['opus-one', '1', '0', '3', '2', '1', '6'],
  ]);
  assert.deepEqual(tableRows(shell, 'breakdown-tokens'), [
    ['Input', '6'], ['Output', '11'], ['Cache read', '12'], ['Cache creation', '13'], ['Total', '42'],
  ]);
  moveRange(shell, 'start', Date.parse('2026-09-13T10:01:00Z'));
  moveRange(shell, 'end', Date.parse('2026-09-13T10:02:00Z'));
  assert.equal(tableRows(shell, 'breakdown-tokens').at(-1)[1], '42', 'All ignores the brush');
  chooseScope(shell, 'period');
  assert.match(nodeText(activityPanel(shell, 'breakdowns')), /By time period/);
  for (const [key, label] of [['effort', 'high'], ['model', 'sonnet'], ['model-full', 'sonnet-two']]) {
    assert.deepEqual(tableRows(shell, `breakdown-${key}`), [[label, '1', '5', '6', '7', '8', '26']]);
  }
  assert.deepEqual(tableRows(shell, 'breakdown-tokens'), [
    ['Input', '5'], ['Output', '6'], ['Cache read', '7'], ['Cache creation', '8'], ['Total', '26'],
  ]);
  chooseScope(shell, 'all');
  toggleAgent(shell, 'main', false);
  toggleAgent(shell, 'main→worker', true);
  assert.deepEqual(tableRows(shell, 'breakdown-effort'), [['high', '2', '5', '9', '9', '9', '32']]);
  assert.deepEqual(tableRows(shell, 'breakdown-model'), [
    ['sonnet', '1', '5', '6', '7', '8', '26'], ['opus', '1', '0', '3', '2', '1', '6'],
  ]);
  assert.deepEqual(tableRows(shell, 'breakdown-model-full'), [
    ['sonnet-two', '1', '5', '6', '7', '8', '26'], ['opus-one', '1', '0', '3', '2', '1', '6'],
  ]);
  assert.deepEqual(tableRows(shell, 'breakdown-tokens'), [
    ['Input', '5'], ['Output', '9'], ['Cache read', '9'], ['Cache creation', '9'], ['Total', '32'],
  ]);
});

test('scoped breakdowns retain missing components, known totals, recorded zero, and unknown dimensions', () => {
  const session = freezeDeep({session_id: 'legacy-breakdowns', agent_activity: [
    {timestamp: '2026-09-13T10:00:00Z', agent: 'main', total_tokens: 9, cache_read_tokens: 4, cache_creation_tokens: 1},
    {timestamp: '2026-09-13T10:01:00Z', agent: 'main→worker', effort_key: '__proto__', model: 'constructor', model_full: 'toString',
      input_tokens: 0, output_tokens: 3, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 3},
  ]});
  const shell = bootShell([session]);
  openSession(shell, session.session_id, 'basic');
  assert.deepEqual(tableRows(shell, 'breakdown-tokens'), [
    ['Input', 'Not recorded'], ['Output', 'Not recorded'], ['Cache read', '4'], ['Cache creation', '1'], ['Total', '12'],
  ]);
  for (const [key, label] of [['effort', '__proto__'], ['model', 'constructor'], ['model-full', 'toString']]) {
    assert.deepEqual(tableRows(shell, `breakdown-${key}`), [
      ['Unknown', '1', 'Not recorded', 'Not recorded', '4', '1', '9'], [label, '1', '0', '3', '0', '0', '3'],
    ]);
  }
  chooseScope(shell, 'period');
  moveRange(shell, 'end', Date.parse('2026-09-13T10:01:00Z'));
  assert.deepEqual(tableRows(shell, 'breakdown-tokens'), [
    ['Input', 'Not recorded'], ['Output', 'Not recorded'], ['Cache read', '4'], ['Cache creation', '1'], ['Total', '9'],
  ]);
  chooseScope(shell, 'all');
  toggleAgent(shell, 'main', false);
  toggleAgent(shell, 'main→worker', true);
  assert.deepEqual(tableRows(shell, 'breakdown-tokens'), [
    ['Input', '0'], ['Output', '3'], ['Cache read', '0'], ['Cache creation', '0'], ['Total', '3'],
  ]);
});

test('native detail disclosures retain every response, skill, command, and agent path', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const count = 151;
  const session = {...seed,
    agent_paths: [['main'], ...Array.from({length: count}, (_, index) => ['main', `agent-${index}`])],
    session_facts: {metadata: Array.from({length: count}, (_, index) => ({name: 'version', value: `version-${index}`,
      first_seen: seed.start_time, agent_paths: [['main']]})), effort_conflicts: 0},
    mcp_collection: {calls: 'collected', result_sizes: 'not_collected'},
    mcp_activity: Array.from({length: count}, (_, index) => ({timestamp: seed.start_time,
      agent: 'main', server: 'server', method: `method-${index}`})),
    agent_activity: Array.from({length: count}, (_, index) => ({...seed.agent_activity[0],
      model_full: `full-model-${index}`, input_tokens: index, output_tokens: 2,
      cache_read_tokens: 3, cache_creation_tokens: 4, total_tokens: index + 9})),
    skill_activity: Array.from({length: count}, (_, index) => ({...seed.skill_activity[0], skill: `skill-${index}`})),
    command_activity: Array.from({length: count}, (_, index) => ({...seed.command_activity[0], name: `/command-${index}`})),
  };
  const shell = bootShell([freezeDeep(session)]);
  openSession(shell, 'short', 'basic');
  for (const name of ['agents', 'skills', 'commands', 'facts', 'mcp', 'responses', 'ledger']) {
    const panel = activityPanel(shell, name);
    assert.equal(panel.tagName, 'details');
    assert.equal(panel.children[0].tagName, 'summary');
  }
  for (const [name, label] of [['skills', 'Skills'], ['commands', 'Commands'], ['responses', 'Responses']]) {
    assert.equal(activityRows(shell, name).length, count);
    assert.equal(activityPanel(shell, name).children[0].textContent, `${label} · 151`);
  }
  const responsePanel = activityPanel(shell, 'responses');
  assert.deepEqual(responsePanel.querySelectorAll('thead')[0].children[0].children.map(node => node.textContent),
    ['Timestamp', 'Full model', 'Normalized model', 'Effort', 'Agent path', 'Input', 'Output', 'Cache read', 'Cache creation', 'Total']);
  assert.deepEqual(activityRows(shell, 'responses').at(-1),
    ['2026-09-13T10:00:00Z', 'full-model-150', 'sonnet', 'low', 'main', '150', '2', '3', '4', '159']);
  assert.equal(activityRows(shell, 'skills').at(-1)[2], 'skill-150');
  assert.equal(activityRows(shell, 'commands').at(-1)[2], '/command-150');
  assert.equal(activityRows(shell, 'agents')[0][0], 'main');
  assert.equal(activityRows(shell, 'agents').length, 152);
  assert.equal(activityRows(shell, 'facts').length, 151);
  assert.equal(activityRows(shell, 'facts').at(-1)[1], 'version-150');
  assert.equal(activityRows(shell, 'mcp').length, 151);
  assert.equal(activityRows(shell, 'mcp').at(-1)[2], 'server.method-150');
  assert.equal(activityRows(shell, 'ledger').length, 604);
});

test('detail disclosures keep native open state and summary focus across scope and resize', () => {
  const fixture = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const shell = bootShell([fixture]);
  openSession(shell, 'short', 'basic');
  for (const name of ['agents', 'skills', 'commands', 'facts', 'mcp', 'responses', 'ledger']) {
    const panel = activityPanel(shell, name);
    panel.open = true;
    panel.dispatchEvent({type: 'toggle'});
  }
  chooseScope(shell, 'period');
  for (const name of ['agents', 'skills', 'commands', 'facts', 'mcp', 'responses', 'ledger']) {
    assert.equal(activityPanel(shell, name).open, true, `${name} must remain expanded`);
  }
  const mcp = activityPanel(shell, 'mcp');
  mcp.children[0].focus();
  shell.document.chartWidth = 800;
  shell.resizeObservers[0].callback([{contentRect: {width: 800}}]);
  assert.equal(shell.document.activeElement, activityPanel(shell, 'mcp').children[0]);
  activityPanel(shell, 'mcp').open = false;
  activityPanel(shell, 'mcp').dispatchEvent({type: 'toggle'});
  chooseScope(shell, 'all');
  assert.equal(activityPanel(shell, 'mcp').open, false);
  assert.equal(activityPanel(shell, 'responses').open, true);
});

test('detail activity panels share agent selection and period boundaries', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const child = {agent: 'main→worker', agent_path: ['main', 'worker']};
  const session = {...seed, agent_paths: [['main'], ['main', 'worker']],
    agent_activity: [seed.agent_activity[0], {...seed.agent_activity[1], ...child}],
    skill_activity: [seed.skill_activity[0], {...seed.skill_activity[0], ...child, skill: 'child-skill'}],
    mcp_collection: {calls: 'collected', result_sizes: 'not_collected'},
    mcp_activity: [{timestamp: seed.start_time, agent: 'main', server: 'server', method: 'root'},
      {timestamp: seed.agent_activity[1].timestamp, ...child, server: 'server', method: 'child'},
      {timestamp: null, ...child, server: 'server', method: 'untimed'}],
  };
  const shell = bootShell([freezeDeep(session)]);
  openSession(shell, 'short', 'basic');
  moveRange(shell, 'end', Date.parse(seed.agent_activity[1].timestamp));
  assert.equal(activityRows(shell, 'mcp').length, 3, 'All ignores the narrower brush');
  chooseScope(shell, 'period');
  assert.equal(activityRows(shell, 'responses').length, 1);
  assert.equal(activityRows(shell, 'skills').length, 0);
  assert.equal(activityRows(shell, 'commands').length, 1);
  assert.equal(activityRows(shell, 'mcp').length, 1);
  assert.equal(activityRows(shell, 'ledger').length, 3);
  chooseScope(shell, 'all');
  toggleAgent(shell, child.agent, false);
  assert.equal(activityRows(shell, 'responses').length, 1);
  assert.equal(activityRows(shell, 'skills').length, 1);
  assert.equal(activityRows(shell, 'mcp').length, 1);
  assert.equal(activityRows(shell, 'ledger').length, 4);
  toggleAgent(shell, 'main', false);
  toggleAgent(shell, child.agent, true);
  assert.equal(activityRows(shell, 'commands').length, 0, 'Root commands follow the root path');
  assert.equal(activityRows(shell, 'mcp').length, 2);
  assert.ok(activityRows(shell, 'ledger').some(row => row[0] === 'Time not recorded'));
});

test('session facts keep all conflicting values and explicitly session-wide provenance', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  seed.session_facts = {metadata: [
    {name: 'gitBranch', value: 'main', first_seen: seed.start_time, agent_paths: [['main']]},
    {name: 'gitBranch', value: '<img src=x onerror=alert(1)>', first_seen: seed.end_time,
      agent_paths: [['main'], ['main', 'worker']]},
    {name: 'version', value: '1.2.3', first_seen: seed.start_time, agent_paths: [['main']]},
  ], effort_conflicts: 2};
  const shell = bootShell([freezeDeep(seed)]);
  openSession(shell, 'short', 'basic');
  const expected = [
    ['gitBranch', 'main', seed.start_time, 'main'],
    ['gitBranch', '<img src=x onerror=alert(1)>', seed.end_time, 'main\nmain→worker'],
    ['version', '1.2.3', seed.start_time, 'main'],
  ];
  assert.deepEqual(activityRows(shell, 'facts'), expected);
  assert.match(nodeText(activityPanel(shell, 'facts')), /Session-wide effort conflicts: 2/);
  assert.match(nodeText(activityPanel(shell, 'facts')), /unaffected by agent selection and time period/);
  toggleAgent(shell, 'main', false);
  chooseScope(shell, 'period');
  assert.deepEqual(activityRows(shell, 'facts'), expected);
  assert.ok(sessionNodes(shell).every(node => node.innerHTML === ''));
  assert.ok(!sessionNodes(shell).some(node => node.tagName === 'img'));
});

test('MCP state copy gates activity and distinguishes uncollected unavailable and zero', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  for (const [state, copy] of [
    [undefined, 'Not collected'],
    [{calls: 'not_collected'}, 'Not collected'],
    [{calls: 'unavailable'}, 'Unavailable'],
    [{calls: 'unavailable', warning: 'transcript_unavailable'}, 'Unavailable · Transcript unavailable'],
    [{calls: 'collected', result_sizes: 'not_collected'}, '0 calls'],
  ]) {
    const shell = bootShell([{...seed, mcp_collection: state, mcp_activity: []}]);
    openSession(shell, 'short', 'basic');
    assert.equal(activityPanel(shell, 'mcp').children[0].textContent, `MCP · ${copy}`);
    assert.equal(activityPanel(shell, 'mcp').querySelectorAll('p')[0].textContent, copy);
  }
  const shell = bootShell([{...seed, mcp_collection: {calls: 'not_collected'},
    mcp_activity: [{timestamp: seed.start_time, agent: 'main', server: 'stale', method: 'call'}]}]);
  openSession(shell, 'short', 'basic');
  assert.doesNotMatch(nodeText(activityPanel(shell, 'mcp')), /stale/);
  assert.doesNotMatch(nodeText(activityPanel(shell, 'ledger')), /stale/);
});

test('MCP groups all calls while retaining measured zero excluded and missing sizes safely', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const call = {timestamp: seed.start_time, agent: 'main', server: '<script>server</script>', method: 'method',
    raw_tool_name: 'RAW_SECRET', tool_name: 'RAW_SECRET', content: 'CONTENT_SECRET'};
  const session = {...seed, mcp_collection: {calls: 'collected', result_sizes: 'collected'},
    mcp_activity: [{...call, result_chars: 0}, {...call, result_chars: 200, result_excluded: true}, {...call}]};
  const shell = bootShell([freezeDeep(session)]);
  openSession(shell, 'short', 'basic');
  const panel = activityPanel(shell, 'mcp');
  assert.equal(panel.children[0].textContent, 'MCP · 3 calls');
  assert.match(nodeText(panel), /<script>server<\/script>\.method · 3 calls/);
  assert.deepEqual(activityRows(shell, 'mcp').map(row => row.at(-1)),
    ['Estimated result size: 0 characters', 'Excluded by collection limit', 'Estimated result size: Unavailable']);
  assert.ok(sessionNodes(shell).every(node => node.innerHTML === ''));
  assert.doesNotMatch(nodeText(shell.document.elements['view-container']), /RAW_SECRET|CONTENT_SECRET/);
  const unmeasured = bootShell([{...session, mcp_collection: {calls: 'collected', result_sizes: 'not_collected'}}]);
  openSession(unmeasured, 'short', 'basic');
  assert.ok(activityRows(unmeasured, 'mcp').every(row => row.length === 3));
  assert.doesNotMatch(nodeText(activityPanel(unmeasured, 'mcp')), /Estimated result size|Excluded/);
});

test('rendered ledger retains deterministic ties, full event detail, and missing time last', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const event = {timestamp: seed.start_time, agent: 'main'};
  const session = {...seed, agent_activity: [seed.agent_activity[0], {...seed.agent_activity[0], model_full: 'second-model'}],
    skill_activity: [{...event, skill: 'first'}, {...event, skill: 'second'}],
    command_activity: [{...event, name: '/command'}],
    mcp_collection: {calls: 'collected', result_sizes: 'collected'},
    mcp_activity: [{...event, server: 'server', method: 'method', result_chars: 0},
      {...event, timestamp: null, server: 'server', method: 'last'}]};
  const shell = bootShell([freezeDeep(session)]);
  openSession(shell, 'short', 'basic');
  const rows = activityRows(shell, 'ledger');
  assert.deepEqual(rows.map(row => row[1]), ['Response', 'Response', 'Skill', 'Skill', 'Command', 'MCP', 'MCP']);
  assert.match(rows[0][3], /claude-sonnet-5.*sonnet.*low.*input 1.*output 9.*cache read 0.*cache creation 0.*total 10/);
  assert.match(rows[1][3], /second-model/);
  assert.deepEqual(rows.slice(2, 5).map(row => row[3]), ['first', 'second', '/command']);
  assert.equal(rows[5][3], 'server.method; Estimated result size: 0 characters');
  assert.equal(rows[6][0], 'Time not recorded');
  assert.match(nodeText(activityPanel(shell, 'ledger')), /Equal timestamps do not imply causality/);
});

test('legacy response details never invent missing timestamps or token components', () => {
  const shell = bootShell([{session_id: 'legacy-detail', agent_activity: [{agent: 'main', total_tokens: 9}]}]);
  openSession(shell, 'legacy-detail', 'basic');
  assert.deepEqual(activityRows(shell, 'responses')[0],
    ['Time not recorded', 'Unknown', 'unknown', 'Unknown', 'main',
      'Not recorded', 'Not recorded', 'Not recorded', 'Not recorded', '9']);
  const detail = activityRows(shell, 'ledger')[0][3];
  assert.match(detail, /^Time not recorded;/);
  assert.match(detail, /input Not recorded; output Not recorded; cache read Not recorded; cache creation Not recorded; total 9 tokens/);
  assert.doesNotMatch(detail, /undefined|null/);
});

test('Skills and Commands preserve omitted null and recorded-empty collection states on rerender', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  for (const state of ['omitted', 'null', 'empty']) {
    const fixture = {...seed};
    for (const field of ['skill_activity', 'command_activity']) {
      if (state === 'omitted') delete fixture[field];
      else fixture[field] = state === 'null' ? null : [];
    }
    const shell = bootShell([freezeDeep(fixture)]);
    openSession(shell, 'short', 'basic');
    for (const mode of ['all', 'period']) {
      chooseScope(shell, mode);
      for (const [name, label] of [['skills', 'Skills'], ['commands', 'Commands']]) {
        const panel = activityPanel(shell, name);
        assert.equal(panel.tagName, 'details');
        assert.equal(panel.children[0].tagName, 'summary');
        assert.equal(panel.children[0].textContent,
          `${label} · ${state === 'empty' ? '0' : 'Not recorded'}`, `${state} ${name} in ${mode}`);
        if (state === 'empty') assert.equal(activityRows(shell, name).length, 0);
        else {
          assert.equal(panel.querySelectorAll('p')[0].textContent, 'Not recorded');
          assert.equal(panel.querySelectorAll('table').length, 0);
        }
      }
    }
  }
});

test('agent hierarchy marks incomplete components without losing recorded totals or zero', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const event = {timestamp: seed.start_time, agent: 'main', total_tokens: 9};
  const cases = [
    {responses: [event], expected: ['main', 'Root', '1', 'Not recorded', 'Not recorded', 'Not recorded', 'Not recorded', '9']},
    {responses: [seed.agent_activity[0], {...event, input_tokens: 0, output_tokens: null, cache_read_tokens: 0}],
      expected: ['main', 'Root', '2', '1', 'Not recorded', '0', 'Not recorded', '19']},
    {responses: [seed.agent_activity[0], {...event, total_tokens: null}],
      expected: ['main', 'Root', '2', 'Not recorded', 'Not recorded', 'Not recorded', 'Not recorded', 'Not recorded']},
  ];
  for (const {responses, expected} of cases) {
    const shell = bootShell([freezeDeep({...seed, agent_activity: responses})]);
    openSession(shell, 'short', 'basic');
    assert.deepEqual(activityRows(shell, 'agents')[0], expected);
    const responseRows = activityRows(shell, 'responses');
    const ledgerRows = activityRows(shell, 'ledger');
    chooseScope(shell, 'period');
    assert.deepEqual(activityRows(shell, 'agents')[0], expected);
    assert.deepEqual(activityRows(shell, 'responses'), responseRows);
    assert.deepEqual(activityRows(shell, 'ledger'), ledgerRows);
    moveRange(shell, 'start', Date.parse(seed.start_time) + 1);
    assert.deepEqual(activityRows(shell, 'agents')[0], ['main', 'Root', '0', '0', '0', '0', '0', '0']);
  }
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

for (const [label, extra] of [['single legacy', []], ['mixed legacy', [{
  timestamp: '2026-09-13T10:01:00Z', agent: 'main', input_tokens: 0, output_tokens: 3,
  cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 3,
}]]]) {
  test(`chart tables preserve unavailable components and known totals for ${label} responses at exact and dense widths`, () => {
    const session = freezeDeep({session_id: 'legacy-charts', agent_activity: [
      {timestamp: '2026-09-13T10:00:00Z', agent: 'main', total_tokens: 9, cache_read_tokens: 4, cache_creation_tokens: 1},
      ...extra,
    ]});
    const shell = bootShell([session]);
    openSession(shell, session.session_id, 'basic');
    const totals = extra.length ? ['Not recorded', 'Not recorded', '4', '1', '12']
      : ['Not recorded', 'Not recorded', '4', '1', '9'];
    for (const width of [600, 1]) {
      shell.document.chartWidth = width;
      shell.resizeObservers[0].callback([{contentRect: {width}}]);
      assert.deepEqual(tableRows(shell, 'overview')[0].slice(-5), totals);
      assert.deepEqual(tableRows(shell, 'tracks')[0].slice(-5), totals);
      const exact = tableRows(shell, 'detail', 'Exact response values');
      assert.deepEqual(exact[0].slice(-5), ['Not recorded', 'Not recorded', '4', '1', '9']);
      if (extra.length) assert.deepEqual(exact[1].slice(-5), ['0', '3', '0', '0', '3']);
      if (width === 1) {
        assert.deepEqual(tableRows(shell, 'detail', 'Token totals by effort')[0].slice(-5), totals);
      }
    }
  });
}

test('every unavailable token field remains unavailable in chart tables while recorded zeros stay zero', () => {
  for (const missing of TOKEN_KEYS) {
    const response = {timestamp: '2026-09-13T10:00:00Z', agent: 'main',
      input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_creation_tokens: 0, total_tokens: 0,
      [missing]: null};
    const shell = bootShell([{session_id: 'missing-field', agent_activity: [response]}]);
    shell.document.chartWidth = 1;
    openSession(shell, 'missing-field', 'basic');
    const expected = TOKEN_KEYS.map(field => field === missing ? 'Not recorded' : '0');
    for (const [key, caption] of [['overview'], ['tracks'], ['detail', 'Exact response values'], ['detail', 'Token totals by effort']]) {
      assert.deepEqual(tableRows(shell, key, caption)[0].slice(-5), expected, `${key}: ${missing}`);
    }
  }
});

test('full brush domain includes all retained timed activity beyond response identity bounds and remains half-open', () => {
  const seed = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  const session = freezeDeep({...seed,
    command_activity: [{timestamp: '2026-09-13T09:59:00Z', agent: 'main', name: '/early'}],
    skill_activity: [{timestamp: '2026-09-13T10:03:00Z', agent: 'main', skill: 'late-skill'}],
    mcp_collection: {calls: 'collected', result_sizes: 'not_collected'},
    mcp_activity: [{timestamp: '2026-09-13T10:04:00Z', agent: 'main', server: 'github', method: 'late'}],
  });
  const shell = bootShell([session]);
  openSession(shell, 'short', 'basic');
  const identity = nodeText(activityPanel(shell, 'identity'));
  const initialLedger = activityRows(shell, 'ledger');
  chooseScope(shell, 'period');
  assert.deepEqual(activityRows(shell, 'ledger'), initialLedger, 'The untouched period includes all retained timed events');
  const overview = {...activityPanel(shell, 'overview').dataset};
  assert.equal(overview.start, String(Date.parse('2026-09-13T09:59:00Z')));
  assert.equal(overview.end, String(Date.parse('2026-09-13T10:04:00Z') + 1));
  moveRange(shell, 'start', Date.parse('2026-09-13T09:59:00Z') + 1);
  assert.deepEqual(activityRows(shell, 'commands'), []);
  assert.equal(activityRows(shell, 'skills').length, 1);
  assert.equal(activityRows(shell, 'mcp').length, 1);
  moveRange(shell, 'end', Date.parse('2026-09-13T10:04:00Z'));
  assert.match(nodeText(activityPanel(shell, 'mcp')), /0 calls/);
  assert.equal(activityRows(shell, 'skills').length, 1);
  moveRange(shell, 'end', Date.parse('2026-09-13T10:03:00Z'));
  assert.deepEqual(activityRows(shell, 'skills'), []);
  moveRange(shell, 'end', Date.parse('2026-09-13T10:03:00Z') + 1);
  assert.equal(activityRows(shell, 'skills').length, 1);
  assert.deepEqual(activityPanel(shell, 'overview').dataset, overview);
  assert.equal(nodeText(activityPanel(shell, 'identity')), identity);
  toggleAgent(shell, 'main', false);
  assert.deepEqual(activityPanel(shell, 'overview').dataset, overview, 'Selection cannot shrink the immutable brush domain');
});

for (const control of ['Back', 'heading']) {
  test(`resize retains the mounted ${control} focus owner`, () => {
    const shell = bootShell([require('../fixtures/session-analytics/short-single-agent.json')]);
    openSession(shell, 'short', 'basic');
    const headerControl = () => activityPanel(shell, 'identity').children.find(node =>
      control === 'Back' ? node.tagName === 'button' : node.tagName === 'h2');
    const original = headerControl();
    if (control === 'Back') original.focus();
    else assert.equal(shell.document.activeElement, original, 'The route initially focuses its heading');
    shell.document.chartWidth = 390;
    shell.resizeObservers[0].callback([{contentRect: {width: 390}}]);
    assert.ok(shell.document.activeElement === headerControl(), `The mounted ${control} must keep focus`);
    assert.ok(sessionNodes(shell).includes(shell.document.activeElement));
    if (control === 'Back') {
      headerControl().dispatchEvent({type: 'click'});
      assert.equal(shell.location.hash, '');
      assert.equal(shell.renderCalls.at(-1).view, 'basic');
    }
  });
}

/** Change the real range control, as keyboard/native range commits do. */
function moveRange(shell, edge, value) {
  const input = sessionNode(shell, node => node.dataset.sessionRange === edge);
  input.value = String(value);
  input.dispatchEvent({type: 'change'});
}

function chooseScope(shell, mode) {
  const input = sessionNode(shell, node => node.dataset.sessionScope === mode);
  input.checked = true;
  input.dispatchEvent({type: 'change'});
}

function exactBars(shell) {
  return sessionNodes(shell).filter(node => node.dataset.responseBar !== undefined);
}

test('overview draws shared stepped stack boundaries and offers token totals by effort', () => {
  const seed = require('../fixtures/session-analytics/short-single-agent.json');
  const fixture = {...seed, start_time: new Date(0).toISOString(), end_time: new Date(1999).toISOString(),
    // This two-second chart fixture has no activity in the seed's 2026 clock.
    skill_activity: [], command_activity: [],
    agent_activity: [
      {...seed.agent_activity[0], timestamp: new Date(0).toISOString(), total_tokens: 10},
      {...seed.agent_activity[1], timestamp: new Date(0).toISOString(), total_tokens: 20},
      {...seed.agent_activity[0], timestamp: new Date(1000).toISOString(), output_tokens: 4, total_tokens: 5},
      {...seed.agent_activity[1], timestamp: new Date(1000).toISOString(), input_tokens: 1, output_tokens: 14, total_tokens: 15},
    ]};
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');
  const svg = sessionNode(shell, node => node.dataset.sessionChart === 'overview');
  assert.equal(svg.namespaceURI, 'http://www.w3.org/2000/svg');
  assert.equal(svg.attributes.role, 'img');
  const bands = svg.children.filter(node => node.dataset.effortLayer);
  assert.deepEqual(bands.map(node => [node.dataset.effortLayer, node.attributes.d]), [
    ['low', 'M0,80 L500,80 L500,100 L1000,100 L1000,120 L500,120 L500,120 L0,120 Z'],
    ['high', 'M0,0 L500,0 L500,40 L1000,40 L1000,100 L500,100 L500,80 L0,80 Z'],
  ]);
  const table = sessionNode(shell, node => node.dataset.chartTable === 'overview');
  const rows = table.children.find(node => node.tagName === 'tbody').children;
  assert.deepEqual(rows.map(row => row.children.map(cell => cell.textContent)), [
    ['low', '2', '2', '13', '0', '0', '15'], ['high', '2', '3', '32', '0', '0', '35'],
  ]);
});

test('xhigh is solid red while unknown effort retains its pattern', () => {
  const fixture = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  fixture.agent_activity[0] = {
    ...fixture.agent_activity[0], effort: 'xhigh', effort_key: 'xhigh',
  };
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');

  const xhighBand = sessionNode(shell, node => node.dataset.effortLayer === 'xhigh');
  const unknownBand = sessionNode(shell, node => node.dataset.effortLayer === 'unknown');
  assert.equal(xhighBand.attributes.fill, '#f85149');
  assert.equal(unknownBand.attributes.fill, 'url(#session-overview-unknown)');

  const legendEntry = label => sessionNode(shell, node => node.tagName === 'span'
    && node.children[1]?.textContent.startsWith(`${label}:`));
  assert.equal(legendEntry('xhigh').children[0].style.background, '#f85149');
  assert.match(legendEntry('Unknown').children[0].style.background, /^repeating-linear-gradient/);

  const bars = exactBars(shell);
  assert.equal(bars[0].children[0].style.background, '#f85149');
  assert.match(bars[2].children[0].style.background, /^repeating-linear-gradient/);

  const trackMark = effort => sessionNode(shell, node => node.dataset.trackMark === 'main'
    && node.attributes['aria-label']?.includes(`effort ${effort};`));
  assert.equal(trackMark('xhigh').children[1].attributes.fill, '#f85149');
  assert.equal(trackMark('Unknown').children[1].attributes.fill, 'url(#session-track-0-unknown)');
});

test('labeled keyboard brush controls change only period detail and retain overview domain', () => {
  const session = freezeDeep(plain(require('../fixtures/session-analytics/short-single-agent.json')));
  const shell = bootShell([session]);
  openSession(shell, 'short', 'basic');
  const initialDomain = {...sessionNode(shell, node => node.dataset.sessionPanel === 'overview').dataset};
  const inputs = sessionNodes(shell).filter(node => node.dataset.sessionRange);
  assert.deepEqual(inputs.map(node => [node.type, node.attributes['aria-label'], node.step]), [
    ['range', 'Period start', '1'], ['range', 'Period end (exclusive)', '1'],
  ]);
  assert.equal(exactBars(shell).length, 3);
  moveRange(shell, 'end', Date.parse('2026-09-13T10:01:00Z'));
  assert.equal(exactBars(shell).length, 3);
  assert.equal(scopedTotal(shell), 'All: 60 tokens across 3 responses');
  chooseScope(shell, 'period');
  assert.equal(scopedTotal(shell), 'By time period: 10 tokens across 1 response');
  assert.equal(exactBars(shell).length, 1);
  assert.deepEqual(sessionNode(shell, node => node.dataset.sessionPanel === 'overview').dataset, initialDomain);
  moveRange(shell, 'start', Date.parse(session.end_time) + 5000);
  assert.equal(sessionNode(shell, node => node.dataset.sessionRange === 'end').value, String(Date.parse(session.end_time) + 1));
  assert.equal(shell.document.activeElement.dataset.sessionRange, 'start');
});

test('exact response bars expose every fact and exclude missing-time responses from charts', () => {
  const fixture = plain(require('../fixtures/session-analytics/short-single-agent.json'));
  fixture.agent_activity[0] = {...fixture.agent_activity[0], cache_read_tokens: 3, cache_creation_tokens: 4, total_tokens: 17};
  fixture.agent_activity.push({...fixture.agent_activity[0], timestamp: null});
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');
  const bars = exactBars(shell);
  assert.equal(bars.length, 3);
  assert.ok(bars.every(bar => bar.tagName === 'button' && bar.type === 'button' && bar.tabIndex === 0));
  assert.equal(bars[0].attributes['aria-label'], '2026-09-13T10:00:00Z; model claude-sonnet-5 (sonnet); effort low; path main; input 1; output 9; cache read 3; cache creation 4; total 17 tokens');
  assert.ok(bars[2].attributes['aria-label'].includes('effort Unknown'));
  bars[0].focus();
  assert.equal(sessionNode(shell, node => node.dataset.responseReadout !== undefined).textContent, bars[0].attributes['aria-label']);
  const table = sessionNode(shell, node => node.dataset.chartTable === 'detail');
  assert.equal(table.children.find(node => node.tagName === 'tbody').children.length, 3);
});

test('dense detail switches to exact bars when the period narrows and follows actual CSS width', () => {
  const seed = require('../fixtures/session-analytics/short-single-agent.json');
  const fixture = {...seed, agent_activity: Array.from({length: 51}, (_, index) => ({
    ...seed.agent_activity[0], timestamp: new Date(Date.parse(seed.start_time) + index * 1000).toISOString(),
  }))};
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');
  assert.equal(exactBars(shell).length, 0);
  assert.ok(sessionNode(shell, node => node.textContent === 'Zoom further for per-response bars'));
  assert.ok(sessionNode(shell, node => node.dataset.sessionChart === 'detail'));
  moveRange(shell, 'end', Date.parse(seed.start_time) + 2000);
  chooseScope(shell, 'period');
  assert.equal(exactBars(shell).length, 2);
  shell.document.chartWidth = 23;
  chooseScope(shell, 'period');
  assert.equal(exactBars(shell).length, 0);
  shell.document.chartWidth = 24;
  chooseScope(shell, 'period');
  assert.equal(exactBars(shell).length, 2);
});

test('container resize recomputes chart density and preserves control focus until cleanup', () => {
  const shell = bootShell([require('../fixtures/session-analytics/short-single-agent.json')]);
  openSession(shell, 'short', 'basic');
  const observer = shell.resizeObservers.at(-1);
  assert.ok(observer, 'Responsive charts must observe their container width');
  agentControl(shell, 'main').focus();
  shell.document.chartWidth = 35;
  observer.callback([{contentRect: {width: 35}}]);
  assert.equal(exactBars(shell).length, 0);
  assert.equal(shell.document.activeElement, agentControl(shell, 'main'));
  shell.document.chartWidth = 36;
  observer.callback([{contentRect: {width: 36}}]);
  assert.equal(exactBars(shell).length, 3);
  shell.buttons.find(button => button.dataset.view === 'detail').dispatchEvent({type: 'click'});
  assert.equal(observer.disconnected, true);
  observer.callback([{contentRect: {width: 1200}}]);
  assert.deepEqual(plain(shell.history.state), {dashboardView: 'detail'});
});

test('resize from exact bars to dense detail moves response focus to a mounted detail heading', () => {
  const shell = bootShell([require('../fixtures/session-analytics/short-single-agent.json')]);
  openSession(shell, 'short', 'basic');
  const oldBar = exactBars(shell)[1];
  oldBar.focus();
  shell.document.chartWidth = 35;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 35}}]);
  assert.equal(exactBars(shell).length, 0);
  const focused = shell.document.activeElement;
  assert.ok(sessionNodes(shell).includes(focused), 'Resize must not leave focus on a detached response');
  assert.equal(focused.tagName, 'h3');
  assert.equal(focused.textContent, 'Responses in scope');
  assert.equal(focused.tabIndex, -1);
  shell.document.chartWidth = 36;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 36}}]);
  assert.equal(exactBars(shell).length, 3);
  assert.equal(shell.document.activeElement.textContent, 'Responses in scope');
  assert.ok(sessionNodes(shell).includes(shell.document.activeElement));
});

test('resize restores the focused table summary instead of an earlier agent control', () => {
  const shell = bootShell([require('../fixtures/session-analytics/short-single-agent.json')]);
  openSession(shell, 'short', 'basic');
  agentControl(shell, 'main').focus();
  const oldSummary = sessionNode(shell, node => node.tagName === 'summary' && node.textContent === 'Exact response values');
  const disclosure = sessionNode(shell, node => node.tagName === 'details' && node.children.includes(oldSummary));
  disclosure.open = true;
  oldSummary.focus();
  shell.document.chartWidth = 35;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 35}}]);
  const focused = shell.document.activeElement;
  assert.equal(focused.tagName, 'summary');
  assert.equal(focused.textContent, 'Exact response values');
  assert.notEqual(focused, oldSummary);
  assert.ok(sessionNodes(shell).includes(focused));
  shell.document.chartWidth = 36;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 36}}]);
  assert.equal(shell.document.activeElement.textContent, 'Exact response values');
  assert.ok(sessionNodes(shell).includes(shell.document.activeElement));
});

test('resize from dense detail to exact bars moves disappearing effort-summary focus to its detail heading', () => {
  const shell = bootShell([require('../fixtures/session-analytics/short-single-agent.json')]);
  shell.document.chartWidth = 35;
  openSession(shell, 'short', 'basic');
  assert.equal(exactBars(shell).length, 0);
  const detail = sessionNode(shell, node => node.dataset.sessionPanel === 'detail');
  const oldSummary = detail.querySelectorAll('summary').find(node => node.textContent === 'Token totals by effort');
  assert.ok(oldSummary, 'Dense detail must expose its effort totals summary');
  oldSummary.focus();
  shell.document.chartWidth = 36;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 36}}]);
  assert.equal(exactBars(shell).length, 3);
  assert.ok(!sessionNodes(shell).includes(oldSummary), 'The dense-only summary should disappear');
  const focused = shell.document.activeElement;
  assert.ok(sessionNodes(shell).includes(focused), 'Resize must not leave focus on a detached detail summary');
  assert.equal(focused.tagName, 'h3');
  assert.equal(focused.textContent, 'Responses in scope');
  assert.equal(focused.tabIndex, -1);
  shell.document.chartWidth = 35;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 35}}]);
  assert.equal(shell.document.activeElement.textContent, 'Responses in scope');
  assert.ok(sessionNodes(shell).includes(shell.document.activeElement));
});

test('resize does not steal external focus using a stale session control key', () => {
  const shell = bootShell([require('../fixtures/session-analytics/short-single-agent.json')]);
  openSession(shell, 'short', 'basic');
  agentControl(shell, 'main').focus();
  const outside = shell.buttons.find(button => button.dataset.view === 'detail');
  outside.focus();
  shell.document.chartWidth = 35;
  shell.resizeObservers.at(-1).callback([{contentRect: {width: 35}}]);
  assert.ok(shell.document.activeElement === outside, 'A resize must not steal focus from outside the session');
  assert.equal(exactBars(shell).length, 0);
});

test('cancelled pointer drag leaves the committed half-open range unchanged', () => {
  const fixture = require('../fixtures/session-analytics/short-single-agent.json');
  const shell = bootShell([fixture]);
  openSession(shell, 'short', 'basic');
  const brush = sessionNode(shell, node => node.dataset.sessionBrush !== undefined);
  const initial = sessionNodes(shell).filter(node => node.dataset.sessionRange).map(node => node.value);
  brush.dispatchEvent({type: 'pointerdown', pointerId: 8, button: 0, clientX: 50, preventDefault() {}});
  brush.dispatchEvent({type: 'pointermove', pointerId: 8, clientX: 200});
  brush.dispatchEvent({type: 'pointercancel', pointerId: 8});
  brush.dispatchEvent({type: 'pointerup', pointerId: 8, clientX: 200});
  assert.deepEqual(sessionNodes(shell).filter(node => node.dataset.sessionRange).map(node => node.value), initial);
  assert.equal(brush.capturedPointer, null);
});

test('pointer brush clamps reversed drags and releases old bindings on navigation', () => {
  const fixture = require('../fixtures/session-analytics/short-single-agent.json');
  const shell = bootShell([fixture]);
  openSession(shell, 'short', 'basic');
  const brush = sessionNode(shell, node => node.dataset.sessionBrush !== undefined);
  brush.dispatchEvent({type: 'pointerdown', pointerId: 7, button: 0, clientX: 700, preventDefault() {}});
  brush.dispatchEvent({type: 'pointermove', pointerId: 7, clientX: 300});
  brush.dispatchEvent({type: 'pointerup', pointerId: 7, clientX: 300});
  const start = sessionNode(shell, node => node.dataset.sessionRange === 'start');
  assert.equal(start.value, String(Date.parse(fixture.start_time) + 60001));
  assert.equal(scopedTotal(shell), 'All: 60 tokens across 3 responses');
  chooseScope(shell, 'period');
  assert.equal(scopedTotal(shell), 'By time period: 30 tokens across 1 response');
  assert.ok([...brush.listeners.values()].every(list => list.length === 0));
  const currentBrush = sessionNode(shell, node => node.dataset.sessionBrush !== undefined);
  shell.buttons.find(button => button.dataset.view === 'detail').dispatchEvent({type: 'click'});
  assert.ok([...currentBrush.listeners.values()].every(list => list.length === 0));
});

test('concurrent tracks retain exact paths, zero-response rows, and recursive selection', () => {
  const fixture = plain(require('../fixtures/session-analytics/long-concurrent-agents.json'));
  fixture.agent_paths.push(['main', 'empty']);
  fixture.agent_activity[0].timestamp = fixture.agent_activity[1].timestamp;
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'long-concurrent', 'basic');
  const tracks = () => sessionNodes(shell).filter(node => node.dataset.agentTrack !== undefined);
  assert.deepEqual(tracks().map(node => node.dataset.agentTrack), ['main', 'main→worker', 'main→worker→explorer', 'main→empty']);
  const marks = sessionNodes(shell).filter(node => node.dataset.trackMark !== undefined);
  assert.equal(marks.length, 4);
  assert.equal(marks[0].attributes.transform, marks[2].attributes.transform);
  assert.notEqual(marks[0].children.find(node => ['circle', 'rect', 'polygon'].includes(node.tagName)).tagName,
    marks[2].children.find(node => ['circle', 'rect', 'polygon'].includes(node.tagName)).tagName);
  const toggle = sessionNode(shell, node => node.dataset.trackToggle === 'main→worker');
  toggle.checked = false;
  toggle.dispatchEvent({type: 'change'});
  assert.equal(tracks().length, 4);
  assert.equal(agentControl(shell, 'main→worker→explorer').checked, false);
  assert.equal(agentControl(shell, 'main').indeterminate, true);
  assert.equal(scopedTotal(shell), 'All: 500 tokens across 2 responses');
  assert.equal(shell.document.activeElement.dataset.trackToggle, 'main→worker');
  const table = sessionNode(shell, node => node.dataset.chartTable === 'tracks');
  assert.equal(table.children.find(node => node.tagName === 'tbody').children.length, 4);
});

test('untimed responses do not influence the magnitude scale of timestamped tracks', () => {
  const seed = require('../fixtures/session-analytics/short-single-agent.json');
  const fixture = {...seed, agent_activity: [seed.agent_activity[0],
    {...seed.agent_activity[0], timestamp: null, total_tokens: 1000000}]};
  const shell = bootShell([freezeDeep(fixture)]);
  openSession(shell, 'short', 'basic');
  const marker = sessionNode(shell, node => node.dataset.trackMark === 'main');
  assert.equal(marker.children.find(node => node.tagName === 'circle').attributes.r, '10');
});

test('a response cannot become an exact bar below twelve CSS pixels', () => {
  assert.equal(A.usesExactBars([{}], 11), false);
  assert.equal(A.usesExactBars([{}], 0), false);
});

test('effort stacks reuse cumulative boundaries in stable known and future order', () => {
  assert.equal(typeof A.stackEffortBuckets, 'function', 'Stacking must be available to the renderer');
  const buckets = freezeDeep([
    {by_effort: {zeta: 7, unknown: 5, high: 3, low: 1, alpha: 6, max: 4, medium: 2}},
    {by_effort: {high: 9, low: 4}},
    {by_effort: {}},
  ]);
  assert.deepEqual(A.stackEffortBuckets(buckets), [
    {key: 'low', lower: [0, 0, 0], upper: [1, 4, 0]},
    {key: 'medium', lower: [1, 4, 0], upper: [3, 4, 0]},
    {key: 'high', lower: [3, 4, 0], upper: [6, 13, 0]},
    {key: 'max', lower: [6, 13, 0], upper: [10, 13, 0]},
    {key: 'unknown', lower: [10, 13, 0], upper: [15, 13, 0]},
    {key: 'alpha', lower: [15, 13, 0], upper: [21, 13, 0]},
    {key: 'zeta', lower: [21, 13, 0], upper: [28, 13, 0]},
  ]);
  assert.deepEqual(A.stackEffortBuckets([]), []);
});

test('bucket boundaries assign exact starts, exclude final ends, and retain cache components', () => {
  const response = (time, effort, tokens) => ({timestamp: new Date(time).toISOString(),
    effort_key: effort, input_tokens: tokens, output_tokens: tokens * 2,
    cache_read_tokens: tokens * 3, cache_creation_tokens: tokens * 4, total_tokens: tokens * 10});
  const buckets = A.bucketResponses([
    response(1233, 'low', 100), response(1234, 'low', 1), response(2233, 'high', 2),
    response(2234, 'high', 3), response(3234, null, 4), response(3734, 'max', 100),
    {...response(1234, 'max', 100), timestamp: null},
  ], {start: 1234, end: 3734, width: 18});
  assert.deepEqual(buckets, [
    {start: 1234, end: 2234, by_effort: {low: 10, high: 20}, input_tokens: 3, output_tokens: 6, cache_read_tokens: 9, cache_creation_tokens: 12, total_tokens: 30},
    {start: 2234, end: 3234, by_effort: {high: 30}, input_tokens: 3, output_tokens: 6, cache_read_tokens: 9, cache_creation_tokens: 12, total_tokens: 30},
    {start: 3234, end: 3734, by_effort: {unknown: 40}, input_tokens: 4, output_tokens: 8, cache_read_tokens: 12, cache_creation_tokens: 16, total_tokens: 40},
  ]);
});

test('adaptive buckets cross the one-second ladder and use a bounded fallback duration', () => {
  const bounds = options => A.bucketResponses([], options).map(({start, end}) => [start, end]);
  assert.deepEqual(bounds({start: 0, end: 2000, width: 12}), [[0, 1000], [1000, 2000]]);
  assert.deepEqual(bounds({start: 0, end: 2001, width: 12}), [[0, 2001]]);
  assert.deepEqual(bounds({start: 10, end: 172800013, width: 12}), [[10, 86400012], [86400012, 172800013]]);
});

test('future effort names that match object properties retain their exact bucket totals', () => {
  const buckets = A.bucketResponses([
    {timestamp: new Date(0).toISOString(), effort_key: '__proto__', total_tokens: 10},
    {timestamp: new Date(0).toISOString(), effort_key: 'constructor', total_tokens: 20},
  ], {start: 0, end: 2000, width: 12});
  assert.deepEqual(Object.entries(buckets[0].by_effort), [['__proto__', 10], ['constructor', 20]]);
  assert.deepEqual(A.stackEffortBuckets(buckets), [
    {key: '__proto__', lower: [0, 0], upper: [10, 0]}, {key: 'constructor', lower: [10, 0], upper: [30, 0]},
  ]);
  const seed = require('../fixtures/session-analytics/short-single-agent.json');
  const shell = bootShell([{...seed, agent_activity: [{...seed.agent_activity[0], effort_key: 'constructor'}]}]);
  openSession(shell, 'short', 'basic');
  const layer = sessionNode(shell, node => node.dataset.effortLayer === 'constructor');
  assert.equal(layer.attributes.fill, 'url(#session-overview-unknown)');
});

test('brush normalization sorts, clamps, and keeps a nonempty half-open interval', () => {
  assert.equal(typeof A.normalizeRange, 'function', 'Brush changes need one interval normalizer');
  for (const [start, end, expected] of [
    [80, 20, {start: 20, end: 80}], [-9, 999, {start: 10, end: 100}],
    [100, 100, {start: 99, end: 100}], [-5, -2, {start: 10, end: 11}],
    [50.4, 60.7, {start: 50, end: 61}], [NaN, Infinity, {start: 10, end: 100}],
  ]) assert.deepEqual(A.normalizeRange(start, end, {start: 10, end: 100}), expected);
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
