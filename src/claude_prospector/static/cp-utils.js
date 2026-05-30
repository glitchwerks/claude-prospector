// Shared utilities, palette, chart defaults.

(function () {
  // ── Palette (GitHub-dark inspired) ───────────────────────────────────────
  const PALETTE = {
    bg:        '#0d1117',
    bgAlt:     '#0a0d12',
    card:      '#161b22',
    cardHi:    '#1c2230',
    border:    '#21262d',
    borderHi:  '#30363d',
    text:      '#c9d1d9',
    textHi:    '#f0f6fc',
    textMute:  '#8b949e',
    textDim:   '#6e7681',

    opus:      '#8b5cf6',
    sonnet:    '#2ea043',
    haiku:     '#58a6ff',
    unknown:   '#8b949e',

    accent:    '#d2a8ff',
    warn:      '#d29922',
    danger:    '#f85149',
    ok:        '#3fb950',
    info:      '#79c0ff',

    grid:      '#21262d',
  };

  // ── Formatters ───────────────────────────────────────────────────────────
  function fmtTokens(n) {
    if (n == null) return '—';
    const sign = n < 0 ? '-' : '';
    const a = Math.abs(n);
    if (a >= 1_000_000) return sign + (a / 1_000_000).toFixed(1) + 'M';
    if (a >= 1000)      return sign + (a / 1000).toFixed(a >= 10000 ? 0 : 1) + 'K';
    return sign + String(Math.round(a));
  }
  function fmtTokensFull(n) {
    if (n == null) return '—';
    return n.toLocaleString();
  }
  function fmtPct(n) { return Math.round(n) + '%'; }
  function fmtDuration(minutes) {
    if (minutes == null) return '—';
    const m = Math.round(minutes);
    if (m < 60) return m + 'm';
    const h = Math.floor(m / 60);
    const rem = m % 60;
    return rem > 0 ? h + 'h ' + rem + 'm' : h + 'h';
  }
  function fmtRelTime(iso, now = window.MOCK_NOW || new Date()) {
    const t = new Date(iso);
    const diffMin = Math.round((now - t) / 60000);
    if (diffMin < 1)   return 'just now';
    if (diffMin < 60)  return diffMin + 'm ago';
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24)   return diffHr + 'h ago';
    const diffD = Math.round(diffHr / 24);
    return diffD + 'd ago';
  }
  function fmtDay(iso) {
    return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }
  // Return a YYYY-MM-DD string in the viewer's local timezone.
  // Uses toLocaleDateString('en-CA') which yields ISO-format local date
  // (e.g. "2026-05-30") without UTC conversion.  This replaces
  // d.toISOString().slice(0,10) (UTC) for all client-computed day-bucket
  // keys so that "today" resolves in the viewer's local timezone.
  function localDateKey(date) {
    return date.toLocaleDateString('en-CA');
  }

  // ── Model helpers ────────────────────────────────────────────────────────
  function modelColor(model) {
    if (!model) return PALETTE.unknown;
    const m = model.toLowerCase();
    if (m.includes('opus'))   return PALETTE.opus;
    if (m.includes('sonnet')) return PALETTE.sonnet;
    if (m.includes('haiku'))  return PALETTE.haiku;
    return PALETTE.unknown;
  }

  // ── Time filtering ───────────────────────────────────────────────────────
  function windowCutoff(period, now = window.MOCK_NOW || new Date()) {
    if (period === '5h')  return new Date(now.getTime() - 5  * 60 * 60 * 1000);
    if (period === '24h') return new Date(now.getTime() - 24 * 60 * 60 * 1000);
    if (period === '7d')  return new Date(now.getTime() - 7  * 24 * 60 * 60 * 1000);
    if (period === '30d') return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    return null;
  }
  function filterSessions(sessions, period) {
    const c = windowCutoff(period);
    if (!c) return sessions.slice();
    return sessions.filter(s => new Date(s.start_time) >= c);
  }

  // ── Re-aggregate filtered sessions ───────────────────────────────────────
  function reAggregate(sessions, authoritative = {}) {
    const byModel = {};
    const byAgent = {};
    const byProject = {};
    const byDay = {};
    let totalTokens = 0;

    for (const s of sessions) {
      totalTokens += s.total_tokens;

      if (!byProject[s.project]) byProject[s.project] = { total_tokens: 0, session_count: 0, full_path: s.project_path || '' };
      byProject[s.project].total_tokens += s.total_tokens;
      byProject[s.project].session_count += 1;

      for (const [m, t] of Object.entries(s.model_split || {})) {
        if (!byModel[m]) byModel[m] = { total_tokens: 0 };
        byModel[m].total_tokens += t;
      }

      const d = localDateKey(new Date(s.start_time));
      if (!byDay[d]) byDay[d] = { total_tokens: 0, by_model: {} };
      byDay[d].total_tokens += s.total_tokens;
      for (const [m, t] of Object.entries(s.model_split || {})) {
        byDay[d].by_model[m] = (byDay[d].by_model[m] || 0) + t;
      }

      // Fix #174: use agent_tokens (accurate per-agent totals) when available.
      // The old equal-apportionment (total / agents.length) over-attributed parent
      // tokens to sub-agents; agent_tokens was added to the aggregator output to
      // provide accurate per-agent breakdowns per session.
      const agentKeys = Object.keys(s.agent_tokens || {}).length > 0
        ? Object.keys(s.agent_tokens)
        : (s.agents || []);
      for (const agent of agentKeys) {
        if (!byAgent[agent]) byAgent[agent] = { total_tokens: 0, session_count: 0, primary_model: null, _modelTokens: {} };
        byAgent[agent].session_count += 1;
        const agentShare = s.agent_tokens && s.agent_tokens[agent] != null
          ? s.agent_tokens[agent]
          : Math.round(s.total_tokens / Math.max(1, agentKeys.length));
        byAgent[agent].total_tokens += agentShare;
        // Model split: apportion by this agent's token fraction of session total.
        const sessionTotal = s.total_tokens || 1;
        const agentFraction = agentShare / sessionTotal;
        for (const [m, t] of Object.entries(s.model_split || {})) {
          byAgent[agent]._modelTokens[m] = (byAgent[agent]._modelTokens[m] || 0) + Math.round(t * agentFraction);
        }
      }
    }

    for (const [agent, info] of Object.entries(byAgent)) {
      if (authoritative[agent] && authoritative[agent].primary_model) {
        info.primary_model = authoritative[agent].primary_model;
      } else {
        let best = null, bestC = 0;
        for (const [m, c] of Object.entries(info._modelTokens || {})) {
          if (c > bestC) { best = m; bestC = c; }
        }
        info.primary_model = best;
      }
    }

    return { byModel, byAgent, byProject, byDay, totalTokens };
  }

  // ── Budget computations ──────────────────────────────────────────────────
  function computeBuckets(sessions, limits, now = window.MOCK_NOW || new Date()) {
    const c5h = new Date(now.getTime() - 5  * 60 * 60 * 1000);
    const c7d = new Date(now.getTime() - 7  * 24 * 60 * 60 * 1000);
    let t5h = 0, t7d = 0, sonnet7d = 0;
    for (const s of sessions) {
      const t = new Date(s.start_time);
      if (t >= c5h) t5h += s.total_tokens;
      if (t >= c7d) {
        t7d += s.total_tokens;
        sonnet7d += (s.model_split && s.model_split.sonnet) || 0;
      }
    }
    return {
      h5:     { value: t5h,      limit: limits.limit_5h        || null, label: '5-hour rolling',     color: PALETTE.info   },
      d7:     { value: t7d,      limit: limits.limit_7d        || null, label: '7-day rolling',      color: PALETTE.accent },
      son7d:  { value: sonnet7d, limit: limits.limit_sonnet_7d || null, label: 'Sonnet · 7d',        color: PALETTE.sonnet },
    };
  }

  // ── Pace / forecasting ───────────────────────────────────────────────────
  // Given current consumption and a window length, estimate hit-time for a limit.
  function forecastHit(currentValue, limit, windowHours, now = window.MOCK_NOW || new Date()) {
    if (!limit) return null;
    const pace = currentValue / windowHours; // tokens per hour
    if (pace <= 0) return null;
    const remaining = limit - currentValue;
    if (remaining <= 0) return { hitNow: true };
    const hoursToHit = remaining / pace;
    return {
      pace,
      hoursToHit,
      hitAt: new Date(now.getTime() + hoursToHit * 60 * 60 * 1000),
      onPace: hoursToHit < windowHours,
    };
  }

  // ── Sparkline (SVG) ──────────────────────────────────────────────────────
  function sparkline(values, { width = 120, height = 28, stroke = PALETTE.info, fill = null, strokeWidth = 1.5 } = {}) {
    if (!values || !values.length) return '';
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const range = Math.max(1, max - min);
    const stepX = values.length > 1 ? width / (values.length - 1) : 0;
    const pts = values.map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return [x, y];
    });
    const path = pts.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const area = fill
      ? `<path d="${path} L ${width},${height} L 0,${height} Z" fill="${fill}" opacity="0.18" />`
      : '';
    const dotX = pts[pts.length - 1][0];
    const dotY = pts[pts.length - 1][1];
    return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      ${area}
      <path d="${path}" fill="none" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="${dotX.toFixed(1)}" cy="${dotY.toFixed(1)}" r="2.2" fill="${stroke}" />
    </svg>`;
  }

  // ── Chart.js defaults ────────────────────────────────────────────────────
  function applyChartDefaults() {
    if (!window.Chart) return;
    Chart.defaults.color = PALETTE.textMute;
    Chart.defaults.borderColor = PALETTE.grid;
    Chart.defaults.font.family = "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
    Chart.defaults.font.size = 11;
  }

  // ── Chart instance tracking ──────────────────────────────────────────────
  const _charts = {};
  function destroyChart(id) {
    if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
  }
  function destroyChartsByPrefix(prefix) {
    for (const id of Object.keys(_charts)) {
      if (id.startsWith(prefix)) destroyChart(id);
    }
  }
  function registerChart(id, chart) { _charts[id] = chart; }

  // ── Per-day series for a model over the last N days ──────────────────────
  function modelSeries(byDay, model, days = 7, now = window.MOCK_NOW || new Date()) {
    const out = [];
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(now.getTime() - i * 86400000);
      const key = localDateKey(d);
      const row = byDay[key];
      if (!row) { out.push(0); continue; }
      if (!model) out.push(row.total_tokens);
      else out.push((row.by_model && row.by_model[model]) || 0);
    }
    return out;
  }

  // ── Export ───────────────────────────────────────────────────────────────
  window.CP = {
    PALETTE,
    fmtTokens, fmtTokensFull, fmtPct, fmtDuration, fmtRelTime, fmtDay,
    localDateKey,
    modelColor,
    windowCutoff, filterSessions, reAggregate, computeBuckets, forecastHit,
    sparkline,
    applyChartDefaults, destroyChart, destroyChartsByPrefix, registerChart,
    modelSeries,
  };
})();
