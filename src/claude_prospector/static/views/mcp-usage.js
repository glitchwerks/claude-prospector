// MCP Tool Usage view — top-level tab (D-D=(a), issue #248 Phase 2).
// Shows whole-corpus MCP server/tool call volume from
// window.DATA.by_mcp_usage. Sits outside the live period selector's scope
// (D-H=(b)): this panel does not respond to the basic/detail/advanced
// period buttons, it always shows all data currently in by_mcp_usage.
// Renders into the element passed to renderMcpUsage(root).
//
// Data access: reads window.DATA.by_mcp_usage directly (no `ctx`) — a
// top-level view has none, matching economics.js / layout-b-diag.js's
// convention of reading raw server-side dicts at the point of use.

(function () {
  const PALETTE = CP.PALETTE;

  // ── Helpers ─────────────────────────────────────────────────────────────

  // Server/method names are transcript-derived strings (not otherwise
  // sanitized — see renderer.py's data_json escaping comment) rendered via
  // innerHTML below. Escape before interpolating so a crafted name can't
  // break out of its containing tag.
  const _ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => _ESC_MAP[c]);
  }

  // F6: sessions_seen_in / avg_calls_per_active_session can be `null`
  // ("not observable" — the server was never seen in a transcript) or `0`
  // ("observed as zero"). Collapsing null into 0 would hide that
  // distinction, so this formatter renders them differently on purpose.
  function formatCountOrUnknown(n) {
    if (n === null || n === undefined) return 'unknown';
    return CP.fmtTokens(n);
  }

  function formatAvgOrUnknown(n) {
    if (n === null || n === undefined) return 'unknown';
    return n.toFixed(1);
  }

  function fmtWindowBound(iso) {
    if (!iso) return null;
    // window.start/end (cli/dashboard.py) are date-only 'YYYY-MM-DD'
    // strings. Parsing those bare would anchor to UTC midnight, which
    // `toLocaleDateString` below then renders in the viewer's local
    // timezone -- shifting the displayed date back a day west of UTC.
    // Anchor to local midnight instead, matching cp-utils.js's fmtDay.
    const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso);
    const d = new Date(isDateOnly ? iso + 'T00:00:00' : iso);
    // window.start/end come from resolved_from/resolved_to.date().isoformat()
    // (argparse-derived, cannot carry markup) -- esc() here anyway so this
    // stays the one unconditionally-safe sink in the file, matching the
    // treatment given to transcript-derived server/method names.
    if (isNaN(d.getTime())) return esc(String(iso));
    return d.toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    });
  }

  // F10: state the time basis explicitly. D-H=(b) means this panel is not
  // wired to the shell's period selector, so the copy must say so rather
  // than implying the panel is period-aware.
  function timeBasisLine(win) {
    const start = fmtWindowBound(win.start);
    const end = fmtWindowBound(win.end);
    const scope = (win.start == null && win.end == null)
      ? 'all time'
      : `${start || 'unknown start'} – ${end || 'unknown end'}`;
    return `Whole-corpus totals · ${scope} · not filtered by the period `
      + 'selector above.';
  }

  // ── CSS ─────────────────────────────────────────────────────────────────
  const css = `
    .lmu-style { color: #c9d1d9; }
    .lmu-style .pagehead {
      display: flex; align-items: flex-end; justify-content: space-between;
      gap: 16px; margin-bottom: 12px; flex-wrap: wrap;
    }
    .lmu-style .pagehead h1 {
      font-size: 22px; color: #f0f6fc; letter-spacing: -0.02em; font-weight: 600;
    }
    .lmu-style .pagehead h1 span { color: #6e7681; font-weight: 400; }
    .lmu-style .pagehead .sub { color: #8b949e; font-size: 12px; margin-top: 4px; }

    .lmu-style .banner {
      background: #161b22;
      border: 1px solid #21262d;
      border-left: 3px solid #f85149;
      border-radius: 10px;
      padding: 12px 16px;
      margin-bottom: 16px;
      font-size: 12px;
      color: #f0f6fc;
    }
    .lmu-style .banner b { color: #f85149; }

    .lmu-style .blind-spot {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      padding: 12px 16px;
      margin-bottom: 18px;
      font-size: 12px;
      color: #8b949e;
    }

    .lmu-style .empty {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      padding: 32px 24px;
      text-align: center;
      color: #8b949e;
      font-size: 13px;
    }
    .lmu-style .empty code {
      background: #0d1117;
      border: 1px solid #21262d;
      border-radius: 4px;
      padding: 1px 6px;
      color: #d2a8ff;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }

    .lmu-style .servers {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 14px;
    }
    .lmu-style .server-card {
      background: #161b22;
      border: 1px solid #21262d;
      border-radius: 10px;
      padding: 16px 18px;
    }
    .lmu-style .server-card.dormant { border-style: dashed; }
    .lmu-style .server-card .h {
      display: flex; justify-content: space-between; align-items: baseline;
      margin-bottom: 10px;
    }
    .lmu-style .server-card .h .name {
      font-size: 14px; color: #f0f6fc; font-weight: 600;
    }
    .lmu-style .server-card .h .badge-dormant {
      font-size: 10px; color: #8b949e; background: #21262d;
      padding: 1px 7px; border-radius: 10px;
    }
    .lmu-style .server-card .stats {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 8px 12px;
      margin-bottom: 10px;
    }
    .lmu-style .server-card .stat .label {
      font-size: 10px; color: #6e7681; text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .lmu-style .server-card .stat .v {
      font-size: 16px; color: #f0f6fc; font-weight: 600;
      font-variant-numeric: tabular-nums;
    }
    .lmu-style .server-card .stat .v.unknown { color: #6e7681; font-weight: 500; }
    .lmu-style .server-card .methods {
      border-top: 1px solid #21262d;
      padding-top: 8px;
    }
    .lmu-style .server-card .methods .row {
      display: flex; justify-content: space-between;
      font-size: 12px; color: #c9d1d9; padding: 3px 0;
    }
    .lmu-style .server-card .methods .row .n { color: #8b949e; font-variant-numeric: tabular-nums; }
    .lmu-style .server-card .methods .none {
      font-size: 11px; color: #6e7681; font-style: italic;
    }
  `;

  // ── Render pieces ───────────────────────────────────────────────────────

  function renderEmptyState() {
    return `
      <div class="pagehead">
        <div>
          <h1>MCP Tool Usage</h1>
          <div class="sub">Per-server / per-tool call volume from MCP servers.</div>
        </div>
      </div>
      <div class="empty">
        No MCP call data collected yet. Re-run the dashboard with
        <code>--track-mcp-calls</code> to enable collection.
      </div>`;
  }

  // F9: banner rendered only when unreadable_transcripts > 0 — a caveat
  // alongside the counts below, not a replacement for them.
  function renderUnreadableBanner(warnings) {
    const unreadable = warnings.unreadable_transcripts || 0;
    if (!(unreadable > 0)) return '';
    return `
      <div class="banner">
        <b>${unreadable}</b> session${unreadable === 1 ? '' : 's'} skipped —
        transcript unreadable. Counts below are incomplete.
      </div>`;
  }

  // F7: scope note on what the counts include. Verified against the
  // current collection path (tool_collection.collect_per_session ->
  // collect_session -> transcript_walker.walk_session -> _walk_subagents,
  // issue #253 / PR #255 83010fe): subagent and workflow
  // (subagents/workflows/wf_*/) transcripts are walked and their MCP
  // calls are included below — this is *not* the "blind spot" the plan
  // text originally described, since that gap was closed by PR #255
  // before this view was written. Phrased as a bounded scope statement,
  // not a completeness claim: _walk_subagents' own contract still skips
  // transcripts past the path-depth cap, missing JSONL, cycles, or
  // OSError, so "included" does not mean "every possible transcript".
  function renderBlindSpotNote() {
    return `
      <div class="blind-spot">
        Counts include MCP calls from subagent and workflow
        (<code>workflows/wf_*/</code>) transcripts, not just the
        top-level session.
      </div>`;
  }

  function renderMethodRows(byMethod) {
    const entries = Object.entries(byMethod || {});
    if (entries.length === 0) {
      return '<div class="none">No per-method breakdown recorded.</div>';
    }
    return entries
      .sort((a, b) => b[1] - a[1])
      .map(([method, count]) => `
        <div class="row">
          <div>${esc(method)}</div>
          <div class="n">${CP.fmtTokens(count)}</div>
        </div>`)
      .join('');
  }

  function renderServerCard(name, info) {
    // F5: the available-but-unused case — a server the transcripts saw
    // but that was never actually called.
    const isDormant = info.total_calls === 0
      && info.sessions_seen_in !== null
      && info.sessions_seen_in !== undefined;

    return `
      <div class="server-card ${isDormant ? 'dormant' : ''}">
        <div class="h">
          <div class="name">${esc(name)}</div>
          ${isDormant ? '<div class="badge-dormant">available, unused</div>' : ''}
        </div>
        <div class="stats">
          <div class="stat">
            <div class="label">Total calls</div>
            <div class="v">${CP.fmtTokens(info.total_calls)}</div>
          </div>
          <div class="stat">
            <div class="label">Sessions seen in</div>
            <div class="v ${info.sessions_seen_in === null ? 'unknown' : ''}">${formatCountOrUnknown(info.sessions_seen_in)}</div>
          </div>
          <div class="stat">
            <div class="label">Sessions used in</div>
            <div class="v ${info.sessions_used_in === null ? 'unknown' : ''}">${formatCountOrUnknown(info.sessions_used_in)}</div>
          </div>
          <div class="stat">
            <div class="label">Avg calls / active session</div>
            <div class="v ${info.avg_calls_per_active_session === null ? 'unknown' : ''}">${formatAvgOrUnknown(info.avg_calls_per_active_session)}</div>
          </div>
        </div>
        <div class="methods">
          ${renderMethodRows(info.by_method)}
        </div>
      </div>`;
  }

  function renderServers(byServer) {
    const names = Object.keys(byServer).sort();
    if (names.length === 0) {
      return '<div class="empty">No MCP servers recorded.</div>';
    }
    return `
      <div class="servers">
        ${names.map(name => renderServerCard(name, byServer[name])).join('')}
      </div>`;
  }

  // ── Entry point ─────────────────────────────────────────────────────────
  window.renderMcpUsage = function renderMcpUsage(root) {
    if (!document.getElementById('lmu-css')) {
      const style = document.createElement('style');
      style.id = 'lmu-css';
      style.textContent = css;
      document.head.appendChild(style);
    }
    root.classList.add('lmu-style');

    const usage = window.DATA.by_mcp_usage || {};
    const byServer = usage.by_server || {};
    const byTool = usage.by_tool || {};

    // D-E: flag off ⇒ by_mcp_usage is {} ⇒ show the empty state, not a
    // crash or a disappearing tab.
    if (Object.keys(byServer).length === 0 && Object.keys(byTool).length === 0) {
      root.innerHTML = renderEmptyState();
      return;
    }

    const warnings = usage.warnings || {};
    const win = usage.window || {};

    root.innerHTML = `
      <div class="pagehead">
        <div>
          <h1>MCP Tool Usage</h1>
          <div class="sub">${timeBasisLine(win)}</div>
        </div>
      </div>
      ${renderUnreadableBanner(warnings)}
      ${renderBlindSpotNote()}
      ${renderServers(byServer)}
    `;
  };
})();
