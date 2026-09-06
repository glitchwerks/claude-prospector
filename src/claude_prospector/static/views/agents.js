// Searchable agent statistics view (issue #295).

(function () {
  const PERIODS = ['5h', '24h', '7d', '30d', 'all'];

  function matchesAgentFilter(name, query) {
    return String(name).toLowerCase().includes(String(query).trim().toLowerCase());
  }

  function modelClass(model) {
    const value = String(model || '').toLowerCase();
    if (value.includes('opus')) return 'badge-opus';
    if (value.includes('sonnet')) return 'badge-sonnet';
    if (value.includes('haiku')) return 'badge-haiku';
    return 'badge-unknown';
  }

  function periodAgents(period) {
    if (period === 'all') return window.DATA.by_agent || {};
    const sessions = CP.filterSessions(window.DATA.sessions, period);
    return CP.reAggregate(sessions, window.DATA.by_agent).byAgent;
  }

  function renderPeriodTabs(activePeriod) {
    return PERIODS.map(period => `
      <button data-period="${period}"
        class="${period === activePeriod ? 'active' : ''}"
        aria-pressed="${period === activePeriod ? 'true' : 'false'}">
        ${period === 'all' ? 'All' : period}
      </button>`).join('');
  }

  function renderAgentRows(state) {
    const agents = periodAgents(state.period);
    const rows = Object.entries(agents)
      .filter(([name]) => matchesAgentFilter(name, state.query))
      .sort((left, right) => {
        const tokenDelta = (right[1].total_tokens || 0)
          - (left[1].total_tokens || 0);
        return tokenDelta || left[0].localeCompare(right[0]);
      });
    const matchCount = `<div class="agents-count" id="agent-match-count">
      ${rows.length} matching agent path${rows.length === 1 ? '' : 's'}
    </div>`;

    if (!rows.length) {
      return `${matchCount}<div class="agents-empty">
        No agents match “${CP.esc(state.query)}” in this period.
      </div>`;
    }

    return `${matchCount}
      <div class="agents-table" role="table"
        aria-label="Agent usage statistics">
        <div class="agents-row agents-head" role="row">
          <div role="columnheader">Agent path</div>
          <div role="columnheader">Model</div>
          <div role="columnheader">Tokens</div>
          <div role="columnheader">Messages</div>
          <div role="columnheader">Sessions</div>
          <div role="columnheader">Cache created</div>
          <div role="columnheader">Cache read</div>
        </div>
        ${rows.map(([name, info]) => {
          const model = info.primary_model || 'unknown';
          const rootContext = name === 'general'
            ? '<span class="root-context">root session context</span>'
            : '';
          return `<div class="agents-row" role="row">
            <div class="agent-path" role="cell">${CP.agentLeaf(name)}${rootContext}</div>
            <div role="cell"><span class="badge-model ${modelClass(model)}">${CP.esc(model)}</span></div>
            <div class="num metric-strong" role="cell">${CP.fmtTokens(info.total_tokens || 0)}</div>
            <div class="num" role="cell">${CP.fmtTokens(info.message_count || 0)}</div>
            <div class="num" role="cell">${CP.fmtTokens(info.session_count || 0)}</div>
            <div class="num" role="cell">${CP.fmtTokens(info.cache_creation_tokens || 0)}</div>
            <div class="num" role="cell">${CP.fmtTokens(info.cache_read_tokens || 0)}</div>
          </div>`;
        }).join('')}
      </div>`;
  }

  function renderAgents(root) {
    const state = { period: '7d', query: '' };
    root.innerHTML = `
      <style>
        .agents-view .agents-toolbar {
          display: flex; align-items: end; justify-content: space-between;
          gap: 16px; margin-bottom: 14px; flex-wrap: wrap;
        }
        .agents-view .agents-title h1 {
          color: #f0f6fc; font-size: 22px; font-weight: 600;
          letter-spacing: -0.02em;
        }
        .agents-view .agents-title p {
          color: #8b949e; font-size: 12px; margin-top: 5px;
        }
        .agents-view .agents-controls {
          display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
        }
        .agents-view .agent-search {
          min-width: 300px; background: #0d1117; color: #f0f6fc;
          border: 1px solid #30363d; border-radius: 8px;
          padding: 8px 11px; font: inherit; outline: none;
        }
        .agents-view .agent-search:focus {
          border-color: #58a6ff;
          box-shadow: 0 0 0 3px rgba(88,166,255,0.16);
        }
        .agents-view .agents-count {
          color: #8b949e; font-size: 11px; margin-bottom: 8px;
        }
        .agents-view .agents-table {
          border: 1px solid #21262d; border-radius: 10px;
          background: #161b22; overflow-x: auto;
        }
        .agents-view .agents-row {
          display: grid;
          grid-template-columns: minmax(220px, 1.7fr) 110px 100px 85px 75px 110px 110px;
          gap: 12px; align-items: center; min-width: 900px;
          padding: 10px 14px; border-bottom: 1px solid #21262d;
        }
        .agents-view .agents-row:last-child { border-bottom: 0; }
        .agents-view .agents-head {
          color: #8b949e; background: #0d1117; font-size: 11px;
          font-weight: 500;
        }
        .agents-view .agents-row > div:not(:first-child) { text-align: right; }
        .agents-view .agent-path .leaf { color: #f0f6fc; font-weight: 600; }
        .agents-view .agent-path .chain { color: #6e7681; font-size: 10px; }
        .agents-view .root-context {
          display: inline-block; margin-left: 8px; color: #79c0ff;
          font-size: 10px;
        }
        .agents-view .metric-strong { color: #f0f6fc; font-weight: 600; }
        .agents-view .agents-empty {
          border: 1px dashed #30363d; border-radius: 10px;
          color: #8b949e; padding: 42px 18px; text-align: center;
        }
        @media (max-width: 720px) {
          .agents-view .agents-controls,
          .agents-view .agent-search { width: 100%; min-width: 0; }
        }
      </style>
      <section class="agents-view">
        <div class="agents-toolbar">
          <div class="agents-title">
            <h1>Agent lookup</h1>
            <p id="agent-time-basis">Selected-period totals · parent names include descendant paths.</p>
          </div>
          <div class="agents-controls">
            <input id="agent-name-filter" class="agent-search" type="search"
              aria-label="Search full agent paths"
              placeholder="Search path; parent names include descendants">
            <div class="period-tabs" id="agent-periods"
              aria-label="Agent statistics period">
              ${renderPeriodTabs(state.period)}
            </div>
          </div>
        </div>
        <div id="agent-result-list" aria-live="polite"></div>
      </section>`;

    const resultList = root.querySelector('#agent-result-list');
    const filterInput = root.querySelector('#agent-name-filter');
    const periodButtons = root.querySelectorAll('#agent-periods button');

    function updateResults() {
      resultList.innerHTML = renderAgentRows(state);
    }

    filterInput.addEventListener('input', function () {
      state.query = filterInput.value;
      updateResults();
    });

    periodButtons.forEach(button => {
      button.addEventListener('click', function () {
        state.period = button.dataset.period;
        periodButtons.forEach(candidate => {
          const active = candidate.dataset.period === state.period;
          candidate.classList.toggle('active', active);
          candidate.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        updateResults();
      });
    });

    updateResults();
  }

  window.renderAgents = renderAgents;
})();
