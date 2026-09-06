// Skill Usage view — top-level dashboard report for transcript skill
// invocations and skill-tracker hook adoption events. The two sources use
// independently-filtered time windows, so missing adoption data stays null
// rather than being presented as observed zero.

(function () {
  const css = `
    .skills-style { color: #c9d1d9; }
    .skills-style .skills-view { max-width: 1180px; }
    .skills-style .skills-toolbar {
      display: flex; align-items: flex-end; justify-content: space-between;
      flex-wrap: wrap; gap: 16px; margin-bottom: 16px;
    }
    .skills-style .skills-toolbar h1 {
      margin: 0; color: #f0f6fc; font-size: 22px; font-weight: 600;
      letter-spacing: -0.02em;
    }
    .skills-style .skills-toolbar p {
      margin: 4px 0 0; color: #8b949e; font-size: 12px;
    }
    .skills-style input#skill-name-filter {
      min-width: 220px; padding: 6px 10px; color: #c9d1d9;
      background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
      font-size: 12px;
    }
    .skills-style input#skill-name-filter::placeholder { color: #6e7681; }
    .skills-style input#skill-name-filter:focus-visible,
    .skills-style summary:focus-visible {
      outline: 2px solid #58a6ff; outline-offset: 2px;
    }
    .skills-style .skills-stats {
      display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 0 0 12px;
      color: #8b949e; font-size: 12px;
    }
    .skills-style .skills-stats strong { color: #f0f6fc; font-variant-numeric: tabular-nums; }
    .skills-style .skills-note,
    .skills-style .skills-gap,
    .skills-style .skills-empty {
      background: #161b22; border: 1px solid #21262d; border-radius: 8px;
      font-size: 12px;
    }
    .skills-style .skills-note {
      margin: 0 0 12px; padding: 10px 12px; color: #8b949e;
    }
    .skills-style .skills-gap {
      margin: 0 0 12px; padding: 10px 12px; border-left: 3px solid #d29922;
      color: #c9d1d9;
    }
    .skills-style .skills-gap strong { color: #d29922; }
    .skills-style .skills-gap ul { margin: 6px 0 0; padding-left: 20px; }
    .skills-style .skill-table-wrap {
      overflow-x: auto; border: 1px solid #21262d; border-radius: 8px;
      background: #161b22;
    }
    .skills-style .skill-table {
      width: 100%; min-width: 760px; border-collapse: collapse; font-size: 12px;
    }
    .skills-style .skill-table th,
    .skills-style .skill-table td {
      padding: 10px 12px; border-bottom: 1px solid #21262d; text-align: right;
      font-variant-numeric: tabular-nums; vertical-align: top;
    }
    .skills-style .skill-table th {
      color: #8b949e; font-size: 11px; font-weight: 600; white-space: nowrap;
    }
    .skills-style .skill-table th:first-child,
    .skills-style .skill-table td:first-child { text-align: left; }
    .skills-style .skill-table tr:last-child td { border-bottom: 0; }
    .skills-style .skill-name { color: #f0f6fc; font-weight: 600; word-break: break-word; }
    .skills-style .skill-unknown { color: #6e7681; }
    .skills-style .skill-targets { margin-top: 6px; color: #8b949e; font-weight: 400; }
    .skills-style .skill-targets summary { cursor: pointer; font-size: 11px; }
    .skills-style .skill-targets ul { margin: 6px 0 0; padding-left: 18px; }
    .skills-style .skill-targets li { margin: 2px 0; }
    .skills-style .skills-footnote {
      margin: 10px 0 0; color: #8b949e; font-size: 11px; line-height: 1.45;
    }
    .skills-style .skills-empty { padding: 28px 20px; text-align: center; color: #8b949e; }
    .skills-style .skills-empty strong { display: block; color: #f0f6fc; margin-bottom: 5px; }
    @media (max-width: 600px) {
      .skills-style .skills-toolbar { align-items: stretch; }
      .skills-style input#skill-name-filter { width: 100%; min-width: 0; }
    }
  `;

  function skillRows() {
    const bySkill = window.DATA.by_skill || {};
    const adoption = window.DATA.by_skill_adoption || {};
    const names = [...new Set([
      ...Object.keys(bySkill),
      ...Object.keys(adoption),
    ])];
    return names.map(name => {
      const invocationInfo = bySkill[name] || null;
      const adoptionInfo = adoption[name] || null;
      const tracked = Boolean(adoptionInfo);
      return {
        name,
        invocations: invocationInfo ? invocationInfo.invocation_count : 0,
        totalTokens: invocationInfo ? invocationInfo.total_tokens : 0,
        timesPassed: tracked ? adoptionInfo.times_passed : null,
        timesInvoked: tracked ? adoptionInfo.times_invoked : null,
        adoptionRate: tracked ? adoptionInfo.adoption_rate : null,
        byTargetAgent: tracked ? (adoptionInfo.by_target_agent || {}) : {},
      };
    });
  }

  function formatUnknown(value) {
    return value === null ? '—' : CP.fmtTokens(value);
  }

  function formatRate(value) {
    return value === null ? 'n/a' : `${Math.round(value * 100)}%`;
  }

  function formatWindowBound(value) {
    if (!value) return null;
    const raw = String(value);
    const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(raw);
    const date = new Date(isDateOnly ? `${raw}T00:00:00` : raw);
    if (Number.isNaN(date.getTime())) return CP.esc(raw);
    return CP.esc(date.toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    }));
  }

  function timeBasisLine(win) {
    const start = formatWindowBound(win.start);
    const end = formatWindowBound(win.end);
    const scope = (win.start == null && win.end == null)
      ? 'all time'
      : `${start || 'unknown start'} – ${end || 'unknown end'}`;
    return `Whole-corpus totals · ${scope} · not filtered by the period selector above.`;
  }

  function sortedRows(rows) {
    return rows.slice().sort((left, right) => (
      right.invocations - left.invocations
      || (right.timesPassed || 0) - (left.timesPassed || 0)
      || String(left.name).localeCompare(String(right.name))
    ));
  }

  function renderTargetAgents(row) {
    if (row.timesPassed === null) return '';
    const entries = Object.entries(row.byTargetAgent).sort((left, right) => (
      (Number(right[1].passed) || 0) - (Number(left[1].passed) || 0)
      || (Number(right[1].invoked) || 0) - (Number(left[1].invoked) || 0)
      || String(left[0]).localeCompare(String(right[0]))
    ));
    const agents = entries.length === 0
      ? '<li>No target agent recorded.</li>'
      : entries.map(([agent, agentInfo]) => {
          const passed = agentInfo.passed;
          const invoked = agentInfo.invoked;
          return `<li>${CP.esc(agent)} — Passed: ${CP.esc(CP.fmtTokens(passed))}; `
            + `Invoked: ${CP.esc(CP.fmtTokens(invoked))}</li>`;
        }).join('');
    return `
      <details class="skill-targets">
        <summary>Target agent as recorded by the skill-tracker hook</summary>
        <ul>${agents}</ul>
      </details>`;
  }

  function renderRow(row) {
    const passed = formatUnknown(row.timesPassed);
    const invoked = formatUnknown(row.timesInvoked);
    const rate = formatRate(row.adoptionRate);
    return `
      <tr>
        <td class="skill-name">${CP.esc(row.name)}${renderTargetAgents(row)}</td>
        <td>${CP.esc(CP.fmtTokens(row.invocations))}</td>
        <td>${CP.esc(CP.fmtTokens(row.totalTokens))}</td>
        <td class="${row.timesPassed === null ? 'skill-unknown' : ''}">${CP.esc(passed)}</td>
        <td class="${row.timesInvoked === null ? 'skill-unknown' : ''}">${CP.esc(invoked)}</td>
        <td class="${row.adoptionRate === null ? 'skill-unknown' : ''}">${CP.esc(rate)}</td>
      </tr>`;
  }

  function renderResults(allRows, adoptionAvailable, query) {
    if (allRows.length === 0) {
      return `
        <div class="skills-empty">
          <strong>No skill usage recorded</strong>
          Run the dashboard against Claude Code transcripts to populate this report.
        </div>`;
    }

    const visibleRows = sortedRows(allRows.filter(row => (
      CP.matchesNameFilter(row.name, query)
    )));
    const invokedSkills = allRows.filter(row => row.invocations > 0).length;
    const passedToAgents = allRows.reduce(
      (total, row) => total + (row.timesPassed || 0),
      0,
    );
    const gaps = adoptionAvailable
      ? visibleRows.filter(row => row.timesPassed > 0 && row.adoptionRate === 0)
      : [];
    const unavailable = adoptionAvailable ? '' : `
      <div class="skills-note">
        Adoption tracking unavailable — enable the skill-tracker PreToolUse hook.
      </div>`;
    const gapCallout = gaps.length === 0 ? '' : `
      <aside class="skills-gap" aria-label="Skills passed to agents but never invoked">
        <strong>Adoption gaps</strong>
        <ul>${gaps.map(row => `<li>${CP.esc(row.name)}</li>`).join('')}</ul>
      </aside>`;
    const table = visibleRows.length === 0 ? `
      <div class="skills-empty">No skills match this search.</div>` : `
      <div class="skill-table-wrap">
        <table class="skill-table">
          <thead>
            <tr>
              <th scope="col">Skill</th>
              <th scope="col">Invocations</th>
              <th scope="col">Tokens</th>
              <th scope="col">Times passed</th>
              <th scope="col">Times invoked</th>
              <th scope="col">Adoption</th>
            </tr>
          </thead>
          <tbody>${visibleRows.map(renderRow).join('')}</tbody>
        </table>
      </div>
      <p class="skills-footnote">
        Transcript invocations and hook-correlated times invoked are different
        measurements, based on independently filtered transcript messages and
        skill-tracker events, so they can legitimately differ.
      </p>`;
    return `
      <div class="skills-stats">
        <span><strong>${CP.esc(CP.fmtTokens(invokedSkills))}</strong> skills invoked</span>
        <span><strong>${CP.esc(CP.fmtTokens(passedToAgents))}</strong> passed to agents</span>
      </div>
      ${unavailable}
      ${gapCallout}
      ${table}`;
  }

  function renderSkills(root) {
    if (!document.getElementById('skills-css')) {
      const style = document.createElement('style');
      style.id = 'skills-css';
      style.textContent = css;
      document.head.appendChild(style);
    }
    root.classList.add('skills-style');

    const rows = skillRows();
    const adoption = window.DATA.by_skill_adoption || {};
    const state = { query: '' };
    root.innerHTML = `
      <section class="skills-view">
        <div class="skills-toolbar">
          <div>
            <h1>Skill Usage</h1>
            <p>${timeBasisLine(window.DATA.by_mcp_usage?.window || {})}</p>
          </div>
          <input id="skill-name-filter" type="search"
            placeholder="Search skill names"
            aria-label="Search skills by name">
        </div>
        <div id="skill-results" aria-live="polite"></div>
      </section>`;

    const filterInput = root.querySelector('#skill-name-filter');
    const results = root.querySelector('#skill-results');
    const adoptionAvailable = Object.keys(adoption).length > 0;
    results.innerHTML = renderResults(rows, adoptionAvailable, state.query);
    filterInput.addEventListener('input', function () {
      state.query = filterInput.value;
      results.innerHTML = renderResults(rows, adoptionAvailable, state.query);
    });
  }

  window.renderSkills = renderSkills;
})();
