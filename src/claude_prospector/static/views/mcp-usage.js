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
  const esc = CP.esc;

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

  // Issue #279: --track-mcp-call-sizes sometimes surfaces MCP server
  // entries keyed by a raw GUID (e.g. an ephemeral/dynamic connection
  // whose real name wasn't captured) instead of a readable server name.
  // These add noise without conveying anything actionable, so
  // renderServers() below filters them out by default. Extracted as its
  // own helper (rather than inlined at the call site) because the
  // regression test asserts on it directly.
  const GUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  function isGuidLike(name) {
    return GUID_RE.test(name);
  }

  // F5 (issue #248): the available-but-unused case -- a server the
  // transcripts saw but that was never actually called (total_calls is
  // 0, but sessions_seen_in is populated from availability signal, not
  // from calls -- see aggregator.py's server_seen_sessions, filled
  // independently of server_calls). Issue #281 hides these cards from
  // renderServers' default output; extracted here (mirrors isGuidLike)
  // so renderServerCard's badge condition and renderServers' filter
  // share one definition instead of drifting apart.
  function isDormantServer(info) {
    return info.total_calls === 0
      && info.sessions_seen_in !== null
      && info.sessions_seen_in !== undefined;
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
    .lmu-style .pagehead input#mcp-name-filter {
      background: #0d1117;
      border: 1px solid #21262d;
      border-radius: 6px;
      padding: 6px 10px;
      color: #c9d1d9;
      font-size: 12px;
      min-width: 220px;
    }
    .lmu-style .pagehead input#mcp-name-filter::placeholder { color: #6e7681; }

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
    /* Issue #284: .methods is a single shared grid so the count/tokens
       columns line up across every method row. Previously .row was its
       own flex box with justify-content: space-between -- fine for
       exactly 2 children (name flush-left, count flush-right), but once
       the per-method tokens note (issue #262) added a 3rd child, the
       middle item (count) lost its flush-right anchor and floated to a
       position based on the surrounding items' widths, shifting
       row-to-row with method-name length. Setting .row's display to
       "contents" lets its children become direct grid items of
       .methods, sharing one set of column tracks across all rows --
       true columnar alignment instead of per-row flex distribution. */
    .lmu-style .server-card .methods {
      border-top: 1px solid #21262d;
      padding-top: 8px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      column-gap: 10px;
      row-gap: 6px;
    }
    .lmu-style .server-card .methods .row {
      display: contents;
      font-size: 12px; color: #c9d1d9;
    }
    /* Name column shares its grid track (minmax(0, 1fr) above) with every
       other row via .methods' shared grid, so an unbounded method name
       would otherwise overflow past the card edge -- truncate instead. */
    .lmu-style .server-card .methods .row > div:first-child {
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .lmu-style .server-card .methods .row .n { color: #8b949e; font-variant-numeric: tabular-nums; text-align: right; }
    .lmu-style .server-card .methods .none {
      font-size: 11px; color: #6e7681; font-style: italic;
    }
    /* Issue #283: collapsed per-method breakdown for servers with a large
       tool surface (e.g. 20+ mcp__github__* tools). Sits above .methods
       (not inside it), so .methods' shared 3-column grid contract (#284)
       is unaffected regardless of collapse state. */
    .lmu-style .server-card details.methods-collapse {
      border-top: 1px solid #21262d;
      padding-top: 8px;
    }
    .lmu-style .server-card details.methods-collapse summary {
      cursor: pointer;
      font-size: 12px;
      color: #8b949e;
    }
    .lmu-style .server-card details.methods-collapse[open] summary {
      margin-bottom: 8px;
    }
    .lmu-style .server-card details.methods-collapse .methods {
      border-top: none;
      padding-top: 0;
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
        <code>--track-mcp-calls</code> or <code>--track-mcp-call-sizes</code>
        to enable collection.
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
  // calls are included below — this is *not* the "blind spot" issue
  // #248's implementation plan originally described, since that gap was
  // closed by PR #255 before this view was written. Phrased as a bounded
  // scope statement, not a completeness claim: _walk_subagents' own
  // contract still skips transcripts past the path-depth cap, missing
  // JSONL, cycles, or OSError, so "included" does not mean "every
  // possible transcript".
  function renderBlindSpotNote() {
    return `
      <div class="blind-spot">
        Counts include MCP calls from subagent and workflow
        (<code>workflows/wf_*/</code>) transcripts, not just the
        top-level session.
      </div>`;
  }

  // Cost-proxy per-method note (issue #262, plan §6c). byMethodTokens is
  // the additive `by_method_tokens` sibling map Phase 2 emits alongside
  // `by_method` -- absent entirely whenever --track-mcp-call-sizes was
  // off, so every access below is guarded rather than assumed present.
  // Issue #284: always return a (possibly empty) third cell rather than
  // '' when stats are absent. `.methods` is a shared 3-column CSS grid
  // (see css below) and `.row` participates via `display: contents` --
  // grid auto-placement fills cells left-to-right and wraps after every
  // 3 items, so a row that emits only 2 children (the '' case) would
  // shift every subsequent row's cells by one column. Returning an empty
  // placeholder cell keeps every row's child count at a fixed 3,
  // regardless of whether per-method token data exists for it.
  function renderMethodTokensNote(method, byMethodTokens) {
    const stats = byMethodTokens && byMethodTokens[method];
    if (!stats) return '<div class="n"></div>';
    return `<div class="n">(est. ${formatCountOrUnknown(stats.total)} tok)</div>`;
  }

  // Issue #282: `query` narrows the per-method/tool rows shown inside a
  // server card. Callers only pass a non-empty query when the server's
  // own name didn't match the filter (see renderServerCard) -- in that
  // case, a card is only rendered at all because at least one method
  // matched (renderServers' own filter), so this narrows the card's
  // body down to the method(s) that earned it a spot.
  function renderMethodRows(byMethod, byMethodTokens, query) {
    const entries = Object.entries(byMethod || {});
    if (entries.length === 0) {
      return '<div class="none">No per-method breakdown recorded.</div>';
    }
    const filtered = query
      ? entries.filter(([method]) => CP.matchesNameFilter(method, query))
      : entries;
    if (filtered.length === 0) {
      return '<div class="none">No tools match the current filter.</div>';
    }
    return filtered
      .sort((a, b) => b[1] - a[1])
      .map(([method, count]) => `
        <div class="row">
          <div>${esc(method)}</div>
          <div class="n">${CP.fmtTokens(count)}</div>
          ${renderMethodTokensNote(method, byMethodTokens)}
        </div>`)
      .join('');
  }

  // Issue #283: servers with a large tool surface (e.g. GitHub's 20+
  // mcp__github__* tools) render one row per tool, dominating the card.
  // Above this many distinct methods, collapse the breakdown behind a
  // native <details> disclosure instead -- zero JS event-wiring needed,
  // and it degrades gracefully (still readable/expandable without CSS/JS).
  const TOOL_COLLAPSE_THRESHOLD = 8;

  // Wraps renderMethodRows' output in `.methods` (unchanged shape/contract
  // -- see #284) and, once a server exceeds TOOL_COLLAPSE_THRESHOLD
  // distinct methods, wraps that whole `.methods` block in a collapsed
  // <details> summarizing the tool count + aggregate call total (and,
  // when --track-mcp-call-sizes populated by_method_tokens, an aggregate
  // token total alongside it -- issue #283's "aggregate calls/tokens"
  // ask). The <details> element sits *outside* `.methods`, so `.methods`'
  // shared 3-column grid contract (#284) is untouched either way.
  function renderMethodsBlock(info, query) {
    const byMethod = info.by_method || {};
    const entries = Object.entries(byMethod);
    const methodsHtml = `
        <div class="methods">
          ${renderMethodRows(byMethod, info.by_method_tokens, query)}
        </div>`;

    if (entries.length <= TOOL_COLLAPSE_THRESHOLD) {
      return methodsHtml;
    }

    const totalCalls = Object.values(byMethod)
      .reduce((sum, count) => sum + count, 0);
    // Issue #283 (CodeRabbit, PR #293): the request asks to aggregate
    // "calls/tokens" -- by_method_tokens is only present when
    // --track-mcp-call-sizes was passed, so this is guarded the same
    // way as renderEstimatedTokensStat/renderCostProxyBanner (optional
    // chaining + a null totalTokens when the map is absent), and the
    // summary text below omits the token clause entirely in that case
    // rather than rendering a misleading "0 tokens".
    const byMethodTokens = info.by_method_tokens;
    const totalTokens = byMethodTokens
      ? Object.values(byMethodTokens).reduce((sum, stats) => sum + (stats?.total || 0), 0)
      : null;
    const tokensClause = totalTokens !== null
      ? `, ~${formatCountOrUnknown(totalTokens)} tokens`
      : '';
    return `
        <details class="methods-collapse">
          <summary>${entries.length} tools, ${CP.fmtTokens(totalCalls)} calls${tokensClause}</summary>
          ${methodsHtml}
        </details>`;
  }

  // Cost-proxy stat + caveat (issue #262, plan §6c). `estimated_result_tokens`
  // is entirely absent from `info` unless --track-mcp-call-sizes was
  // passed (Phase 2, aggregator.py) -- every access below is guarded via
  // optional chaining, so the existing three-stat rendering keeps working
  // unchanged when the field is missing.
  function renderEstimatedTokensStat(info) {
    const total = info.estimated_result_tokens?.total;
    return `
      <div class="stat">
        <div class="label" title="Estimated from tool_result payload size -- a proxy, not a measured token count.">Est. result tokens</div>
        <div class="v ${total === null || total === undefined ? 'unknown' : ''}">${formatCountOrUnknown(total)}</div>
      </div>`;
  }

  // Issue #280: one top-level banner instead of a per-card repeat.
  // Guarded so it disappears when no server carries
  // estimated_result_tokens data (--track-mcp-call-sizes was off).
  function renderCostProxyBanner(byServer) {
    const hasEstimatedTokens = Object.values(byServer).some(
      (info) => info.estimated_result_tokens
    );
    if (!hasEstimatedTokens) return '';
    return `
      <div class="blind-spot">
        "Est. result tokens" is a proxy, not a measured token count —
        it's each call's <code>tool_result</code> character length divided
        by an estimated chars-per-token ratio.
      </div>`;
  }

  function renderServerCard(name, info, query) {
    // F5: the available-but-unused case — a server the transcripts saw
    // but that was never actually called. Issue #281 filters these out
    // of renderServers' default output (replaced by
    // renderZeroCallHiddenNote below), so this branch is normally
    // unreachable via that path -- kept correct in case
    // renderServerCard is ever called with unfiltered data.
    const isDormant = isDormantServer(info);

    // Issue #282: if the server's own name matched the active filter,
    // show every method unfiltered (the user searched for the server,
    // not a specific tool). Otherwise only pass the query through to
    // renderMethodRows -- this card is only included at all because at
    // least one method matched (see renderServers), so narrow to those.
    const methodQuery = (query && !CP.matchesNameFilter(name, query)) ? query : '';

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
          ${renderEstimatedTokensStat(info)}
        </div>
        ${renderMethodsBlock(info, methodQuery)}
      </div>`;
  }

  // Issue #279: hidden-count note uses the same `.blind-spot` treatment
  // as renderBlindSpotNote() above -- small, low-emphasis text, not a
  // dismissable banner (no interaction affordance exists in this file's
  // style vocabulary, so "dismissible-in-spirit" means "easy to skim
  // past", matching the existing note style).
  function renderGuidHiddenNote(hiddenCount) {
    if (hiddenCount === 0) return '';
    const plural = hiddenCount === 1 ? '' : 's';
    return `
      <div class="blind-spot">
        <b>${hiddenCount}</b> MCP server${plural} with GUID-styled names
        hidden — likely ephemeral/dynamic connections.
      </div>`;
  }

  // Issue #281: hidden-count note for zero-call ("dormant" -- F5, issue
  // #248) servers, mirroring renderGuidHiddenNote's shape immediately
  // above. The individual dashed-border cards no longer render by
  // default, but the "available, never called" signal isn't dropped --
  // it's summarized here instead.
  function renderZeroCallHiddenNote(hiddenCount) {
    if (hiddenCount === 0) return '';
    const plural = hiddenCount === 1 ? '' : 's';
    return `
      <div class="blind-spot">
        <b>${hiddenCount}</b> MCP server${plural} available but never
        called — hidden (zero total calls).
      </div>`;
  }

  // Issue #282: `query` is the pre-trimmed, pre-lower-cased name filter
  // (see renderMcpUsage's 'input' listener) -- '' means no active
  // filter. Composes with (applied on top of, not instead of) the
  // #279 GUID filter and #281 zero-call filter above: those determine
  // what's eligible to render at all, this narrows further by name.
  function renderServers(byServer, query) {
    const allNames = Object.keys(byServer).sort();
    const nonGuidNames = allNames.filter(name => !isGuidLike(name));
    const nonDormantNames = nonGuidNames.filter(name => !isDormantServer(byServer[name]));
    // A server card stays visible if its own name matches, or any of
    // its methods/tools do -- checked via `by_method`, the same field
    // renderServerCard/renderMethodRows read the per-method map from.
    const names = !query
      ? nonDormantNames
      : nonDormantNames.filter(name => {
          if (CP.matchesNameFilter(name, query)) return true;
          const methodNames = Object.keys(byServer[name].by_method || {});
          return methodNames.some(method => CP.matchesNameFilter(method, query));
        });
    const hiddenGuidCount = allNames.length - nonGuidNames.length;
    const hiddenDormantCount = nonGuidNames.length - nonDormantNames.length;
    const hiddenNote = renderGuidHiddenNote(hiddenGuidCount)
      + renderZeroCallHiddenNote(hiddenDormantCount);

    if (names.length === 0) {
      // Issue #281: distinguish "nothing was ever recorded" (allNames
      // empty) from "servers exist but every one was filtered out above"
      // -- the original unconditional message would be misleading in the
      // latter case since the hidden-count note(s) just said otherwise.
      // Issue #282: the name filter reuses this same branch (and copy)
      // for "no server/tool name matched" -- also correct/non-misleading
      // since the copy says "filters above" generically.
      const emptyMessage = allNames.length === 0
        ? 'No MCP servers recorded.'
        : 'No MCP servers to show — every entry was hidden by the filters above.';
      return `${hiddenNote}<div class="empty">${emptyMessage}</div>`;
    }
    return `
      ${hiddenNote}
      <div class="servers">
        ${names.map(name => renderServerCard(name, byServer[name], query)).join('')}
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

    // Issue #282: name/tool search box. Rendered inside its own
    // #mcp-server-list wrapper (below) so the 'input' listener can
    // re-render just that container's contents on each keystroke,
    // rather than replacing `root.innerHTML` wholesale -- doing the
    // latter would tear down and recreate the input itself, dropping
    // focus/cursor position mid-typing.
    root.innerHTML = `
      <div class="pagehead">
        <div>
          <h1>MCP Tool Usage</h1>
          <div class="sub">${timeBasisLine(win)}</div>
        </div>
        <input id="mcp-name-filter" type="text"
          placeholder="Filter by server/tool name..."
          aria-label="Filter MCP servers and tools by name" />
      </div>
      ${renderUnreadableBanner(warnings)}
      ${renderCostProxyBanner(byServer)}
      ${renderBlindSpotNote()}
      <div id="mcp-server-list">${renderServers(byServer, '')}</div>
    `;

    const filterInput = root.querySelector('#mcp-name-filter');
    const serverList = root.querySelector('#mcp-server-list');
    filterInput.addEventListener('input', () => {
      const query = filterInput.value.trim().toLowerCase();
      serverList.innerHTML = renderServers(byServer, query);
    });
  };
})();
