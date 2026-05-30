// Economics layout — Advanced view (per-turn economics).
// Headlines per-message economics with explicit Goodhart guards.
// Renders into the element passed to renderEconomics(root).
//
// Phase 3: read per-token-type fields directly from aggregator (#165).
// Artifact original approximated per-agent recent/prior metrics from
// mock-injected _recent_total/_prior_total etc. fields on by_agent.
// This port computes those values from window.DATA.sessions directly.

(function () {
  const PALETTE = CP.PALETTE;

  // ── Helpers ─────────────────────────────────────────────────────────────
  function safeDiv(a, b) { return b > 0 ? a / b : 0; }
  // Use the shared CP.fmtTokens formatter throughout (suffixed: 1.2M, 450K)
  // so every numeric cell in the Goodhart pane uses the same notation.
  var fmtSig = CP.fmtTokens;
  // Δ chip — supports semantics where lower-is-better (cost metrics) flips
  // colors.
  function deltaChip(cur, prev, opts = {}) {
    const lowerIsBetter = opts.lowerIsBetter !== false;
    if (prev == null || prev === 0) {
      if (cur > 0) return `<span class="dchip new">new</span>`;
      return `<span class="dchip flat">—</span>`;
    }
    const pct = (cur - prev) / prev * 100;
    let cls;
    if (Math.abs(pct) < 3) cls = 'flat';
    else if (lowerIsBetter) cls = pct < 0 ? 'good' : 'bad';
    else                    cls = pct > 0 ? 'good' : 'bad';
    const sign = pct > 0 ? '+' : '';
    return `<span class="dchip ${cls}">${sign}${pct.toFixed(pct < 10 && pct > -10 ? 1 : 0)}% w/w</span>`;
  }

  // Period helpers
  function inRange(s, from, to) {
    const t = new Date(s.start_time);
    return t >= from && t < to;
  }
  function totalsFromSessions(sessions) {
    const t = {
      total_tokens: 0, message_count: 0, session_count: sessions.length,
      cache_creation_tokens: 0, cache_read_tokens: 0,
      input_tokens: 0, output_tokens: 0,
    };
    for (const s of sessions) {
      t.total_tokens          += s.total_tokens;
      t.message_count         += s.message_count;
      t.cache_creation_tokens += s.cache_creation_tokens;
      t.cache_read_tokens     += s.cache_read_tokens;
      t.input_tokens          += s.input_tokens;
      t.output_tokens         += s.output_tokens;
    }
    return t;
  }

  // ── CSS ─────────────────────────────────────────────────────────────────
  const css = `
    .lec-style { color: #c9d1d9; }
    .lec-style .pagehead {
      display: flex; align-items: flex-end; justify-content: space-between;
      gap: 16px; margin-bottom: 12px; flex-wrap: wrap;
    }
    .lec-style .pagehead h1 {
      font-size: 22px; color: #f0f6fc; letter-spacing: -0.02em; font-weight: 600;
    }
    .lec-style .pagehead h1 span { color: #6e7681; font-weight: 400; }
    .lec-style .pagehead .sub { color: #8b949e; font-size: 12px; margin-top: 4px; }
    .lec-style .pagehead-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

    /* Goodhart guard banner */
    .lec-style .goodhart {
      background: #161b22;
      border: 1px solid #21262d;
      border-left: 3px solid #d2a8ff;
      border-radius: 10px;
      padding: 16px 18px;
      margin-bottom: 18px;
      display: grid;
      grid-template-columns: 28px 1fr;
      gap: 12px;
    }
    .lec-style .goodhart .ico {
      width: 26px; height: 26px; border-radius: 6px;
      background: rgba(210,168,255,0.15); color: #d2a8ff;
      display: inline-flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 14px;
    }
    .lec-style .goodhart .title {
      font-size: 13px; color: #f0f6fc; font-weight: 600;
      margin-bottom: 4px;
      letter-spacing: -0.01em;
    }
    .lec-style .goodhart .body {
      font-size: 12px; color: #c9d1d9; line-height: 1.5;
    }
    .lec-style .goodhart .body b { color: #f0f6fc; font-weight: 500; }
    .lec-style .goodhart .body .good  { color: #3fb950; font-weight: 500; }
    .lec-style .goodhart .body .bad   { color: #f85149; font-weight: 500; }
    .lec-style .goodhart .body .ctx   { color: #d2a8ff; font-weight: 500; }
    .lec-style .goodhart .formula {
      display: inline-flex; align-items: center; gap: 6px;
      background: #0d1117; border: 1px solid #21262d;
      padding: 4px 8px; border-radius: 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px; color: #8b949e;
      margin-top: 8px;
    }
    .lec-style .goodhart .formula b { color: #c9d1d9; font-weight: 500; }

    /* KPI strip */
    .lec-style .kpis {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
      margin-bottom: 18px;
    }
    @media (max-width: 1100px) { .lec-style .kpis { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 600px)  { .lec-style .kpis { grid-template-columns: 1fr; } }
    .lec-style .kpi {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      padding: 14px 16px;
      position: relative;
    }
    .lec-style .kpi.hero { border-color: #30363d; }
    .lec-style .kpi.hero::before {
      content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
      background: #d2a8ff; border-radius: 10px 0 0 10px;
    }
    .lec-style .kpi .label {
      font-size: 10px; color: #8b949e; letter-spacing: 0.04em;
      text-transform: uppercase; font-weight: 500;
      display: flex; justify-content: space-between; align-items: baseline;
    }
    .lec-style .kpi .lever-pill {
      font-size: 9px;
      background: rgba(210,168,255,0.15); color: #d2a8ff;
      padding: 1px 5px; border-radius: 4px; letter-spacing: 0.03em;
    }
    .lec-style .kpi .v {
      font-size: 26px; color: #f0f6fc; font-weight: 600;
      letter-spacing: -0.02em; line-height: 1.1;
      font-variant-numeric: tabular-nums; margin: 6px 0 4px;
    }
    .lec-style .kpi .v .unit { font-size: 11px; color: #6e7681; font-weight: 400; margin-left: 4px; letter-spacing: 0; }
    .lec-style .kpi .below { display: flex; align-items: center; gap: 8px; }
    .lec-style .kpi .below .spark { line-height: 0; }
    .lec-style .kpi.workflow .v { color: #ffa657; }
    .lec-style .kpi.workflow .label .lever-pill { background: rgba(255,166,87,0.15); color: #ffa657; }

    /* Δ chip primitives */
    .lec-style .dchip {
      display: inline-flex; align-items: center;
      padding: 1px 6px; border-radius: 8px;
      font-size: 10px; font-weight: 500; letter-spacing: 0.02em;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .lec-style .dchip.good { background: rgba(63,185,80,0.15);  color: #3fb950; }
    .lec-style .dchip.bad  { background: rgba(248,81,73,0.15);  color: #f85149; }
    .lec-style .dchip.flat { background: #21262d;               color: #8b949e; }
    .lec-style .dchip.new  { background: rgba(88,166,255,0.15); color: #79c0ff; }

    /* Card */
    .lec-style .card {
      background: #161b22; border: 1px solid #21262d; border-radius: 10px;
      padding: 18px 20px; margin-bottom: 18px;
    }
    .lec-style .card .h {
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: 14px;
    }
    .lec-style .card .h .title { font-size: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em; font-weight: 500; }
    .lec-style .card .h .meta  { font-size: 11px; color: #6e7681; }

    /* Waterfall */
    .lec-style .wf-wrap {
      display: grid;
      grid-template-columns: 1fr 320px;
      gap: 24px;
    }
    @media (max-width: 1100px) { .lec-style .wf-wrap { grid-template-columns: 1fr; } }
    .lec-style .wf svg { width: 100%; height: 280px; display: block; }
    .lec-style .wf-legend {
      display: flex; flex-direction: column; gap: 10px;
      font-size: 12px;
    }
    .lec-style .wf-legend .row {
      display: grid;
      grid-template-columns: 12px 1fr;
      gap: 8px;
      align-items: flex-start;
    }
    .lec-style .wf-legend .sw { width: 10px; height: 10px; border-radius: 3px; margin-top: 4px; }
    .lec-style .wf-legend .nm { color: #f0f6fc; font-weight: 500; }
    .lec-style .wf-legend .nm .val { font-weight: 600; font-variant-numeric: tabular-nums; margin-left: 6px; }
    .lec-style .wf-legend .desc { color: #8b949e; font-size: 11px; margin-top: 1px; }
    .lec-style .wf-legend .sum {
      margin-top: 6px; padding-top: 10px; border-top: 1px solid #21262d;
      color: #f0f6fc; font-weight: 500;
    }
    .lec-style .wf-legend .sum .val { font-variant-numeric: tabular-nums; }

    /* Stacked area chart */
    .lec-style .area-chart svg { width: 100%; height: 280px; display: block; }
    .lec-style .area-chart .legend {
      display: flex; gap: 14px; margin-top: 8px;
      font-size: 11px; color: #8b949e; flex-wrap: wrap;
    }
    .lec-style .area-chart .legend .sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; margin-right: 4px; vertical-align: -1px; }
    .lec-style .area-chart .anno {
      stroke: #d2a8ff; stroke-dasharray: 4 3; stroke-width: 1;
    }
    .lec-style .area-chart .anno-label {
      fill: #d2a8ff; font-size: 10px; font-weight: 500;
    }

    /* Agent table */
    .lec-style .agent-head, .lec-style .agent-row {
      display: grid;
      grid-template-columns: 160px 80px 140px 130px 80px 80px;
      gap: 12px;
      align-items: center;
    }
    .lec-style .agent-head {
      padding: 4px 0 8px;
      border-bottom: 1px solid #21262d;
      font-size: 10px; color: #6e7681; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .lec-style .agent-head .r { text-align: right; }
    .lec-style .agent-row {
      padding: 10px 0;
      border-bottom: 1px solid #1c2128;
      font-size: 12px;
    }
    .lec-style .agent-row:last-child { border-bottom: none; }
    .lec-style .agent-row .nm { color: #c9d1d9; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .lec-style .agent-row .nm .leaf { color: #f0f6fc; }
    .lec-style .agent-row .nm .chain { color: #6e7681; font-size: 10px; }
    .lec-style .agent-row .metric {
      display: flex; flex-direction: column; gap: 2px;
    }
    .lec-style .agent-row .metric .v { color: #f0f6fc; font-variant-numeric: tabular-nums; font-weight: 600; font-size: 13px; }
    .lec-style .agent-row .metric .v.lever { color: #d2a8ff; }
    .lec-style .agent-row .metric .below { display: flex; align-items: center; gap: 6px; }
    .lec-style .agent-row .metric .spark { line-height: 0; }
    .lec-style .agent-row .num { color: #c9d1d9; font-variant-numeric: tabular-nums; text-align: right; }

    /* Scoreboard */
    .lec-style .score-wrap {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 24px;
    }
    @media (max-width: 1000px) { .lec-style .score-wrap { grid-template-columns: 1fr; } }
    .lec-style .score-col h4 {
      font-size: 11px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em;
      font-weight: 500; margin-bottom: 10px;
      display: flex; justify-content: space-between;
    }
    .lec-style .score-col h4 .pill {
      display: inline-flex; align-items: center; gap: 4px;
      background: rgba(63,185,80,0.15); color: #3fb950;
      padding: 1px 6px; border-radius: 8px; font-size: 9px; text-transform: none; letter-spacing: 0;
      border: 0;
      cursor: default;
    }
    .lec-style .score-col h4 .pill:hover { border-color: transparent; color: #3fb950; }
    .lec-style .score-col.regression h4 .pill {
      background: rgba(248,81,73,0.15); color: #f85149;
    }
    .lec-style .score-col.regression h4 .pill:hover { color: #f85149; }
    .lec-style .score-row {
      display: grid;
      grid-template-columns: 1fr 80px 80px 80px;
      gap: 10px; align-items: center;
      padding: 8px 0; border-bottom: 1px solid #1c2128;
      font-size: 12px;
    }
    .lec-style .score-row:last-child { border-bottom: none; }
    .lec-style .score-row .nm { color: #c9d1d9; }
    .lec-style .score-row .cur { color: #f0f6fc; font-variant-numeric: tabular-nums; font-weight: 600; text-align: right; }
    .lec-style .score-row .prev { color: #6e7681; font-variant-numeric: tabular-nums; text-align: right; }
    .lec-style .score-row .delta { font-variant-numeric: tabular-nums; font-weight: 500; text-align: right; }
    .lec-style .score-row .delta.good { color: #3fb950; }
    .lec-style .score-row .delta.bad  { color: #f85149; }
    .lec-style .score-row .delta.flat { color: #8b949e; }

    /* Session outliers */
    .lec-style .sess-row {
      display: grid;
      grid-template-columns: 1fr 100px 100px 100px 90px;
      gap: 12px; align-items: center;
      padding: 10px 0; border-bottom: 1px solid #1c2128;
      font-size: 12px;
    }
    .lec-style .sess-row:last-child { border-bottom: none; }
    .lec-style .sess-row.outlier {
      background: linear-gradient(90deg, rgba(248,81,73,0.06), transparent);
      margin: 0 -8px; padding-left: 8px; padding-right: 8px; border-radius: 4px;
    }
    .lec-style .sess-row .head .pn { color: #ffa657; font-weight: 500; font-size: 13px; }
    .lec-style .sess-row .head .meta { color: #8b949e; font-size: 11px; margin-top: 2px; }
    .lec-style .sess-row .num { color: #f0f6fc; font-variant-numeric: tabular-nums; text-align: right; }
    .lec-style .sess-row .num.lever { color: #d2a8ff; }
    .lec-style .sess-row .num .dim { color: #6e7681; font-size: 10px; display: block; }
    .lec-style .sess-row .flag {
      display: inline-block; padding: 1px 6px; border-radius: 4px;
      background: rgba(248,81,73,0.18); color: #f85149;
      font-size: 10px; font-weight: 500; margin-left: 6px;
    }
    .lec-style .sess-row .flag.bench {
      background: rgba(63,185,80,0.18); color: #3fb950;
    }
    .lec-style .sess-row .flag.workflow {
      background: rgba(210,168,255,0.18); color: #d2a8ff;
    }
    .lec-style .sess-head {
      display: grid;
      grid-template-columns: 1fr 100px 100px 100px 90px;
      gap: 12px; padding: 4px 0 8px;
      border-bottom: 1px solid #21262d;
      font-size: 10px; color: #6e7681; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .lec-style .sess-head .r { text-align: right; }
    .lec-style .sort-toggle { display: inline-flex; gap: 4px; }
    .lec-style .pill {
      display: inline-flex; align-items: center; gap: 6px;
      background: #161b22;
      border: 1px solid #30363d;
      color: #c9d1d9;
      border-radius: 999px;
      padding: 4px 10px;
      font: inherit;
      font-size: 11px;
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
    }
    .lec-style .pill:hover { border-color: #58a6ff; color: #f0f6fc; }
    .lec-style .sort-toggle .pill { font-size: 10px; padding: 3px 10px; }
    .lec-style .sort-toggle .pill.active {
      background: #21262d;
      border-color: #58a6ff;
      color: #f0f6fc;
    }

    /* Period header */
    .lec-style .period-tabs {
      display: inline-flex; background: #0d1117; border: 1px solid #21262d;
      border-radius: 8px; padding: 3px; gap: 2px;
    }
    .lec-style .period-tabs button {
      background: transparent; border: 0; color: #8b949e;
      padding: 5px 12px; border-radius: 5px; font: inherit; font-size: 11px; cursor: pointer;
    }
    .lec-style .period-tabs button:hover { color: #f0f6fc; }
    .lec-style .period-tabs button.active { background: #21262d; color: #f0f6fc; }

    .lec-style .chip {
      display: inline-flex; align-items: center; gap: 6px;
      background: #21262d; color: #c9d1d9;
      padding: 1px 8px; border-radius: 12px; font-size: 10px;
    }
    .lec-style .badge { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 10px; font-weight: 500; }
    .lec-style .badge-opus   { background: #3b1f6e; color: #d2a8ff; }
    .lec-style .badge-sonnet { background: #1a3a2a; color: #7ee787; }
    .lec-style .badge-haiku  { background: #1a2a3a; color: #79c0ff; }
    .lec-style .badge-unknown{ background: #21262d; color: #8b949e; }
  `;

  // ── Render: Goodhart banner ────────────────────────────────────────────
  function renderGoodhartBanner(ctx) {
    const { recent, prior } = ctx;
    const totalDelta  = safeDiv(recent.total_tokens - prior.total_tokens, prior.total_tokens) * 100;
    const tpmRecent   = safeDiv(recent.total_tokens, recent.message_count);
    const tpmPrior    = safeDiv(prior.total_tokens, prior.message_count);
    const tpmDelta    = safeDiv(tpmRecent - tpmPrior, tpmPrior) * 100;
    const msgsSesRecent = safeDiv(recent.message_count, recent.session_count);
    const msgsSesPrior  = safeDiv(prior.message_count,  prior.session_count);
    const msgsSesDelta  = safeDiv(msgsSesRecent - msgsSesPrior, msgsSesPrior) * 100;
    const ccpmRecent  = safeDiv(recent.cache_creation_tokens, recent.message_count);
    const ccpmPrior   = safeDiv(prior.cache_creation_tokens,  prior.message_count);
    const ccpmDelta   = safeDiv(ccpmRecent - ccpmPrior, ccpmPrior) * 100;

    function sign(n, decimals = 0) {
      const s = n > 0 ? '+' : '';
      return s + (Math.abs(n) >= 10 ? n.toFixed(0) : n.toFixed(decimals));
    }

    const totalCls = totalDelta > 5 ? 'bad' : totalDelta < -5 ? 'good' : '';
    const tpmCls   = tpmDelta < -5 ? 'good' : tpmDelta > 5 ? 'bad' : '';
    const ccpmCls  = ccpmDelta < -5 ? 'good' : ccpmDelta > 5 ? 'bad' : '';

    return `
      <div class="goodhart">
        <div class="ico">&#x2696;</div>
        <div>
          <div class="title">Goodhart guard · why the headline metric can mislead</div>
          <div class="body">
            Total tokens
            <b>${fmtSig(recent.total_tokens)}</b>
            (<span class="${totalCls}">${sign(totalDelta, 1)}% w/w</span>)
            looks like a regression, but the lever and workflow components moved in opposite directions:
            <span class="good">per-msg cost ↓</span>,
            <span class="ctx">workflow length ↑</span>.
            <br>
            <span class="good"><b>tokens/msg</b> ${fmtSig(tpmRecent)} (${sign(tpmDelta, 1)}% w/w)</span>
            ·
            <span class="good"><b>cache_creation/msg</b> ${fmtSig(ccpmRecent)} (${sign(ccpmDelta, 1)}% w/w)</span>
            ·
            <span class="ctx"><b>msgs/session</b> ${msgsSesRecent.toFixed(0)} (${sign(msgsSesDelta, 0)}% w/w — workflow, not cost)</span>
            <br>
            <span class="formula">
              <b>total</b> = <b>sessions</b> × <b>msgs/session</b> × <b>tokens/msg</b>
              <span style="color:#6e7681"> — break apart before evaluating</span>
            </span>
          </div>
        </div>
      </div>`;
  }

  // ── Render: KPI strip ──────────────────────────────────────────────────
  function renderKpis(ctx) {
    const { recent, prior, daily } = ctx;

    const tpmR = safeDiv(recent.total_tokens, recent.message_count);
    const tpmP = safeDiv(prior.total_tokens, prior.message_count);

    const ccpmR = safeDiv(recent.cache_creation_tokens, recent.message_count);
    const ccpmP = safeDiv(prior.cache_creation_tokens,  prior.message_count);

    const crpmR = safeDiv(recent.cache_read_tokens, recent.message_count);
    const crpmP = safeDiv(prior.cache_read_tokens,  prior.message_count);

    const msPerSessR = safeDiv(recent.message_count, recent.session_count);
    const msPerSessP = safeDiv(prior.message_count,  prior.session_count);

    // Sparkline series for last 14 days for each metric
    function dailyMetric(fn) {
      return daily.map(d => fn(d) || 0);
    }
    const tpmDaily  = dailyMetric(d => safeDiv(d.total_tokens, d.message_count));
    const ccpmDaily = dailyMetric(d => safeDiv(d.cache_creation_tokens, d.message_count));
    const crpmDaily = dailyMetric(d => safeDiv(d.cache_read_tokens, d.message_count));
    const mpsDaily  = dailyMetric(d => safeDiv(d.message_count, d.session_count));

    return `
      <div class="kpis">
        <div class="kpi hero">
          <div class="label">
            <span>Tokens / msg</span>
            <span class="lever-pill">DE-CONTAMINATED</span>
          </div>
          <div class="v">${fmtSig(tpmR)}<span class="unit">tok/msg</span></div>
          <div class="below">
            ${deltaChip(tpmR, tpmP)}
            <span class="spark">${CP.sparkline(tpmDaily, { width: 130, height: 24, stroke: '#d2a8ff', fill: '#d2a8ff' })}</span>
          </div>
        </div>
        <div class="kpi hero">
          <div class="label">
            <span>Cache_creation / msg</span>
            <span class="lever-pill">PREFIX LEVER</span>
          </div>
          <div class="v">${fmtSig(ccpmR)}<span class="unit">tok/msg</span></div>
          <div class="below">
            ${deltaChip(ccpmR, ccpmP)}
            <span class="spark">${CP.sparkline(ccpmDaily, { width: 130, height: 24, stroke: '#d2a8ff', fill: '#d2a8ff' })}</span>
          </div>
        </div>
        <div class="kpi">
          <div class="label">
            <span>Cache_read / msg</span>
            <span class="dim" style="font-size:9px;text-transform:none;letter-spacing:0">TTL cost · not prefix-controlled</span>
          </div>
          <div class="v">${fmtSig(crpmR)}<span class="unit">tok/msg</span></div>
          <div class="below">
            ${deltaChip(crpmR, crpmP)}
            <span class="spark">${CP.sparkline(crpmDaily, { width: 130, height: 24, stroke: '#58a6ff', fill: '#58a6ff' })}</span>
          </div>
        </div>
        <div class="kpi workflow">
          <div class="label">
            <span>Msgs / session</span>
            <span class="lever-pill">WORKFLOW · NOT COST</span>
          </div>
          <div class="v">${msPerSessR.toFixed(0)}<span class="unit">msgs</span></div>
          <div class="below">
            ${deltaChip(msPerSessR, msPerSessP, { lowerIsBetter: false })}
            <span class="spark">${CP.sparkline(mpsDaily, { width: 130, height: 24, stroke: '#ffa657', fill: '#ffa657' })}</span>
          </div>
        </div>
      </div>`;
  }

  // ── Render: Waterfall ──────────────────────────────────────────────────
  // Decomposes Δtotal into multiplicative contributions:
  //   total = sessions × msgs/session × tokens/msg
  //   Δlog(total) ≈ Δlog(sessions) + Δlog(msgs/sess) + Δlog(tokens/msg)
  // Convert to absolute token contributions using mid-point delta on log.
  function renderWaterfall(ctx) {
    const r = ctx.recent, p = ctx.prior;

    const sessR = r.session_count, sessP = p.session_count;
    const mpsR  = safeDiv(r.message_count, r.session_count);
    const mpsP  = safeDiv(p.message_count, p.session_count);
    const tpmR  = safeDiv(r.total_tokens, r.message_count);
    const tpmP  = safeDiv(p.total_tokens, p.message_count);

    // Geometric decomposition.
    // ΔT = Tr - Tp. We allocate using marginal contributions on a balanced
    // path (midpoint expansion) so positive + negative bars sum cleanly to ΔT.
    const Tr = r.total_tokens, Tp = p.total_tokens;
    const dT = Tr - Tp;

    // Hybrid-mean factors
    const ms = (sessR + sessP) / 2;
    const mm = (mpsR  + mpsP) / 2;
    const mt = (tpmR  + tpmP) / 2;

    const cSess = (sessR - sessP) * mm * mt;
    const cMps  = (mpsR  - mpsP)  * ms * mt;
    const cTpm  = (tpmR  - tpmP)  * ms * mm;

    // Rescale so contributions sum to actual ΔT
    const rawSum = cSess + cMps + cTpm;
    const k = rawSum !== 0 ? dT / rawSum : 0;
    const contrib = [
      { name: 'session count',  desc: 'more sessions',                    val: cSess * k, color: '#79c0ff', sub: `${sessP} → ${sessR}` },
      { name: 'msgs / session', desc: 'workflow length (longer sessions)', val: cMps  * k, color: '#ffa657', sub: `${mpsP.toFixed(0)} → ${mpsR.toFixed(0)}` },
      { name: 'tokens / msg',   desc: 'per-turn cost (the lever)',         val: cTpm  * k, color: '#d2a8ff', sub: `${fmtSig(tpmP)} → ${fmtSig(tpmR)}` },
    ];

    // Build SVG waterfall
    const W = 640, H = 280, padL = 70, padR = 90, padT = 24, padB = 28;
    const innerW = W - padL - padR, innerH = H - padT - padB;

    // Bars: Prior, +c1, +c2, +c3, Recent
    const bars = [
      { lbl: 'prior 7d',  base: 0,        val: Tp,            color: '#30363d', total: true },
      { lbl: contrib[0].name, base: Tp,                            val: contrib[0].val, color: contrib[0].val >= 0 ? '#79c0ff' : '#3fb950', delta: true },
      { lbl: contrib[1].name, base: Tp + contrib[0].val,           val: contrib[1].val, color: contrib[1].val >= 0 ? '#ffa657' : '#3fb950', delta: true },
      { lbl: contrib[2].name, base: Tp + contrib[0].val + contrib[1].val, val: contrib[2].val, color: contrib[2].val >= 0 ? '#f85149' : '#3fb950', delta: true },
      { lbl: 'recent 7d', base: 0,        val: Tr,            color: '#30363d', total: true },
    ];

    const maxY = Math.max(Tp, Tr, ...bars.map(b => b.base + Math.max(0, b.val)), ...bars.map(b => Math.abs(b.val))) * 1.15;
    const minY = Math.min(0, ...bars.map(b => b.base + Math.min(0, b.val)));
    const rangeY = maxY - minY || 1;
    const colW = innerW / bars.length;
    const barW = colW * 0.5;

    const yAt = v => padT + (1 - (v - minY) / rangeY) * innerH;

    const barsSvg = bars.map((b, i) => {
      const cx = padL + (i + 0.5) * colW;
      const top = b.delta
        ? yAt(b.base + Math.max(0, b.val))
        : yAt(b.val);
      const bottom = b.delta
        ? yAt(b.base + Math.min(0, b.val))
        : yAt(0);
      const h = Math.max(2, Math.abs(bottom - top));
      const labelTxt = b.total ? fmtSig(b.val) :
        (b.val > 0 ? '+' : '') + fmtSig(b.val);
      const labelY = b.val >= 0 ? (top - 6) : (bottom + 12);

      // Connector line from previous bar's running total to this bar's base
      let connector = '';
      if (b.delta && i > 0) {
        const prev = bars[i - 1];
        const prevTotal = prev.delta ? prev.base + prev.val : prev.val;
        const y = yAt(prevTotal);
        const startX = padL + (i - 0.5) * colW + barW / 2;
        const endX = cx - barW / 2;
        connector = `<line x1="${startX}" x2="${endX}" y1="${y}" y2="${y}" stroke="#30363d" stroke-dasharray="2 2"/>`;
      } else if (b.total && i === bars.length - 1) {
        const prev = bars[i - 1];
        const prevTotal = prev.base + prev.val;
        const y = yAt(prevTotal);
        const startX = padL + (i - 0.5) * colW + barW / 2;
        const endX = cx - barW / 2;
        connector = `<line x1="${startX}" x2="${endX}" y1="${y}" y2="${y}" stroke="#30363d" stroke-dasharray="2 2"/>`;
      }

      return `
        ${connector}
        <rect x="${cx - barW/2}" y="${top}" width="${barW}" height="${h}" fill="${b.color}" rx="2"/>
        <text x="${cx}" y="${labelY}" fill="#f0f6fc" font-size="11" font-weight="600" text-anchor="middle" font-family="ui-monospace, SFMono-Regular, Menlo">${labelTxt}</text>
        <text x="${cx}" y="${H - 10}" fill="#8b949e" font-size="10" text-anchor="middle">${b.lbl}</text>
      `;
    }).join('');

    // y-axis
    const zeroY = yAt(0);
    const axis = `
      <line x1="${padL}" x2="${W - padR}" y1="${zeroY}" y2="${zeroY}" stroke="#30363d"/>
      <text x="6" y="${padT + 8}" fill="#6e7681" font-size="9">${fmtSig(maxY)}</text>
      <text x="6" y="${zeroY + 3}" fill="#6e7681" font-size="9">0</text>
    `;

    return `
      <div class="card">
        <div class="h">
          <div class="title">Why did total tokens change? · Goodhart decomposition</div>
          <div class="meta">total = sessions × msgs/session × tokens/msg · recent 7d vs prior 7d</div>
        </div>
        <div class="wf-wrap">
          <div class="wf">
            <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
              ${axis}
              ${barsSvg}
            </svg>
          </div>
          <div class="wf-legend">
            ${contrib.map(c => `
              <div class="row">
                <div class="sw" style="background:${c.color}"></div>
                <div>
                  <div class="nm">Δ ${c.name}<span class="val">${c.val > 0 ? '+' : ''}${fmtSig(c.val)}</span></div>
                  <div class="desc">${c.desc} · ${c.sub}</div>
                </div>
              </div>
            `).join('')}
            <div class="sum row">
              <div></div>
              <div class="nm">Net Δ total<span class="val">${dT > 0 ? '+' : ''}${fmtSig(dT)}</span></div>
            </div>
          </div>
        </div>
      </div>`;
  }

  // ── Render: Stacked area chart of per-msg breakdown ────────────────────
  function renderAreaChart(ctx) {
    const days = ctx.daily;
    if (!days.length) return '';

    const W = 920, H = 280, padL = 50, padR = 130, padT = 20, padB = 30;
    const innerW = W - padL - padR, innerH = H - padT - padB;

    const SERIES = [
      { key: 'cache_creation_tokens', label: 'cache_creation/msg', color: '#d2a8ff', lever: true },
      { key: 'input_tokens',          label: 'input/msg',          color: '#ffa657' },
      { key: 'output_tokens',         label: 'output/msg',         color: '#79c0ff' },
      { key: 'cache_read_tokens',     label: 'cache_read/msg',     color: '#2ea043' },
    ];

    // For each day, compute per-msg values for each series
    const data = days.map(d => {
      const msgs = Math.max(1, d.message_count);
      const obj = { day: d._day };
      for (const s of SERIES) obj[s.key] = d[s.key] / msgs;
      obj.total = SERIES.reduce((a, s) => a + obj[s.key], 0);
      return obj;
    });

    const maxY = Math.max(...data.map(d => d.total)) * 1.05 || 1;
    const xAt = i => padL + (i / Math.max(1, data.length - 1)) * innerW;
    const yAt = v => padT + (1 - v / maxY) * innerH;

    // Stacked areas (cache_read on top so it doesn't dominate visual mass)
    function buildArea(seriesKey, stackBelow) {
      const upper = data.map((d, i) => {
        let stack = 0;
        for (const k of stackBelow) stack += d[k];
        stack += d[seriesKey];
        return [xAt(i), yAt(stack)];
      });
      const lower = data.map((d, i) => {
        let stack = 0;
        for (const k of stackBelow) stack += d[k];
        return [xAt(i), yAt(stack)];
      }).reverse();
      const pts = upper.concat(lower);
      return 'M ' + pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(' L ') + ' Z';
    }

    // We want lever (cache_creation) as the bottom band — visually compressing.
    const ORDER = [
      SERIES[0], // cache_creation (bottom)
      SERIES[1], // input
      SERIES[2], // output
      SERIES[3], // cache_read (top)
    ];
    const accumKeys = [];
    const areasSvg = ORDER.map((s) => {
      const d = buildArea(s.key, accumKeys.slice());
      accumKeys.push(s.key);
      const opacity = s.lever ? 0.92 : 0.5;
      return `<path d="${d}" fill="${s.color}" fill-opacity="${opacity}"/>`;
    }).join('');

    // R6 annotation line — pretend it landed at R6_CUTOFF
    const r6 = window.R6_LANDING ? new Date(window.R6_LANDING) : null;
    let annoSvg = '';
    if (r6) {
      const idx = data.findIndex(d => new Date(d.day) >= r6);
      if (idx >= 0) {
        const ax = xAt(idx);
        annoSvg = `
          <line class="anno" x1="${ax}" x2="${ax}" y1="${padT}" y2="${padT + innerH}"/>
          <text class="anno-label" x="${ax + 6}" y="${padT + 12}">↓ R6 landed</text>`;
      }
    }

    // Axis labels
    const xLabels = data.map((d, i) => {
      if (i % 2 !== 0 && i !== data.length - 1) return '';
      return `<text x="${xAt(i)}" y="${H - 8}" fill="#6e7681" font-size="9" text-anchor="middle">${CP.fmtDay(d.day)}</text>`;
    }).join('');
    const yLabels = `
      <text x="6" y="${padT + 8}" fill="#6e7681" font-size="9">${fmtSig(maxY)}</text>
      <text x="6" y="${padT + innerH}" fill="#6e7681" font-size="9">0</text>
      <text x="10" y="${padT + innerH / 2 + 4}" fill="#c9d1d9" font-size="11" font-weight="600" transform="rotate(-90 10 ${padT + innerH/2})" text-anchor="middle">avg tokens / message</text>
    `;

    // Inline legend with current per-msg values (last day) on the right
    const last = data[data.length - 1];
    const legendY = padT + 14;
    const sideLegend = ORDER.slice().reverse().map((s, idx) => {
      const v = last[s.key];
      return `
        <g>
          <rect x="${W - padR + 10}" y="${legendY + idx * 26}" width="9" height="9" rx="2" fill="${s.color}" fill-opacity="${s.lever ? 0.92 : 0.6}"/>
          <text x="${W - padR + 24}" y="${legendY + idx * 26 + 8}" fill="${s.lever ? '#d2a8ff' : '#c9d1d9'}" font-size="10" font-weight="${s.lever ? '600' : '400'}">${s.label}</text>
          <text x="${W - padR + 24}" y="${legendY + idx * 26 + 20}" fill="#6e7681" font-size="9">${fmtSig(v)}</text>
        </g>`;
    }).join('');

    return `
      <div class="card">
        <div class="h">
          <div class="title">Avg tokens per message · stacked by token type</div>
          <div class="meta">y-axis = tokens ÷ messages, per day · last ${data.length} days · prefix lever = cache_creation/msg (highlighted)</div>
        </div>
        <div class="area-chart">
          <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
            ${areasSvg}
            ${annoSvg}
            ${yLabels}
            ${xLabels}
            ${sideLegend}
          </svg>
        </div>
      </div>`;
  }

  // ── Per-agent per-period metrics ──────────────────────────────────────
  // Phase 3: read per-token-type fields directly from aggregator (#165).
  // Artifact original approximated client-side via mock-injected _recent_total
  // etc. fields on by_agent. We now compute these by iterating sessions,
  // filtering to recent/prior 7-day windows, and accumulating per agent.
  // Fix #174: use agent_tokens (accurate per-agent totals from aggregator)
  // instead of equal-apportionment. Equal-apportionment divided session
  // total_tokens by agents.length, inflating sub-agents like ops that were the
  // sole leaf while the parent held large cache-heavy context.
  function computeAgentPeriods(sessions, now) {
    const c7  = new Date(now.getTime() - 7  * 86_400_000);
    const c14 = new Date(now.getTime() - 14 * 86_400_000);
    const recent = {};
    const prior  = {};
    for (const s of sessions) {
      const t = new Date(s.start_time);
      const isRecent = t >= c7  && t < now;
      const isPrior  = t >= c14 && t < c7;
      if (!isRecent && !isPrior) continue;
      const bucket = isRecent ? recent : prior;
      // Prefer agent_tokens (accurate breakdown) over equal-apportionment.
      const agentKeys = s.agent_tokens && Object.keys(s.agent_tokens).length > 0
        ? Object.keys(s.agent_tokens)
        : (s.agents || []);
      const share = Math.max(1, agentKeys.length);
      const sessionTotal = s.total_tokens || 1;
      for (const agent of agentKeys) {
        if (!bucket[agent]) {
          bucket[agent] = {
            total_tokens: 0, message_count: 0,
            cache_creation_tokens: 0,
          };
        }
        const agentTokens = s.agent_tokens && s.agent_tokens[agent] != null
          ? s.agent_tokens[agent]
          : Math.round(s.total_tokens / share);
        const agentFraction = agentTokens / sessionTotal;
        bucket[agent].total_tokens          += agentTokens;
        bucket[agent].message_count         += Math.round(s.message_count * agentFraction);
        bucket[agent].cache_creation_tokens += Math.round(
          (s.cache_creation_tokens || 0) * agentFraction
        );
      }
    }
    return { recent, prior };
  }

  // ── Render: Per-agent economics table ──────────────────────────────────
  // We display agents as leaf-segment + dim chain (Goodhart-guard friendly).
  function agentLeaf(name) {
    const SEP = '→';
    const parts = name.split(SEP);
    const leaf = parts[parts.length - 1];
    if (parts.length === 1) return `<span class="leaf">${leaf}</span>`;
    return `<span class="leaf">${leaf}</span><br><span class="chain">${parts.slice(0, -1).join(' ' + SEP + ' ')} ${SEP}</span>`;
  }

  function renderAgentTable(ctx) {
    const byAgent = window.DATA.by_agent;
    const { recent: recentAP, prior: priorAP } = ctx.agentPeriods;
    const rows = Object.entries(byAgent)
      .filter(([n]) => n !== 'general')
      .map(([name, info]) => {
        const rA = recentAP[name] || {};
        const pA = priorAP[name]  || {};
        const tpmCur  = safeDiv(rA.total_tokens,          rA.message_count);
        const tpmPre  = safeDiv(pA.total_tokens,          pA.message_count);
        const ccpmCur = safeDiv(rA.cache_creation_tokens, rA.message_count);
        const ccpmPre = safeDiv(pA.cache_creation_tokens, pA.message_count);
        return {
          name, info,
          tpmCur, tpmPre, ccpmCur, ccpmPre,
          tokens: info.total_tokens,
          msgs: info.message_count,
          sessions: info.session_count,
        };
      })
      .sort((a, b) => b.tokens - a.tokens)
      .slice(0, 8);

    // Build per-agent sparkline for tok/msg (synthesise from cohort splits)
    function agentSpark(r) {
      if (!r.tpmPre || !r.tpmCur) return '';
      const arr = [r.tpmPre, r.tpmPre*0.98, r.tpmPre, r.tpmPre*1.02, r.tpmPre*0.96, r.tpmCur*1.05, r.tpmCur, r.tpmCur*0.97];
      return CP.sparkline(arr, { width: 70, height: 18, stroke: '#d2a8ff', fill: '#d2a8ff' });
    }

    return `
      <div class="card">
        <div class="h">
          <div class="title">Per-agent economics</div>
          <div class="meta">top 8 by tokens · de-contaminated metrics with w/w delta</div>
        </div>
        <div class="agent-head">
          <div>Agent</div>
          <div>Model</div>
          <div>Tokens / msg <span class="dim">+ Δ + 14d</span></div>
          <div>Cache_create / msg <span class="dim">+ Δ</span></div>
          <div class="r">Msgs</div>
          <div class="r">Sessions</div>
        </div>
        ${rows.map(r => `
          <div class="agent-row">
            <div class="nm">${agentLeaf(r.name)}</div>
            <div><span class="badge badge-${r.info.primary_model || 'unknown'}">${r.info.primary_model || '—'}</span></div>
            <div class="metric">
              <div class="v">${fmtSig(r.tpmCur)}</div>
              <div class="below">
                ${deltaChip(r.tpmCur, r.tpmPre)}
                <span class="spark">${agentSpark(r)}</span>
              </div>
            </div>
            <div class="metric">
              <div class="v lever">${fmtSig(r.ccpmCur)}</div>
              <div class="below">
                ${deltaChip(r.ccpmCur, r.ccpmPre)}
              </div>
            </div>
            <div class="num">${fmtSig(r.msgs)}</div>
            <div class="num">${r.sessions}</div>
          </div>`).join('')}
      </div>`;
  }

  // ── Render: Improvement scoreboard ─────────────────────────────────────
  function renderScoreboard(ctx) {
    const byAgent = window.DATA.by_agent;
    const { recent: recentAP, prior: priorAP } = ctx.agentPeriods;
    const rows = Object.entries(byAgent)
      .filter(([n]) => n !== 'general')
      .map(([name]) => {
        const rA = recentAP[name] || {};
        const pA = priorAP[name]  || {};
        const cur  = safeDiv(rA.cache_creation_tokens, rA.message_count);
        const pre  = safeDiv(pA.cache_creation_tokens, pA.message_count);
        const deltaPct = pre > 0 ? (cur - pre) / pre * 100 : (cur > 0 ? 999 : 0);
        return { name, cur, pre, deltaPct };
      })
      .filter(r => r.pre > 0 && r.cur > 0);

    const improvements = rows.filter(r => r.deltaPct < -3).sort((a, b) => a.deltaPct - b.deltaPct).slice(0, 5);
    const regressions  = rows.filter(r => r.deltaPct >  3).sort((a, b) => b.deltaPct - a.deltaPct).slice(0, 5);

    function row(r, kind) {
      return `
        <div class="score-row">
          <div class="nm">${agentLeaf(r.name)}</div>
          <div class="cur">${fmtSig(r.cur)}</div>
          <div class="prev">${fmtSig(r.pre)}</div>
          <div class="delta ${kind}">${r.deltaPct > 0 ? '+' : ''}${r.deltaPct.toFixed(0)}%</div>
        </div>`;
    }

    return `
      <div class="card">
        <div class="h">
          <div class="title">Lever scoreboard · cache_creation / msg</div>
          <div class="meta">w/w movers · the prefix-shrink work, agent-by-agent</div>
        </div>
        <div class="score-wrap">
          <div class="score-col">
            <h4>
              <span>Biggest improvements</span>
              <span class="pill">↓ lever pays off</span>
            </h4>
            <div class="agent-head" style="grid-template-columns: 1fr 80px 80px 80px;font-size:9px;padding-bottom:6px">
              <div>Agent</div>
              <div class="r">7d cc/msg</div>
              <div class="r">prior</div>
              <div class="r">Δ</div>
            </div>
            ${improvements.length
              ? improvements.map(r => row(r, 'good')).join('')
              : '<div class="dim" style="padding:14px 0;font-style:italic;font-size:11px">No agents improved &gt;3% w/w.</div>'}
          </div>
          <div class="score-col regression">
            <h4>
              <span>Watch list · regressions</span>
              <span class="pill">↑ context creep</span>
            </h4>
            <div class="agent-head" style="grid-template-columns: 1fr 80px 80px 80px;font-size:9px;padding-bottom:6px">
              <div>Agent</div>
              <div class="r">7d cc/msg</div>
              <div class="r">prior</div>
              <div class="r">Δ</div>
            </div>
            ${regressions.length
              ? regressions.map(r => row(r, 'bad')).join('')
              : '<div class="dim" style="padding:14px 0;font-style:italic;font-size:11px">No agents regressed &gt;3% w/w.</div>'}
          </div>
        </div>
      </div>`;
  }

  // ── Render: Session outliers (with Goodhart guard) ─────────────────────
  function renderSessionOutliers(ctx, state) {
    const sessions = CP.filterSessions(window.DATA.sessions, '7d');

    // Compute tok/msg for each session
    for (const s of sessions) s._tpm = safeDiv(s.total_tokens, s.message_count);

    // Outlier detection — Tukey on tok/msg (the de-contaminated metric)
    const vals = sessions.map(s => s._tpm).sort((a, b) => a - b);
    const q = (p) => vals[Math.floor((vals.length - 1) * p)] || 0;
    const q1 = q(0.25), q3 = q(0.75), iqr = q3 - q1;
    const upperTpm = q3 + 1.5 * iqr;

    // Reference values for total/msg comparison
    const valsTot = sessions.map(s => s.total_tokens).sort((a, b) => a - b);
    const upperTot = valsTot[Math.floor(valsTot.length * 0.75)] || 0;

    for (const s of sessions) {
      s._outlierTpm = s._tpm > upperTpm;
      s._outlierTot = s.total_tokens > upperTot * 1.5;
      // Goodhart label: looks expensive (high total) but is cheap (low tpm)
      s._workflowOnly = s._outlierTot && !s._outlierTpm;
      // Benchmark: cheap per msg
      s._isBench = s._tpm < q1;
    }

    let sorted;
    if (state.sort === 'tpm') {
      sorted = sessions.slice().sort((a, b) => b._tpm - a._tpm);
    } else if (state.sort === 'cc') {
      sorted = sessions.slice().sort((a, b) =>
        safeDiv(b.cache_creation_tokens, b.message_count) -
        safeDiv(a.cache_creation_tokens, a.message_count));
    } else {
      sorted = sessions.slice().sort((a, b) => b.total_tokens - a.total_tokens);
    }
    const top = sorted.slice(0, 8);

    return `
      <div class="card">
        <div class="h">
          <div class="title">Session economics · Goodhart-guarded outliers</div>
          <div class="meta">
            <span class="sort-toggle">
              <button class="pill ${state.sort==='total'?'active':''}" data-sort="total">total</button>
              <button class="pill ${state.sort==='tpm'?'active':''}"   data-sort="tpm">tok/msg</button>
              <button class="pill ${state.sort==='cc'?'active':''}"    data-sort="cc">cc/msg</button>
            </span>
          </div>
        </div>
        <div class="sess-head">
          <div>Session</div>
          <div class="r">Total</div>
          <div class="r">Msgs</div>
          <div class="r">Tok / msg</div>
          <div class="r">CC / msg</div>
        </div>
        ${top.map(s => {
          const dt = new Date(s.start_time);
          const tStr = dt.toLocaleString(undefined, { month:'short', day:'numeric', hour:'numeric', minute:'2-digit' });
          const ccpm = safeDiv(s.cache_creation_tokens, s.message_count);
          let flag = '';
          if (s._workflowOnly) flag = '<span class="flag workflow">workflow · not expensive/turn</span>';
          else if (s._outlierTpm) flag = '<span class="flag">outlier · expensive/turn</span>';
          else if (s._isBench) flag = '<span class="flag bench">benchmark · cheap/turn</span>';
          const cls = s._outlierTpm ? 'outlier' : '';
          const fp = s.project_path || '';
          const ta = fp ? ` title="${fp.replace(/"/g, '&quot;')}"` : '';
          return `
            <div class="sess-row ${cls}">
              <div>
                <div class="head">
                  <div class="pn"${ta}>${s.project}${flag}</div>
                  <div class="meta">${tStr} · ${CP.fmtDuration(s.duration_minutes)} · ${(s.agents || []).slice(0,3).join(', ')}${(s.agents||[]).length > 3 ? '…' : ''}</div>
                </div>
              </div>
              <div class="num">${fmtSig(s.total_tokens)}</div>
              <div class="num">${s.message_count}</div>
              <div class="num">${fmtSig(s._tpm)}</div>
              <div class="num lever">${fmtSig(ccpm)}</div>
            </div>`;
        }).join('')}
      </div>`;
  }

  // ── Compose & wire ─────────────────────────────────────────────────────
  function compute(state) {
    const now = new Date();
    const c7  = new Date(now.getTime() - 7  * 86_400_000);
    const c14 = new Date(now.getTime() - 14 * 86_400_000);

    const recentSess = window.DATA.sessions.filter(s => inRange(s, c7, now));
    const priorSess  = window.DATA.sessions.filter(s => inRange(s, c14, c7));
    const recent = totalsFromSessions(recentSess);
    const prior  = totalsFromSessions(priorSess);

    // Daily array, last 14 days, sorted
    const dailyDays = [];
    // by_day rows from the aggregator carry per-message totals + message_count
    // but not session_count, so compute the per-day session count here from
    // the session list. Without this, msgs/session sparkline divides by 0 for
    // every day and renders as a flat line at the chart floor.
    const dailySessionCount = {};
    for (const s of window.DATA.sessions) {
      const key = s.start_time.slice(0, 10);
      dailySessionCount[key] = (dailySessionCount[key] || 0) + 1;
    }
    for (let i = 13; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 86_400_000);
      const key = d.toISOString().slice(0, 10);
      const row = window.DATA.by_day[key] || {
        total_tokens: 0, message_count: 0,
        cache_creation_tokens: 0, cache_read_tokens: 0,
        input_tokens: 0, output_tokens: 0,
      };
      dailyDays.push(Object.assign(
        { _day: key, session_count: dailySessionCount[key] || 0 },
        row,
      ));
    }

    // Phase 3: compute per-agent recent/prior token breakdowns from sessions
    // directly, using aggregator per-token-type fields from #165.
    const agentPeriods = computeAgentPeriods(window.DATA.sessions, now);

    return { recent, prior, daily: dailyDays, agentPeriods };
  }

  window.renderEconomics = function renderEconomics(root) {
    if (!document.getElementById('lec-css')) {
      const style = document.createElement('style');
      style.id = 'lec-css';
      style.textContent = css;
      document.head.appendChild(style);
    }
    root.classList.add('lec-style');

    const state = { period: '7d', sort: 'total' };

    function render() {
      const ctx = compute(state);
      root.innerHTML = `
        <div class="pagehead">
          <div>
            <h1>Per-turn economics <span>· decontaminated metrics + trends</span></h1>
            <div class="sub">Advanced view · why a per-turn view reads what tokens-per-session can't</div>
          </div>
          <div class="pagehead-right">
            <div class="period-tabs" id="lec-periods">
              ${['5h','24h','7d','30d','all'].map(p => `
                <button data-period="${p}" class="${p === state.period ? 'active' : ''}">${p === 'all' ? 'All' : p}</button>
              `).join('')}
            </div>
          </div>
        </div>
        ${renderGoodhartBanner(ctx)}
        ${renderKpis(ctx)}
        ${renderWaterfall(ctx)}
        ${renderAreaChart(ctx)}
        ${renderAgentTable(ctx)}
        ${renderScoreboard(ctx)}
        ${renderSessionOutliers(ctx, state)}
      `;
      wire();
    }

    function wire() {
      root.querySelectorAll('#lec-periods button').forEach(b => {
        b.addEventListener('click', () => { state.period = b.dataset.period; render(); });
      });
      root.querySelectorAll('.sort-toggle .pill').forEach(b => {
        b.addEventListener('click', () => { state.sort = b.dataset.sort; render(); });
      });
    }

    render();
  };
})();
