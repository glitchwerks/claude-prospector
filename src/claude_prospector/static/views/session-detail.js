(function () {
  const A = CP.sessionAnalytics;
  const MODES = {all: 'All', period: 'By time period'};
  const TOKEN_FIELDS = ['input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens', 'total_tokens'];
  const TOKEN_LABELS = ['Input', 'Output', 'Cache read', 'Cache creation', 'Total'];
  const EFFORT_COLORS = {low: '#3fb950', medium: '#58a6ff', high: '#d2a8ff', max: '#ffa657', unknown: '#8b949e'};
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
    .session-page input:focus-visible, .session-page button:focus-visible, .session-page h3:focus-visible { outline: 2px solid #58a6ff; outline-offset: 3px; }
    .session-page fieldset { border: 0; margin-bottom: 12px; }
    .session-page legend { color: #f0f6fc; font-weight: 600; margin-bottom: 10px; }
    .session-page fieldset label { display: inline-flex; align-items: center; gap: 8px; margin: 0 18px 8px 0; cursor: pointer; }
    .session-page input:disabled + span { color: #8b949e; }
    .session-page .session-total { font-size: 16px; color: #f0f6fc; font-variant-numeric: tabular-nums; }
    .session-page .session-empty { color: #8b949e; margin: 12px 0; }
    .session-page .session-chart { display: block; width: 100%; height: 160px; overflow: visible; }
    .session-page .session-axis { display: flex; justify-content: space-between; gap: 18px; color: #8b949e; font-size: 11px; }
    .session-page .session-legend { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 12px 0; font-size: 12px; }
    .session-page .session-swatch { display: inline-block; width: 14px; height: 10px; margin-right: 6px; border: 1px solid #c9d1d9; }
    .session-page .session-ranges { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 18px 0; }
    .session-page .session-ranges input { display: block; width: 100%; margin-top: 8px; }
    .session-page .session-ranges output { display: block; color: #8b949e; font-size: 11px; }
    .session-page .session-brush { cursor: crosshair; touch-action: none; }
    .session-page .session-table-wrap { max-width: 100%; overflow-x: auto; margin: 12px 0; }
    .session-page table { border-collapse: collapse; width: 100%; min-width: 640px; overflow-wrap: normal; font-size: 12px; font-variant-numeric: tabular-nums; }
    .session-page caption { text-align: left; color: #8b949e; padding: 8px 0; }
    .session-page th, .session-page td { text-align: right; padding: 7px 10px; border-bottom: 1px solid #30363d; }
    .session-page th:first-child, .session-page td:first-child { text-align: left; }
    .session-page summary { cursor: pointer; padding: 6px 0; }
    .session-page .session-panel { border-top: 1px solid #30363d; margin: 12px 0; padding-top: 8px; }
    .session-page .session-panel td { white-space: pre-wrap; text-align: left; }
    .session-page summary:focus-visible { outline: 2px solid #58a6ff; outline-offset: 3px; }
    .session-page .session-bars { display: flex; align-items: stretch; height: 160px; width: 100%; }
    .session-page .session-bar { flex: 1 1 0; min-width: 12px; border: 0; border-radius: 0; padding: 0 1px; background: transparent; display: flex; align-items: flex-end; cursor: pointer; }
    .session-page .session-bar-fill { display: block; width: 100%; min-height: 2px; border: 1px solid #c9d1d9; }
    .session-page .session-readout { min-height: 3em; color: #c9d1d9; font-size: 12px; }
    .session-page .session-track { padding: 10px 0; border-bottom: 1px solid #21262d; }
    .session-page .session-track label { display: flex; align-items: center; gap: 8px; font-size: 12px; }
    .session-page .session-track svg { width: 100%; height: 40px; display: block; }
    @media (prefers-reduced-motion: reduce) { .session-page *, .session-page *::before, .session-page *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; } }
    @media (max-width: 720px) { .session-page .session-agents { grid-template-columns: 1fr; gap: 16px; } }
    @media (max-width: 480px) { .session-page .session-ranges { grid-template-columns: 1fr; } .session-page .session-overview { padding: 12px; } }
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

  /** Create genuine SVG nodes with text kept outside attribute interpolation. */
  function svgElement(tag, attributes = {}) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    return node;
  }

  /** Unknown and future efforts remain explicit, including without color. */
  function effortLabel(key) { return !key || key === 'unknown' ? 'Unknown' : key; }

  function effortBackground(key) {
    return Object.hasOwn(EFFORT_COLORS, key) && key !== 'unknown' ? EFFORT_COLORS[key]
      : 'repeating-linear-gradient(135deg, #8b949e 0 3px, #30363d 3px 6px)';
  }

  /** Keep every recorded token component available in accessible exact values. */
  function responseLabel(row) {
    return `${activityTime(row.timestamp)}; model ${row.model_full || 'Unknown'} (${row.model || 'unknown'}); effort ${effortLabel(row.effort_key)}; path ${recordPath(row)}; input ${row.input_tokens ?? 'Not recorded'}; output ${row.output_tokens ?? 'Not recorded'}; cache read ${row.cache_read_tokens ?? 'Not recorded'}; cache creation ${row.cache_creation_tokens ?? 'Not recorded'}; total ${row.total_tokens ?? 'Not recorded'} tokens`;
  }

  /** Tables are the nonvisual counterpart of each chart, with exact numbers. */
  function chartTable(key, caption, headers, rows) {
    const disclosure = element('details', 'session-table-wrap');
    const summary = element('summary', undefined, caption);
    summary.dataset.chartSummary = `table:${key}:${caption}`;
    disclosure.append(summary);
    const table = element('table');
    table.dataset.chartTable = key;
    table.append(element('caption', undefined, caption));
    const head = element('thead');
    const heading = element('tr');
    for (const title of headers) {
      const cell = element('th', undefined, title);
      cell.setAttribute('scope', 'col');
      heading.append(cell);
    }
    head.append(heading);
    const body = element('tbody');
    for (const values of rows) {
      const row = element('tr');
      values.forEach((value, index) => {
        const cell = element(index ? 'td' : 'th', undefined, value);
        if (!index) cell.setAttribute('scope', 'row');
        row.append(cell);
      });
      body.append(row);
    }
    table.append(head, body);
    disclosure.append(table);
    return disclosure;
  }

  /** Install a stripe pattern for missing/future effort; IDs are chart-local. */
  function effortPattern(svg, key) {
    const defs = svgElement('defs');
    const pattern = svgElement('pattern', {id: `session-${key}-unknown`, width: 6, height: 6, patternUnits: 'userSpaceOnUse'});
    pattern.append(svgElement('rect', {width: 6, height: 6, fill: '#30363d'}),
      svgElement('path', {d: 'M-1,1 L1,-1 M0,6 L6,0 M5,7 L7,5', stroke: '#8b949e', 'stroke-width': 2}));
    defs.append(pattern);
    svg.append(defs);
    return effort => Object.hasOwn(EFFORT_COLORS, effort) && effort !== 'unknown'
      ? EFFORT_COLORS[effort] : `url(#session-${key}-unknown)`;
  }

  /** Bucket rectangles share both time edges and cumulative y boundaries. */
  function renderOverviewSvg(parent, responses, domain, key = 'overview') {
    const svg = svgElement('svg', {viewBox: '0 0 1000 120', preserveAspectRatio: 'none', role: 'img',
      'aria-label': `${key === 'overview' ? 'Whole-session' : 'Scoped'} tokens by effort; exact totals in the following table`});
    svg.setAttribute('class', 'session-chart');
    svg.dataset.sessionChart = key;
    parent.append(svg);
    const width = svg.getBoundingClientRect().width;
    const buckets = A.bucketResponses(responses, {...domain, width});
    const layers = A.stackEffortBuckets(buckets);
    const maximum = Math.max(1, ...buckets.map(bucket => bucket.total_tokens));
    const x = time => (time - domain.start) / (domain.end - domain.start) * 1000;
    const y = tokens => 120 - tokens / maximum * 120;
    const fill = effortPattern(svg, key);
    for (const layer of layers) {
      // Step over complete buckets, then return along the shared lower edge.
      // No interpolation implies no invented token activity in empty buckets.
      const upper = buckets.flatMap((bucket, index) => [`${x(bucket.start)},${y(layer.upper[index])}`, `${x(bucket.end)},${y(layer.upper[index])}`]);
      const lower = buckets.flatMap((bucket, index) => [`${x(bucket.start)},${y(layer.lower[index])}`, `${x(bucket.end)},${y(layer.lower[index])}`]).reverse();
      const band = svgElement('path', {d: `M${upper.concat(lower).join(' L')} Z`, fill: fill(layer.key)});
      band.dataset.effortLayer = layer.key;
      svg.append(band);
    }
    const axis = element('div', 'session-axis');
    axis.append(element('span', undefined, new Date(domain.start).toISOString()),
      element('span', undefined, `${new Date(domain.end).toISOString()} (exclusive)`));
    parent.append(axis);
    const legend = element('div', 'session-legend');
    const rows = layers.map(layer => {
      const matching = responses.filter(row => (row.effort_key || 'unknown') === layer.key && A.inRange(row, domain));
      const total = A.sumTokens(matching);
      const label = element('span');
      const swatch = element('span', 'session-swatch');
      swatch.style.background = effortBackground(layer.key);
      swatch.setAttribute('aria-hidden', 'true');
      label.append(swatch, element('span', undefined, `${effortLabel(layer.key)}: ${total.total_tokens.toLocaleString()} tokens`));
      legend.append(label);
      return [effortLabel(layer.key), matching.length, ...TOKEN_FIELDS.map(field => total[field])];
    });
    parent.append(legend, chartTable(key, 'Token totals by effort', ['Effort', 'Responses', ...TOKEN_LABELS], rows));
    return svg;
  }

  /** Use equal-width response slots only when each has at least 12 CSS pixels. */
  function renderScopedDetail(parent, responses, domain, listen, controls) {
    const timed = responses.filter(row => domain && A.inRange(row, domain))
      .slice().sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
    if (!timed.length) {
      parent.append(element('p', 'session-empty', 'No timestamped responses in this scope.'));
      return;
    }
    const chart = element('div', 'session-bars');
    parent.append(chart);
    if (A.usesExactBars(timed, chart.getBoundingClientRect().width)) {
      chart.setAttribute('aria-label', 'Exact responses in timestamp order; equal-width slots');
      const maximum = Math.max(1, ...timed.map(row => Number(row.total_tokens || 0)));
      const readout = element('p', 'session-readout', 'Focus or hover a response for its exact values.');
      readout.dataset.responseReadout = '';
      for (const [index, row] of timed.entries()) {
        const label = responseLabel(row);
        const bar = element('button', 'session-bar');
        bar.type = 'button';
        bar.tabIndex = 0;
        bar.dataset.responseBar = String(index);
        bar.setAttribute('aria-label', label);
        bar.title = label;
        const fill = element('span', 'session-bar-fill');
        fill.style.height = `${Number(row.total_tokens || 0) / maximum * 100}%`;
        fill.style.background = effortBackground(row.effort_key);
        fill.setAttribute('aria-hidden', 'true');
        bar.append(fill);
        listen(bar, 'focus', () => { readout.textContent = label; });
        listen(bar, 'pointerenter', () => { readout.textContent = label; });
        controls.set(`response:${index}`, bar);
        chart.append(bar);
      }
      parent.append(element('p', 'muted', 'Exact responses in timestamp order; bar height shows total tokens.'), readout);
    } else {
      chart.style.display = 'none';
      renderOverviewSvg(parent, timed, domain, 'detail');
      parent.append(element('p', 'muted', 'Zoom further for per-response bars'));
    }
    parent.append(chartTable('detail', 'Exact response values', ['Timestamp', 'Full model', 'Model', 'Effort', 'Agent path', ...TOKEN_LABELS],
      timed.map(row => [row.timestamp, row.model_full || 'Unknown', row.model || 'unknown', effortLabel(row.effort_key), recordPath(row), ...TOKEN_FIELDS.map(field => row[field] || 0)])));
  }

  /** Plot independent exact paths on a common clock, including empty rows. */
  function renderAgentTracks(parent, paths, responses, domain, activePaths, allPaths, toggle, listen, controls) {
    parent.append(element('p', 'muted', 'Model: circle = sonnet; diamond = opus; square = haiku; triangle = other. Fill shows effort; stripes = Unknown or future effort. Marker size shows tokens (3–10 px).'));
    const timed = responses.filter(row => domain && A.inRange(row, domain));
    const maximum = timed.reduce((largest, row) => Math.max(largest, Number(row.total_tokens || 0)), 1);
    const rows = [];
    paths.forEach((path, index) => {
      const track = element('div', 'session-track');
      track.dataset.agentTrack = path;
      const label = element('label');
      const checkbox = element('input');
      checkbox.type = 'checkbox';
      const selection = A.selectionState(activePaths, path, allPaths);
      checkbox.checked = selection === 'checked';
      checkbox.indeterminate = selection === 'indeterminate';
      checkbox.dataset.trackToggle = path;
      checkbox.setAttribute('aria-label', `Include ${path} and descendants`);
      listen(checkbox, 'change', () => toggle(path, checkbox.checked));
      controls.set(`track:${path}`, checkbox);
      label.append(checkbox, element('span', undefined, `${path}${activePaths.has(path) ? '' : ' (inactive)'}`));
      track.append(label);
      parent.append(track);
      const matching = timed.filter(row => recordPath(row) === path);
      const totals = A.sumTokens(matching);
      rows.push([path, activePaths.has(path) ? 'Active' : 'Inactive', matching.length, ...TOKEN_FIELDS.map(field => totals[field])]);
      if (!domain) return;
      const svg = svgElement('svg', {role: 'img', 'aria-label': `${path}: ${matching.length} timestamped responses, ${totals.total_tokens} tokens`});
      track.append(svg);
      const width = Math.max(24, svg.getBoundingClientRect().width);
      svg.setAttribute('viewBox', `0 0 ${width} 40`);
      const fill = effortPattern(svg, `track-${index}`);
      svg.append(svgElement('line', {x1: 12, x2: width - 12, y1: 20, y2: 20, stroke: '#30363d'}));
      for (const row of matching) {
        const x = 12 + (Date.parse(row.timestamp) - domain.start) / (domain.end - domain.start) * (width - 24);
        const size = 3 + 7 * Math.sqrt(Number(row.total_tokens || 0) / maximum);
        const marker = svgElement('g', {transform: `translate(${x},20)`, role: 'img', 'aria-label': responseLabel(row)});
        marker.dataset.trackMark = path;
        const title = svgElement('title');
        title.textContent = responseLabel(row);
        const model = String(row.model || '').toLowerCase();
        const shape = model.includes('sonnet') ? svgElement('circle', {r: size})
          : model.includes('opus') ? svgElement('polygon', {points: `0,${-size} ${size},0 0,${size} ${-size},0`})
            : model.includes('haiku') ? svgElement('rect', {x: -size, y: -size, width: size * 2, height: size * 2})
              : svgElement('polygon', {points: `0,${-size} ${size},${size} ${-size},${size}`});
        shape.setAttribute('fill', fill(row.effort_key));
        shape.setAttribute('stroke', '#c9d1d9');
        marker.append(title, shape);
        svg.append(marker);
      }
    });
    parent.append(chartTable('tracks', 'Timestamped response totals by agent path', ['Agent path', 'Selection', 'Responses', ...TOKEN_LABELS], rows));
  }

  /** Preserve exact recorded timestamps, including timezone and precision. */
  function activityTime(value) {
    return Number.isFinite(Date.parse(value)) ? value : 'Time not recorded';
  }

  /** Reuse accessible tables and expose the complete count in native summaries. */
  function buildActivityPanel(name, label, headers, rows, count = rows.length) {
    const details = chartTable(name, label, headers, rows);
    details.className = 'session-panel session-table-wrap';
    details.dataset.sessionPanel = name;
    details.children[0].textContent = `${label} · ${count}`;
    return details;
  }

  /** Collection states remain distinct from observed empty activity. */
  function statusPanel(name, label, status) {
    const details = element('details', 'session-panel');
    details.dataset.sessionPanel = name;
    details.append(element('summary', 'session-panel-summary', `${label} · ${status}`),
      element('p', 'session-panel-status', status));
    return details;
  }

  /** Character counts are a size proxy, never tokens or raw tool results. */
  function formatResultSize(call, mcpState) {
    if (mcpState.result_sizes !== 'collected') return null;
    if (call.result_excluded) return 'Excluded by collection limit';
    if (Number.isFinite(call.result_chars)) return `Estimated result size: ${call.result_chars} characters`;
    return 'Estimated result size: Unavailable';
  }

  /** Only the privacy-safe server/method pair identifies an MCP call. */
  function mcpLabel(call) {
    return `${call.server ?? 'Not recorded'}.${call.method ?? 'Not recorded'}`;
  }

  /** Gate all presentation on collection state, then retain every scoped call. */
  function mcpPanel(scoped, mcpState) {
    if (mcpState.calls === 'not_collected') return statusPanel('mcp', 'MCP', 'Not collected');
    if (mcpState.calls !== 'collected') {
      return statusPanel('mcp', 'MCP', mcpState.warning === 'transcript_unavailable'
        ? 'Unavailable · Transcript unavailable' : 'Unavailable');
    }
    const calls = scoped.mcp || [];
    if (!calls.length) return statusPanel('mcp', 'MCP', '0 calls');
    const sizesCollected = mcpState.result_sizes === 'collected';
    const headers = ['Timestamp', 'Agent path', 'Server.method'];
    if (sizesCollected) headers.push('Estimated result size');
    const rows = calls.map(call => {
      const values = [activityTime(call.timestamp), recordPath(call), mcpLabel(call)];
      if (sizesCollected) values.push(formatResultSize(call, mcpState));
      return values;
    });
    const details = buildActivityPanel('mcp', 'MCP', headers, rows, `${calls.length} calls`);
    const groups = new Map();
    for (const call of calls) {
      const key = mcpLabel(call);
      groups.set(key, (groups.get(key) || 0) + 1);
    }
    const compact = element('ul');
    for (const [key, count] of groups) compact.append(element('li', undefined, `${key} · ${count} calls`));
    const summary = details.children[0];
    const table = details.querySelectorAll('table')[0];
    details.replaceChildren(summary, compact, table);
    return details;
  }

  /** Render all recorded metadata without manufacturing scoped provenance. */
  function factsPanel(session) {
    const facts = session.session_facts;
    const rows = (facts?.metadata || []).map(row => [row.name, row.value,
      activityTime(row.first_seen), (row.agent_paths || []).map(pathKey).join('\n') || 'Not recorded']);
    const details = buildActivityPanel('facts', 'Session facts',
      ['Name', 'Value', 'First seen (session-wide)', 'Contributing agent paths'], rows);
    const summary = details.children[0];
    const table = details.querySelectorAll('table')[0];
    details.replaceChildren(summary,
      element('p', 'muted', 'Session-wide evidence: unaffected by agent selection and time period. First-seen times and contributing paths are recorded across the whole session.'),
      element('p', undefined, `Session-wide effort conflicts: ${facts?.effort_conflicts ?? 'Not recorded'}`), table);
    return details;
  }

  /** Keep every selected path and scoped activity row in expandable tables. */
  function renderActivityPanels(parent, session, scoped, activePaths, mcpState) {
    const agentRows = [...activePaths].sort().map(path => {
      const parts = path.split(CP.AGENT_PATH_SEP);
      const responses = scoped.responses.filter(row => recordPath(row) === path);
      const tokens = A.sumTokens(responses);
      return [path, parts.slice(0, -1).join(CP.AGENT_PATH_SEP) || 'Root', responses.length,
        ...TOKEN_FIELDS.map(field => responses.every(row => Number.isFinite(row[field]))
          ? tokens[field] : 'Not recorded')];
    });
    const activityHeaders = ['Timestamp', 'Agent path'];
    const skillRows = scoped.skills.map(row => [activityTime(row.timestamp), recordPath(row), row.skill ?? 'Not recorded']);
    const commandRows = scoped.commands.map(row => [activityTime(row.timestamp), recordPath(row), row.name ?? 'Not recorded']);
    const responseRows = scoped.responses.map(row => [activityTime(row.timestamp), row.model_full || 'Unknown',
      row.model || 'unknown', effortLabel(row.effort_key), recordPath(row),
      ...TOKEN_FIELDS.map(field => row[field] ?? 'Not recorded')]);
    const kinds = {response: 'Response', skill: 'Skill', command: 'Command', mcp: 'MCP'};
    const ledgerRows = A.mergeLedger(scoped).map(row => {
      const content = row.kind === 'response' ? responseLabel(row)
        : row.kind === 'skill' ? row.skill ?? 'Not recorded'
          : row.kind === 'command' ? row.name ?? 'Not recorded'
            : [mcpLabel(row), formatResultSize(row, mcpState)].filter(value => value !== null).join('; ');
      return [activityTime(row.timestamp), kinds[row.kind], recordPath(row), content];
    });
    const ledger = buildActivityPanel('ledger', 'Event ledger', ['Timestamp', 'Kind', 'Agent path', 'Detail'], ledgerRows);
    ledger.append(element('p', 'muted', 'Equal timestamps do not imply causality. Tie order: Response, Skill, Command, MCP, then source order. Missing times appear last in All and are excluded from By time period.'));
    parent.append(
      buildActivityPanel('agents', 'Agent hierarchy', ['Agent path', 'Parent path', 'Responses', ...TOKEN_LABELS], agentRows),
      Array.isArray(session.skill_activity)
        ? buildActivityPanel('skills', 'Skills', [...activityHeaders, 'Skill'], skillRows)
        : statusPanel('skills', 'Skills', 'Not recorded'),
      Array.isArray(session.command_activity)
        ? buildActivityPanel('commands', 'Commands', [...activityHeaders, 'Command'], commandRows)
        : statusPanel('commands', 'Commands', 'Not recorded'),
      factsPanel(session), mcpPanel(scoped, mcpState),
      buildActivityPanel('responses', 'Responses', ['Timestamp', 'Full model', 'Normalized model', 'Effort', 'Agent path', ...TOKEN_LABELS], responseRows),
      ledger);
  }

  /** Render one session from an immutable source and disposable local state. */
  function renderSessionDetail(container, session, routeState) {
    const fields = ['agent_activity', 'skill_activity', 'command_activity', 'mcp_activity'];
    // Older records may have a path array without a label. Copy only those rows
    // to satisfy the shared scoper's full-path label contract; never edit DATA.
    const source = {...session};
    const mcpState = session.mcp_collection || {calls: 'not_collected', result_sizes: 'not_collected'};
    for (const field of fields) {
      if (field === 'mcp_activity' && mcpState.calls !== 'collected') {
        source[field] = null;
        continue;
      }
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
      focusedPath: treeNodes[0]?.path,
    };
    let disposed = false;
    let listeners = [];
    let renderedControls = new Map();
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

    /** Commit every brush source through the same bounded interval contract. */
    function setRange(start, end, focusKey) {
      state.range = A.normalizeRange(start, end, domain);
      render(focusKey);
    }

    /** Native range commits and pointer drags offer equivalent period selection. */
    function renderBrush(parent, svg, controls) {
      const x = time => (time - domain.start) / (domain.end - domain.start) * 1000;
      const selection = svgElement('rect', {x: x(state.range.start), y: 0,
        width: x(state.range.end) - x(state.range.start), height: 120,
        fill: '#58a6ff', 'fill-opacity': 0.12, stroke: '#79c0ff', 'stroke-width': 2});
      selection.setAttribute('aria-hidden', 'true');
      const overlay = svgElement('rect', {x: 0, y: 0, width: 1000, height: 120, fill: 'transparent', class: 'session-brush'});
      overlay.dataset.sessionBrush = '';
      overlay.setAttribute('aria-hidden', 'true');
      svg.append(selection, overlay);
      let drag = null;
      const timeAt = event => {
        const bounds = svg.getBoundingClientRect();
        const fraction = Math.max(0, Math.min(1, (event.clientX - bounds.left) / Math.max(1, bounds.width)));
        return Math.round(domain.start + fraction * (domain.end - domain.start));
      };
      listen(overlay, 'pointerdown', event => {
        if (event.button !== 0) return;
        event.preventDefault();
        drag = {pointerId: event.pointerId, start: timeAt(event)};
        overlay.setPointerCapture(event.pointerId);
      });
      listen(overlay, 'pointermove', event => {
        if (!drag || event.pointerId !== drag.pointerId) return;
        const preview = A.normalizeRange(drag.start, timeAt(event), domain);
        selection.setAttribute('x', x(preview.start));
        selection.setAttribute('width', x(preview.end) - x(preview.start));
      });
      listen(overlay, 'pointerup', event => {
        if (!drag || event.pointerId !== drag.pointerId) return;
        const start = drag.start;
        drag = null;
        overlay.releasePointerCapture(event.pointerId);
        setRange(start, timeAt(event), 'range:start');
      });
      listen(overlay, 'pointercancel', event => {
        if (!drag || event.pointerId !== drag.pointerId) return;
        drag = null;
        overlay.releasePointerCapture(event.pointerId);
        selection.setAttribute('x', x(state.range.start));
        selection.setAttribute('width', x(state.range.end) - x(state.range.start));
      });
      const ranges = element('div', 'session-ranges');
      for (const [edge, title] of [['start', 'Period start'], ['end', 'Period end (exclusive)']]) {
        const label = element('label', undefined, title);
        const input = element('input');
        input.type = 'range';
        input.min = String(domain.start);
        input.max = String(domain.end);
        input.step = '1';
        input.value = String(state.range[edge]);
        input.dataset.sessionRange = edge;
        input.setAttribute('aria-label', title);
        input.setAttribute('aria-valuetext', new Date(state.range[edge]).toISOString());
        controls.set(`range:${edge}`, input);
        listen(input, 'change', () => setRange(edge === 'start' ? Number(input.value) : state.range.start,
          edge === 'end' ? Number(input.value) : state.range.end, `range:${edge}`));
        label.append(input, element('output', undefined, new Date(state.range[edge]).toISOString()));
        ranges.append(label);
      }
      parent.append(ranges, element('p', 'muted', 'Drag the timeline or use the period sliders. The start is included; the end is excluded. Choose By time period to apply the range.'));
    }

    /** Recompute every scoped region together while keeping identity fixed. */
    function render(focusKey) {
      if (disposed) return;
      if (focusKey?.startsWith('agent:')) state.focusedPath = decodeURIComponent(focusKey.slice(6));
      // Read native state before replacement, even if its toggle event is queued.
      for (const disclosure of afterScope.querySelectorAll('details')) {
        const name = disclosure.dataset.sessionPanel;
        if (name) {
          if (disclosure.open) state.expanded.add(name);
          else state.expanded.delete(name);
        }
      }
      removeListeners();
      CP.destroyChartsByPrefix('session-');
      const scoped = A.scopeSession(source, state.activePaths, state.scope, state.range);
      const overviewScope = A.scopeSession(source, state.activePaths, 'all', state.range);
      const timedResponses = overviewScope.responses.filter(row => Number.isFinite(Date.parse(row.timestamp)));
      const untimedCount = overviewScope.responses.length - timedResponses.length;
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
        ? `${timedResponses.length} responses across the whole session`
        : 'Timeline unavailable: no valid timestamps recorded.'));
      if (untimedCount) {
        const missingTime = element('p', 'session-empty',
          `${untimedCount} active response${untimedCount === 1 ? ' has' : 's have'} no recorded time. Included in All; excluded from By time period and timelines.`);
        missingTime.dataset.sessionMissingTime = String(untimedCount);
        overview.append(missingTime);
      }
      if (allPaths.length && !state.activePaths.size) {
        overview.append(element('p', 'session-empty', 'No agents selected'));
      }

      const agentRegion = element('div', 'session-agents');
      const agents = panel('agent-filter', 'Agents included');
      const tree = element('ul', 'session-tree');
      tree.setAttribute('role', 'tree');
      tree.setAttribute('aria-label', 'Agents included in analytics');
      tree.setAttribute('aria-multiselectable', 'true');
      const agentControls = new Map();

      /** Native checkbox focus is the tree's sole roving tab stop. */
      function setTreeFocus(path) {
        state.focusedPath = path;
        for (const [candidate, checkbox] of agentControls) {
          checkbox.tabIndex = candidate === path ? 0 : -1;
        }
      }

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
        checkbox.tabIndex = node.path === state.focusedPath ? 0 : -1;
        checkbox.dataset.agentPath = encodeURIComponent(node.path);
        checkbox.setAttribute('aria-label', node.path);
        controls.set(`agent:${checkbox.dataset.agentPath}`, checkbox);
        agentControls.set(node.path, checkbox);
        const toggleNode = enabled => {
          state.activePaths = A.setSubtree(state.activePaths, node.path, enabled, allPaths);
          render(`agent:${checkbox.dataset.agentPath}`);
        };
        listen(checkbox, 'focus', () => setTreeFocus(node.path));
        listen(checkbox, 'change', () => toggleNode(checkbox.checked));
        listen(checkbox, 'keydown', event => {
          const paths = [...agentControls.keys()];
          const index = paths.indexOf(node.path);
          let destination = node.path;
          switch (event.key) {
            case 'ArrowDown': destination = paths[Math.min(index + 1, paths.length - 1)]; break;
            case 'ArrowUp': destination = paths[Math.max(0, index - 1)]; break;
            case 'Home': destination = paths[0]; break;
            case 'End': destination = paths[paths.length - 1]; break;
            // All branches remain expanded: horizontal keys move to relatives.
            case 'ArrowRight': destination = node.children[0]?.path || node.path; break;
            case 'ArrowLeft': destination = node.path.split(CP.AGENT_PATH_SEP).slice(0, -1).join(CP.AGENT_PATH_SEP) || node.path; break;
            case ' ':
            case 'Enter':
              // Suppress native Space activation and held-key repeat toggles.
              event.preventDefault();
              if (!event.repeat) toggleNode(selection !== 'checked');
              return;
            default: return;
          }
          event.preventDefault();
          setTreeFocus(destination);
          agentControls.get(destination).focus();
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
      if (domain) {
        const overviewSvg = renderOverviewSvg(overview, timedResponses, domain);
        renderBrush(overview, overviewSvg, controls);
      }
      renderAgentTracks(tracks, allPaths, scoped.responses, state.scope === 'period' ? state.range : domain,
        state.activePaths, allPaths, (path, enabled) => {
          state.activePaths = A.setSubtree(state.activePaths, path, enabled, allPaths);
          render(`track:${path}`);
        }, listen, controls);

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
      const details = panel('details', 'Session details');
      renderActivityPanels(details, session, scoped, state.activePaths, mcpState);
      for (const disclosure of details.querySelectorAll('details')) {
        const name = disclosure.dataset.sessionPanel;
        disclosure.open = state.expanded.has(name);
        controls.set(`panel:${name}`, disclosure.children[0]);
        listen(disclosure, 'toggle', () => {
          if (disclosure.open) state.expanded.add(name);
          else state.expanded.delete(name);
        });
      }
      afterScope.replaceChildren(detail,
        panel('breakdowns', 'Effort, models, and tokens'),
        details);
      renderScopedDetail(detail, scoped.responses, state.scope === 'period' ? state.range : domain, listen, controls);
      const detailHeading = detail.children[0];
      detailHeading.tabIndex = -1;
      controls.set('region:detail', detailHeading);
      for (const summary of page.querySelectorAll('summary')) {
        if (summary.dataset.chartSummary) controls.set(summary.dataset.chartSummary, summary);
      }
      renderedControls = controls;
      if (focusKey) {
        // Either density mode can remove detail controls; keep focus in that region.
        const belongsToDetail = focusKey.startsWith('response:') || focusKey.startsWith('table:detail:');
        const destination = controls.get(focusKey)
          || (belongsToDetail ? detailHeading : null);
        destination?.focus();
      } else heading.focus();
    }

    render();
    let previousWidth = container.getBoundingClientRect().width;
    const resizeObserver = window.ResizeObserver ? new window.ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width;
      if (disposed || !Number.isFinite(width) || width === previousWidth) return;
      previousWidth = width;
      // Read the live focus owner, never a key remembered from an earlier focus.
      const focused = [...renderedControls].find(([, control]) => control === document.activeElement);
      render(focused ? focused[0] : 'resize');
    }) : null;
    resizeObserver?.observe(container);
    return () => {
      if (disposed) return;
      disposed = true;
      resizeObserver?.disconnect();
      removeListeners();
      CP.destroyChartsByPrefix('session-');
      container.replaceChildren();
    };
  }

  window.renderSessionDetail = renderSessionDetail;
})();
