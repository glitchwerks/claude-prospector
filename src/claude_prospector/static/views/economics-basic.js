// Economy — Overview (Basic) view.
// Plain-English layer over the aggregator data. No per-msg / cache jargon.
// Renders into the element passed to renderEconomicsBasic(root).
//
// Phase 3: reads window.DATA (aggregator payload) — mock references removed.
// Function name, variable names, and visual output match the reference
// artifact (Dashboard - Economy v1 standalone). No design drift.

(function () {
  // ── Helpers ─────────────────────────────────────────────────────────────
  function safeDiv(a, b) { return b > 0 ? a / b : 0; }
  function fmtBigTokens(n) {
    if (n == null) return '—';
    if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(2) + 'B';
    if (n >= 1_000_000)     return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000)         return (n / 1_000).toFixed(1) + 'K';
    return Math.round(n).toLocaleString();
  }
  function fmtPct(p) {
    const sign = p > 0 ? '+' : '';
    return sign + p.toFixed(Math.abs(p) < 10 ? 1 : 0) + '%';
  }
  function fmtRelDay(iso) {
    const t = new Date(iso);
    const now = new Date();
    const diffMs = now - t;
    const diffH = diffMs / 3_600_000;
    if (diffH < 1)  return Math.round(diffH * 60) + 'm ago';
    if (diffH < 24) return Math.round(diffH) + 'h ago';
    const diffD = Math.floor(diffH / 24);
    if (diffD < 7) return diffD + 'd ago';
    return t.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  function shortAgent(name) {
    const parts = name.split('→');
    return parts[parts.length - 1];
  }

  // ── CSS ─────────────────────────────────────────────────────────────────
  const css = `
    .leb-style { color: #c9d1d9; }

    /* Top hero row */
    .leb-style .top-row {
      display: grid;
      grid-template-columns: 2fr 1fr 1fr;
      gap: 14px;
      margin-bottom: 18px;
    }
    @media (max-width: 1000px) { .leb-style .top-row { grid-template-columns: 1fr; } }

    .leb-style .hero {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 12px;
      padding: 22px 24px;
      position: relative;
      overflow: hidden;
    }
    .leb-style .hero .eyebrow {
      font-size: 11px; color: #8b949e; text-transform: uppercase;
      letter-spacing: 0.08em; font-weight: 500;
    }
    .leb-style .hero .bignum {
      font-size: 48px; color: #f0f6fc; font-weight: 600;
      letter-spacing: -0.03em; line-height: 1;
      margin: 12px 0 8px;
      font-variant-numeric: tabular-nums;
    }
    .leb-style .hero .bignum .unit { font-size: 16px; color: #8b949e; font-weight: 400; margin-left: 6px; }
    .leb-style .hero .deltaline {
      font-size: 14px; color: #c9d1d9; display: flex; align-items: center; gap: 8px;
    }
    .leb-style .hero .deltaline .arrow {
      font-weight: 600; font-size: 16px;
    }
    .leb-style .hero .deltaline .arrow.up    { color: #ffa657; }
    .leb-style .hero .deltaline .arrow.down  { color: #3fb950; }
    .leb-style .hero .deltaline .arrow.flat  { color: #8b949e; }
    .leb-style .hero .deltaline .pct { font-weight: 600; }
    .leb-style .hero .deltaline .pct.up   { color: #ffa657; }
    .leb-style .hero .deltaline .pct.down { color: #3fb950; }
    .leb-style .hero .deltaline .pct.flat { color: #8b949e; }
    .leb-style .hero .deltaline .vs { color: #8b949e; }
    .leb-style .hero .spark { margin-top: 14px; line-height: 0; }
    .leb-style .hero .spark svg { width: 100%; height: 48px; display: block; }

    .leb-style .stat {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 12px;
      padding: 18px 20px;
      display: flex; flex-direction: column; justify-content: space-between;
    }
    .leb-style .stat .label {
      font-size: 11px; color: #8b949e; text-transform: uppercase;
      letter-spacing: 0.08em; font-weight: 500;
    }
    .leb-style .stat .num {
      font-size: 32px; color: #f0f6fc; font-weight: 600;
      letter-spacing: -0.02em; line-height: 1;
      margin: 10px 0 6px;
      font-variant-numeric: tabular-nums;
    }
    .leb-style .stat .sub { font-size: 12px; color: #8b949e; }

    /* Generic card */
    .leb-style .card {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 12px;
      padding: 20px 22px;
      margin-bottom: 18px;
    }
    .leb-style .card .h {
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: 16px;
    }
    .leb-style .card .h .title {
      font-size: 15px; color: #f0f6fc; font-weight: 600; letter-spacing: -0.01em;
    }
    .leb-style .card .h .meta { font-size: 12px; color: #8b949e; }

    /* Daily activity bars */
    .leb-style .bars {
      display: grid;
      grid-template-columns: repeat(14, 1fr);
      gap: 6px;
      align-items: end;
      height: 180px;
      padding-bottom: 22px;
      position: relative;
    }
    .leb-style .bars .bar {
      background: linear-gradient(180deg, #d2a8ff 0%, #8957e5 100%);
      border-radius: 4px 4px 0 0;
      position: relative;
      min-height: 2px;
      transition: opacity 0.15s ease;
    }
    .leb-style .bars .bar.today { background: linear-gradient(180deg, #ffd9a8 0%, #f59e0b 100%); }
    .leb-style .bars .bar:hover { opacity: 0.85; }
    .leb-style .bars .bar .lbl {
      position: absolute; bottom: -20px; left: 0; right: 0;
      text-align: center; font-size: 10px; color: #6e7681;
      font-variant-numeric: tabular-nums;
    }
    .leb-style .bars .bar .val {
      position: absolute; top: -18px; left: 0; right: 0;
      text-align: center; font-size: 10px; color: #c9d1d9;
      opacity: 0; transition: opacity 0.15s ease;
      pointer-events: none; white-space: nowrap;
    }
    .leb-style .bars .bar:hover .val { opacity: 1; }

    /* Top agents horizontal bars */
    .leb-style .agents-list { display: flex; flex-direction: column; gap: 10px; }
    .leb-style .agent-row {
      display: grid;
      grid-template-columns: 200px 1fr 90px 60px;
      gap: 14px;
      align-items: center;
      font-size: 13px;
    }
    .leb-style .agent-row .nm {
      color: #f0f6fc; font-weight: 500;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .leb-style .agent-row .track {
      background: #0d1117;
      border-radius: 4px;
      height: 8px;
      position: relative;
      overflow: hidden;
    }
    .leb-style .agent-row .fill {
      position: absolute; left: 0; top: 0; bottom: 0;
      background: linear-gradient(90deg, #8957e5 0%, #d2a8ff 100%);
      border-radius: 4px;
    }
    .leb-style .agent-row .tok {
      color: #c9d1d9; font-variant-numeric: tabular-nums;
      text-align: right;
    }
    .leb-style .agent-row .pct {
      color: #8b949e; font-variant-numeric: tabular-nums; font-size: 12px;
      text-align: right;
    }
    @media (max-width: 700px) {
      .leb-style .agent-row {
        grid-template-columns: 1fr 70px 50px;
      }
      .leb-style .agent-row .track { display: none; }
    }

    /* Sessions list */
    .leb-style .sess-list {
      display: flex; flex-direction: column;
      gap: 0;
    }
    .leb-style .sess-row {
      display: grid;
      grid-template-columns: 80px 1fr 90px 100px;
      gap: 14px;
      align-items: center;
      padding: 10px 4px;
      border-bottom: 1px solid #21262d;
      font-size: 13px;
    }
    .leb-style .sess-row:last-child { border-bottom: 0; }
    .leb-style .sess-row .when {
      color: #8b949e; font-size: 12px;
    }
    .leb-style .sess-row .who {
      color: #f0f6fc; font-weight: 500;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .leb-style .sess-row .who .chain {
      color: #6e7681; font-weight: 400; font-size: 11px;
    }
    .leb-style .sess-row .dur {
      color: #8b949e; text-align: right; font-variant-numeric: tabular-nums;
    }
    .leb-style .sess-row .tok {
      color: #c9d1d9; text-align: right; font-variant-numeric: tabular-nums;
      font-weight: 500;
    }

    /* Advanced nudge */
    .leb-style .nudge {
      background: linear-gradient(135deg, rgba(210,168,255,0.08) 0%, rgba(137,87,229,0.04) 100%);
      border: 1px solid rgba(210,168,255,0.25);
      border-radius: 12px;
      padding: 18px 22px;
      display: grid;
      grid-template-columns: 32px 1fr auto;
      gap: 14px;
      align-items: center;
      margin-top: 8px;
    }
    .leb-style .nudge .ico {
      width: 30px; height: 30px; border-radius: 8px;
      background: rgba(210,168,255,0.18); color: #d2a8ff;
      display: inline-flex; align-items: center; justify-content: center;
      font-weight: 600; font-size: 16px;
    }
    .leb-style .nudge .body { font-size: 13px; color: #c9d1d9; line-height: 1.5; }
    .leb-style .nudge .body b { color: #f0f6fc; font-weight: 600; }
    .leb-style .nudge .nudge-secondary {
      font-size: 11px; color: #8b949e; margin-top: 6px;
    }
    .leb-style .nudge .nudge-secondary a {
      color: #d2a8ff; text-decoration: none; border-bottom: 1px dotted rgba(210,168,255,0.4);
    }
    .leb-style .nudge .nudge-secondary a:hover {
      border-bottom-color: #d2a8ff;
    }
    .leb-style .nudge .cta {
      background: rgba(210,168,255,0.15);
      color: #d2a8ff;
      border: 1px solid rgba(210,168,255,0.3);
      border-radius: 8px;
      padding: 8px 14px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.15s ease;
    }
    .leb-style .nudge .cta:hover { background: rgba(210,168,255,0.25); }
  `;

  // ── Compute ─────────────────────────────────────────────────────────────
  function computeBasic() {
    // Phase 3: read window.DATA (aggregator payload) — mock references removed.
    const NOW = new Date();
    const sessions = window.DATA.sessions;

    const c7  = new Date(NOW.getTime() - 7  * 86_400_000);
    const c14 = new Date(NOW.getTime() - 14 * 86_400_000);

    const recent = [], prior = [];
    for (const s of sessions) {
      const t = new Date(s.start_time);
      if (t >= c7) recent.push(s);
      else if (t >= c14) prior.push(s);
    }

    const sumT = arr => arr.reduce((a, s) => a + s.total_tokens, 0);
    const recentTotal = sumT(recent);
    const priorTotal  = sumT(prior);
    const pctChange = priorTotal > 0 ? (recentTotal - priorTotal) / priorTotal * 100 : 0;

    // Active days: of the last 7 calendar days (anchored on NOW),
    // how many had any session activity.
    // Both anchor keys and session keys use localDateKey() so they are
    // compared in the same timezone (#197).
    const recentDateKeys = new Set();
    for (let i = 0; i < 7; i++) {
      const d = new Date(NOW.getTime() - i * 86_400_000);
      recentDateKeys.add(CP.localDateKey(d));
    }
    const sessionDateKeys = new Set(sessions.map(s => CP.localDateKey(new Date(s.start_time))));
    const recentDays = [...recentDateKeys].filter(k => sessionDateKeys.has(k)).length;

    // Daily totals for the last 14 days
    const daily = [];
    for (let i = 13; i >= 0; i--) {
      const d = new Date(NOW.getTime() - i * 86_400_000);
      const key = CP.localDateKey(d);
      const dayTokens = sessions
        .filter(s => CP.localDateKey(new Date(s.start_time)) === key)
        .reduce((a, s) => a + s.total_tokens, 0);
      daily.push({ day: key, date: d, total: dayTokens, isToday: i === 0 });
    }

    // Top agents in recent 7d — fix #174: use agent_tokens (accurate per-agent
    // totals from the aggregator) instead of equal-apportionment heuristic.
    // Equal-apportionment (total_tokens / agents.length) over-attributed parent
    // tokens to sub-agents: when ops was the only leaf, it absorbed all Opus
    // context tokens, inflating its 7-day total from ~tens of M to 1.23 B.
    const agentTotals = {};
    for (const s of recent) {
      if (s.agent_tokens && Object.keys(s.agent_tokens).length > 0) {
        // Prefer accurate per-agent breakdown supplied by the aggregator.
        for (const [a, t] of Object.entries(s.agent_tokens)) {
          if (a === 'general') continue;
          agentTotals[a] = (agentTotals[a] || 0) + t;
        }
      } else {
        // Fallback for session records that pre-date agent_tokens (e.g. stale
        // JSON cache): fall back to equal-apportionment over leaf agents.
        const agents = s.agents && s.agents.length ? s.agents : ['(unspecified)'];
        const share = s.total_tokens / agents.length;
        for (const a of agents) {
          if (a === 'general') continue;
          agentTotals[a] = (agentTotals[a] || 0) + share;
        }
      }
    }
    const topAgents = Object.entries(agentTotals)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);

    // Recent sessions, most recent first
    const recentSorted = recent.slice().sort((a, b) =>
      new Date(b.start_time) - new Date(a.start_time)
    ).slice(0, 8);

    return {
      recentTotal, priorTotal, pctChange,
      sessionCount: recent.length,
      recentDays,
      daily,
      topAgents,
      recentSessions: recentSorted,
    };
  }

  // ── Renderers ───────────────────────────────────────────────────────────
  function renderHeroSpark(daily) {
    const W = 600, H = 48;
    const max = Math.max(...daily.map(d => d.total)) || 1;
    const xAt = i => (i / Math.max(1, daily.length - 1)) * W;
    const yAt = v => H - (v / max) * (H - 4) - 2;
    const pts = daily.map((d, i) => `${xAt(i).toFixed(1)},${yAt(d.total).toFixed(1)}`).join(' ');
    const areaPts = `0,${H} ${pts} ${W},${H}`;
    return `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <polygon points="${areaPts}" fill="#d2a8ff" fill-opacity="0.15"/>
        <polyline points="${pts}" fill="none" stroke="#d2a8ff" stroke-width="1.5"/>
      </svg>`;
  }

  function renderTopRow(ctx) {
    const dir = ctx.pctChange > 3 ? 'up' : ctx.pctChange < -3 ? 'down' : 'flat';
    const arrow = dir === 'up' ? '↑' : dir === 'down' ? '↓' : '→';

    return `
      <div class="top-row">
        <div class="hero">
          <div class="eyebrow">This week</div>
          <div class="bignum">${fmtBigTokens(ctx.recentTotal)}<span class="unit">tokens used</span></div>
          <div class="deltaline">
            <span class="arrow ${dir}">${arrow}</span>
            <span class="pct ${dir}">${fmtPct(ctx.pctChange)}</span>
            <span class="vs">vs. previous 7 days (${fmtBigTokens(ctx.priorTotal)})</span>
          </div>
          <div class="spark">${renderHeroSpark(ctx.daily)}</div>
        </div>

        <div class="stat">
          <div class="label">Sessions</div>
          <div class="num">${ctx.sessionCount}</div>
          <div class="sub">started in the last 7 days</div>
        </div>

        <div class="stat">
          <div class="label">Active days</div>
          <div class="num">${ctx.recentDays}<span style="font-size:18px;color:#6e7681;font-weight:400;">/7</span></div>
          <div class="sub">days with any activity</div>
        </div>
      </div>`;
  }

  function renderDailyChart(ctx) {
    const max = Math.max(...ctx.daily.map(d => d.total)) || 1;
    const bars = ctx.daily.map((d, i) => {
      const h = (d.total / max) * 100;
      const dow = d.date.toLocaleDateString(undefined, { weekday: 'narrow' });
      const showLabel = i % 2 === 0 || d.isToday;
      return `
        <div class="bar ${d.isToday ? 'today' : ''}" style="height: ${h}%">
          <div class="val">${fmtBigTokens(d.total)}</div>
          ${showLabel ? `<div class="lbl">${dow}</div>` : ''}
        </div>`;
    }).join('');

    return `
      <div class="card">
        <div class="h">
          <div class="title">Daily activity</div>
          <div class="meta">last 14 days · hover a bar for details</div>
        </div>
        <div class="bars">${bars}</div>
      </div>`;
  }

  function renderTopAgents(ctx) {
    const max = ctx.topAgents.length ? ctx.topAgents[0][1] : 1;
    const grandTotal = ctx.topAgents.reduce((a, [, v]) => a + v, 0) || 1;
    const rows = ctx.topAgents.map(([name, v]) => {
      const widthPct = (v / max) * 100;
      const shareOfTop = (v / grandTotal) * 100;
      const parts = name.split('→');
      const leaf = parts[parts.length - 1];
      return `
        <div class="agent-row">
          <div class="nm" title="${name}">${leaf}</div>
          <div class="track"><div class="fill" style="width:${widthPct.toFixed(1)}%"></div></div>
          <div class="tok">${fmtBigTokens(v)}</div>
          <div class="pct">${shareOfTop.toFixed(0)}%</div>
        </div>`;
    }).join('');

    return `
      <div class="card">
        <div class="h">
          <div class="title">Where your tokens went</div>
          <div class="meta">top agents · last 7 days · % of these top 6</div>
        </div>
        <div class="agents-list">${rows}</div>
      </div>`;
  }

  function renderRecentSessions(ctx) {
    const rows = ctx.recentSessions.map(s => {
      const when = fmtRelDay(s.start_time);
      const agents = (s.agents || []).filter(a => a !== 'general');
      const leaf = agents.length ? shortAgent(agents[0]) : '(general)';
      const extra = agents.length > 1 ? ` <span class="chain">+${agents.length - 1} more</span>` : '';
      const mins = Math.round(s.duration_minutes);
      const dur = mins >= 60 ? `${(mins / 60).toFixed(1)}h` : `${mins}m`;
      return `
        <div class="sess-row">
          <div class="when">${when}</div>
          <div class="who">${leaf}${extra}</div>
          <div class="dur">${dur}</div>
          <div class="tok">${fmtBigTokens(s.total_tokens)}</div>
        </div>`;
    }).join('');

    return `
      <div class="card">
        <div class="h">
          <div class="title">Recent sessions</div>
          <div class="meta">8 most recent · this week</div>
        </div>
        <div class="sess-list">${rows}</div>
      </div>`;
  }

  function renderNudge() {
    return `
      <div class="nudge">
        <div class="ico">→</div>
        <div class="body">
          Want to see <b>which skills you're adopting</b>, <b>where tokens go by project</b>, or browse the full session log?
          The Breakdown view drills into the details behind these numbers.
          <div class="nudge-secondary">Already comfortable with token · cache · prefix economics? <a href="#" data-go-advanced>Jump to Advanced →</a></div>
        </div>
        <button class="cta" data-go-detail>Switch to Breakdown</button>
      </div>`;
  }

  // ── Public entry ────────────────────────────────────────────────────────
  window.renderEconomicsBasic = function renderEconomicsBasic(root) {
    if (!document.getElementById('leb-css')) {
      const style = document.createElement('style');
      style.id = 'leb-css';
      style.textContent = css;
      document.head.appendChild(style);
    }
    root.classList.add('leb-style');

    const ctx = computeBasic();
    root.innerHTML = `
      ${renderTopRow(ctx)}
      ${renderDailyChart(ctx)}
      ${renderTopAgents(ctx)}
      ${renderRecentSessions(ctx)}
      ${renderNudge()}
    `;

    // Bubble the "switch to ..." clicks up to the shell
    root.querySelectorAll('[data-go-detail]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent('economy:switch-view', { detail: { view: 'detail' } }));
      });
    });
    root.querySelectorAll('[data-go-advanced]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent('economy:switch-view', { detail: { view: 'advanced' } }));
      });
    });
  };
})();
