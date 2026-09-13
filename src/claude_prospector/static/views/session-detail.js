(function () {
  const A = CP.sessionAnalytics;
  const MODES = {all: 'All', period: 'By time period'};
  const STYLE = `
    .session-detail.session-page { max-width: none; background: transparent; border: 0; padding: 0; }
    .session-page { overflow-wrap: anywhere; }
    .session-page h2 { margin: 14px 0 6px; font-size: 22px; }
    .session-page h3 { color: #f0f6fc; font-size: 15px; font-weight: 600; margin-bottom: 10px; }
    .session-page p { max-width: 80ch; }
    .session-page .session-project { color: #ffa657; }
    .session-page .session-facts { display: flex; flex-wrap: wrap; gap: 12px 28px; margin-top: 16px; }
    .session-page .session-facts dt { color: #8b949e; font-size: 12px; }
    .session-page .session-facts dd { margin: 3px 0 0; font-variant-numeric: tabular-nums; }
    .session-page .session-region { margin-top: 22px; padding-top: 18px; border-top: 1px solid #21262d; }
    .session-page .session-overview { min-height: 200px; background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px; }
    .session-page .session-agents { display: grid; grid-template-columns: minmax(200px, 1fr) 2fr; gap: 24px; }
    .session-page .session-agents > * { min-width: 0; }
    .session-page .session-tree, .session-page .session-tree ul { list-style: none; padding-left: 18px; }
    .session-page .session-tree { padding-left: 0; }
    .session-page .session-tree label { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; cursor: pointer; }
    .session-page input { accent-color: #58a6ff; }
    .session-page input:focus-visible, .session-page button:focus-visible { outline: 2px solid #58a6ff; outline-offset: 3px; }
    .session-page fieldset { border: 0; margin-bottom: 12px; }
    .session-page legend { color: #f0f6fc; font-weight: 600; margin-bottom: 10px; }
    .session-page fieldset label { display: inline-flex; align-items: center; gap: 8px; margin: 0 18px 8px 0; cursor: pointer; }
    .session-page input:disabled + span { color: #8b949e; }
    .session-page .session-total { font-size: 16px; color: #f0f6fc; font-variant-numeric: tabular-nums; }
    .session-page .session-empty { color: #8b949e; margin: 12px 0; }
    @media (max-width: 720px) { .session-page .session-agents { grid-template-columns: 1fr; gap: 16px; } }
  `;

  /** Create nodes without interpreting transcript content as HTML. */
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  /** Reject incomplete paths instead of inventing attribution. */
  function pathKey(parts) {
    return Array.isArray(parts) && parts.length
      && parts.every(part => typeof part === 'string' && part.length)
      ? parts.join(CP.AGENT_PATH_SEP) : '';
  }

  /** Prefer recorded path arrays, with support for older full-path labels. */
  function recordPath(row) {
    return pathKey(row.agent_path) || (typeof row.agent === 'string' ? row.agent : '');
  }

  /** Derive a fixed half-open domain; absent endpoints remain unavailable. */
  function timelineDomain(session, records) {
    const times = records.map(row => Date.parse(row.timestamp)).filter(Number.isFinite);
    const recordedStart = Date.parse(session.start_time);
    const recordedEnd = Date.parse(session.end_time);
    const start = Number.isFinite(recordedStart) ? recordedStart
      : times.reduce((lowest, time) => Math.min(lowest, time), Infinity);
    const end = (Number.isFinite(recordedEnd) ? recordedEnd
      : times.reduce((highest, time) => Math.max(highest, time), -Infinity)) + 1;
    return Number.isFinite(start) && Number.isFinite(end) && end > start
      ? Object.freeze({start, end}) : null;
  }

  /** Format a recorded time, never replacing missing facts with inferred ones. */
  function recordedTime(value) {
    const timestamp = Date.parse(value);
    return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString() : 'Not recorded';
  }

  /** Build a labelled stable region for the chart/detail renderers. */
  function panel(key, title, className = 'session-region') {
    const node = element('section', className);
    node.dataset.sessionPanel = key;
    node.setAttribute('aria-label', title);
    node.append(element('h3', undefined, title));
    return node;
  }

  /** Render one session from an immutable source and disposable local state. */
  function renderSessionDetail(container, session, routeState) {
    const fields = ['agent_activity', 'skill_activity', 'command_activity', 'mcp_activity'];
    // Older records may have a path array without a label. Copy only those rows
    // to satisfy the shared scoper's full-path label contract; never edit DATA.
    const source = {...session};
    for (const field of fields) {
      source[field] = session[field] == null ? session[field]
        : session[field].map(row => recordPath(row) === row.agent
          ? row : {...row, agent: recordPath(row)});
    }
    const records = fields.flatMap(field => source[field] || []);
    const allPaths = [...new Set([
      ...(session.agent_paths || []).map(pathKey), ...records.map(recordPath),
    ])].filter(Boolean);
    const treeNodes = A.buildAgentTree(allPaths);
    const domain = timelineDomain(session, records);
    const state = {
      scope: 'all',
      range: domain ? {...domain} : {start: null, end: null},
      hasTimeline: domain !== null,
      activePaths: new Set(allPaths),
      expanded: new Set(),
    };
    let disposed = false;
    let listeners = [];
    // Keep the live region and its ancestors mounted while replacing controls
    // and projections around it, so updates are observable to screen readers.
    const page = element('section', 'session-detail session-page');
    const beforeScope = element('div');
    const afterScope = element('div');
    const scope = element('section', 'session-region');
    scope.dataset.sessionPanel = 'scope';
    const scopeControls = element('div');
    const totals = element('p', 'session-total');
    totals.dataset.sessionPanel = 'total';
    totals.setAttribute('aria-live', 'polite');
    totals.setAttribute('aria-atomic', 'true');
    scope.append(scopeControls, totals);
    page.append(element('style', undefined, STYLE), beforeScope, scope, afterScope);
    container.replaceChildren(page);

    /** Track each binding so detached controls cannot act after a rerender. */
    function listen(node, type, handler) {
      node.addEventListener(type, handler);
      listeners.push(() => node.removeEventListener(type, handler));
    }

    function removeListeners() {
      listeners.forEach(remove => remove());
      listeners = [];
    }

    /** Recompute every scoped region together while keeping identity fixed. */
    function render(focusKey) {
      if (disposed) return;
      removeListeners();
      CP.destroyChartsByPrefix('session-');
      const scoped = A.scopeSession(source, state.activePaths, state.scope, state.range);
      const overviewScope = A.scopeSession(source, state.activePaths, 'all', state.range);
      const total = A.sumTokens(scoped.responses).total_tokens;
      const controls = new Map();
      const header = element('header');
      header.dataset.sessionPanel = 'identity';
      const back = element('button', undefined, 'Back to dashboard');
      back.type = 'button';
      listen(back, 'click', routeState.close);
      const heading = element('h2', undefined, `Session ${String(session.session_id)}`);
      heading.tabIndex = -1;
      header.append(back, heading,
        element('p', 'session-project', session.project || 'Project not recorded'),
        element('p', 'muted', session.project_path || 'Project path not recorded'));
      const facts = element('dl', 'session-facts');
      const duration = typeof session.duration_seconds === 'number'
        && Number.isFinite(session.duration_seconds) && session.duration_seconds >= 0
        ? `${session.duration_seconds.toLocaleString()} s` : 'Not recorded';
      for (const [label, value] of [
        ['Start', recordedTime(session.start_time)], ['End', recordedTime(session.end_time)],
        ['Duration', duration], ['Responses', (session.agent_activity || []).length],
        ['Active agent paths', `${state.activePaths.size} of ${allPaths.length}`],
      ]) {
        const fact = element('div');
        fact.append(element('dt', undefined, label), element('dd', undefined, value));
        facts.append(fact);
      }
      header.append(facts);

      const overview = panel('overview', 'Session timeline', 'session-region session-overview');
      if (domain) {
        overview.dataset.start = String(domain.start);
        overview.dataset.end = String(domain.end);
      }
      overview.append(element('p', 'muted', state.hasTimeline
        ? `${overviewScope.responses.length} responses across the whole session`
        : 'Timeline unavailable: no valid timestamps recorded.'));
      if (allPaths.length && !state.activePaths.size) {
        overview.append(element('p', 'session-empty', 'No agents selected'));
      }

      const agentRegion = element('div', 'session-agents');
      const agents = panel('agent-filter', 'Agents included');
      const tree = element('ul', 'session-tree');
      tree.setAttribute('role', 'tree');
      tree.setAttribute('aria-label', 'Agents included in analytics');

      /** Render implicit ancestors as subtree controls, not invented records. */
      function agentNode(node) {
        const item = element('li');
        item.setAttribute('role', 'treeitem');
        item.setAttribute('aria-label', node.path);
        const selection = A.selectionState(state.activePaths, node.path, allPaths);
        item.setAttribute('aria-checked', selection === 'indeterminate' ? 'mixed' : String(selection === 'checked'));
        const label = element('label');
        const checkbox = element('input');
        checkbox.type = 'checkbox';
        checkbox.checked = selection === 'checked';
        checkbox.indeterminate = selection === 'indeterminate';
        checkbox.dataset.agentPath = encodeURIComponent(node.path);
        checkbox.setAttribute('aria-label', node.path);
        controls.set(`agent:${checkbox.dataset.agentPath}`, checkbox);
        listen(checkbox, 'change', () => {
          state.activePaths = A.setSubtree(state.activePaths, node.path, checkbox.checked, allPaths);
          render(`agent:${checkbox.dataset.agentPath}`);
        });
        label.append(checkbox, element('span', undefined, node.label));
        item.append(label);
        if (node.children.length) {
          item.setAttribute('aria-expanded', 'true');
          const group = element('ul');
          group.setAttribute('role', 'group');
          node.children.forEach(child => group.append(agentNode(child)));
          item.append(group);
        }
        return item;
      }
      treeNodes.forEach(node => tree.append(agentNode(node)));
      agents.append(tree);
      if (!allPaths.length) agents.append(element('p', 'session-empty', 'Agent paths unavailable.'));
      if (allPaths.length && !state.activePaths.size) {
        agents.append(element('p', 'session-empty', 'No agents selected'));
        const selectAll = element('button', undefined, 'Select all');
        selectAll.type = 'button';
        listen(selectAll, 'click', () => {
          state.activePaths = new Set(allPaths);
          render(`agent:${encodeURIComponent(treeNodes[0].path)}`);
        });
        agents.append(selectAll);
      }
      const missingPaths = records.filter(row => !recordPath(row)).length;
      if (missingPaths) agents.append(element('p', 'session-empty',
        `${missingPaths} record${missingPaths === 1 ? '' : 's'} without an agent path ${missingPaths === 1 ? 'is' : 'are'} excluded from analytics.`));
      const tracks = panel('tracks', 'Agent activity');
      tracks.append(element('p', 'muted', `${state.activePaths.size} active agent paths`));
      agentRegion.append(agents, tracks);
      beforeScope.replaceChildren(header, overview, agentRegion);

      const fieldset = element('fieldset');
      fieldset.setAttribute('aria-label', 'Session analytics scope');
      fieldset.append(element('legend', undefined, 'Session analytics scope'));
      for (const mode of ['all', 'period']) {
        const label = element('label');
        const radio = element('input');
        radio.type = 'radio';
        radio.name = 'session-scope';
        radio.value = mode;
        radio.dataset.sessionScope = mode;
        radio.checked = state.scope === mode;
        radio.disabled = mode === 'period' && !state.hasTimeline;
        controls.set(`scope:${mode}`, radio);
        listen(radio, 'change', () => {
          if (!radio.checked || radio.disabled) return;
          state.scope = mode;
          render(`scope:${mode}`);
        });
        label.append(radio, element('span', undefined, MODES[mode]));
        fieldset.append(label);
      }
      scopeControls.replaceChildren(fieldset);
      totals.textContent = `${MODES[state.scope]}: ${total.toLocaleString()} tokens across ${scoped.responses.length} response${scoped.responses.length === 1 ? '' : 's'}`;

      const detail = panel('detail', 'Responses in scope');
      const hasRecords = ['responses', 'skills', 'commands', 'mcp'].some(field => (scoped[field] || []).length);
      const emptyMessage = allPaths.length && !state.activePaths.size ? 'No agents selected'
        : !hasRecords ? 'No records in this scope.'
          : !scoped.responses.length ? 'No response records in this scope.' : '';
      if (emptyMessage) detail.append(element('p', 'session-empty', emptyMessage));
      afterScope.replaceChildren(detail,
        panel('breakdowns', 'Effort, models, and tokens'),
        panel('details', 'Session details'),
        panel('ledger', 'Event ledger'));
      if (focusKey) controls.get(focusKey)?.focus();
      else heading.focus();
    }

    render();
    return () => {
      if (disposed) return;
      disposed = true;
      removeListeners();
      CP.destroyChartsByPrefix('session-');
      container.replaceChildren();
    };
  }

  window.renderSessionDetail = renderSessionDetail;
})();
