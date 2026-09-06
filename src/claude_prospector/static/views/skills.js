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
    .skills-style .command-report {
      margin-top: 28px; padding-top: 24px; border-top: 1px solid #21262d;
    }
    .skills-style .command-heading { margin-bottom: 12px; }
    .skills-style .command-heading h2 {
      margin: 0; color: #f0f6fc; font-size: 17px; font-weight: 600;
    }
    .skills-style .command-heading p {
      margin: 4px 0 0; color: #8b949e; font-size: 11px; line-height: 1.45;
    }
    .skills-style .command-table { min-width: 440px; }
    .skills-style .command-name {
      color: #79c0ff; font-family: ui-monospace, SFMono-Regular, Consolas,
        'Liberation Mono', monospace; font-weight: 600;
    }
    .skills-style .command-warning {
      margin-top: 12px; padding: 10px 12px; color: #c9d1d9;
      background: #161b22; border: 1px solid #21262d;
      border-left: 3px solid #d29922; border-radius: 8px; font-size: 12px;
    }
    .skills-style .command-warning strong { color: #d29922; }
    .skills-style .command-warning ul { margin: 7px 0 0; padding-left: 20px; }
    .skills-style .command-warning li { margin: 3px 0; }
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
      const invocationInfo = Object.prototype.hasOwnProperty.call(bySkill, name)
        ? bySkill[name]
        : null;
      const adoptionInfo = Object.prototype.hasOwnProperty.call(adoption, name)
        ? adoption[name]
        : null;
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
    if (win === undefined) {
      return 'Whole-corpus totals · scoped by the dashboard CLI window · '
        + 'not filtered by the period selector above.';
    }
    win = win || {};
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
    const passEventsStat = adoptionAvailable ? `
        <span><strong>${CP.esc(CP.fmtTokens(passedToAgents))}</strong> recorded pass events</span>` : '';
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
        ${passEventsStat}
      </div>
      ${unavailable}
      ${gapCallout}
      ${table}`;
  }

  function sortedCommandEntries(commands) {
    return Object.entries(commands || {}).sort((left, right) => (
      (Number(right[1].invocation_count) || 0)
      - (Number(left[1].invocation_count) || 0)
      || String(left[0]).localeCompare(String(right[0]))
    ));
  }

  function commandRows(entries) {
    return entries.map(([name, info]) => `
      <tr>
        <td class="command-name">${CP.esc(name)}</td>
        <td>${CP.esc(CP.fmtTokens(info.invocation_count || 0))}</td>
        <td>${CP.esc(CP.fmtTokens(info.sessions_used_in || 0))}</td>
      </tr>`).join('');
  }

  function renderCommandUsage(usage) {
    usage = usage || {};
    const classification = usage.classification || {};
    const provenance = classification.retrieved_at
      ? `Official Claude Code command reference · catalog retrieved ${CP.esc(classification.retrieved_at)}`
      : 'Official Claude Code command reference';
    const heading = `
      <div class="command-heading">
        <h2 id="command-report-heading">Built-in Commands</h2>
        <p>${provenance} · command names only; arguments are never retained.</p>
      </div>`;

    if (!classification.available) {
      return `
        <section class="command-report" aria-labelledby="command-report-heading">
          ${heading}
          <div class="skills-empty">
            <strong>Command classification unavailable</strong>
            The packaged command catalog could not be loaded.
          </div>
        </section>`;
    }

    const builtins = sortedCommandEntries(usage.by_command);
    const unclassified = sortedCommandEntries(usage.unclassified);
    if (builtins.length === 0 && unclassified.length === 0) {
      return `
        <section class="command-report" aria-labelledby="command-report-heading">
          ${heading}
          <div class="skills-empty">
            <strong>No manual built-in command usage recorded</strong>
            Invoke a built-in slash command to populate this report.
          </div>
        </section>`;
    }

    const table = builtins.length === 0 ? `
      <div class="skills-empty">No classified built-in commands recorded.</div>` : `
      <div class="skill-table-wrap">
        <table class="skill-table command-table">
          <thead>
            <tr>
              <th scope="col">Command</th>
              <th scope="col">Invocations</th>
              <th scope="col">Sessions</th>
            </tr>
          </thead>
          <tbody>${commandRows(builtins)}</tbody>
        </table>
      </div>`;
    const warning = unclassified.length === 0 ? '' : `
      <aside class="command-warning" aria-label="Unclassified slash commands">
        <strong>Unclassified commands</strong> are shown for auditability and
        not counted as built-ins.
        <ul>${unclassified.map(([name, info]) => `
          <li><span class="command-name">${CP.esc(name)}</span> —
            ${CP.esc(CP.fmtTokens(info.invocation_count || 0))} invocation(s)
            in ${CP.esc(CP.fmtTokens(info.sessions_used_in || 0))} session(s)
          </li>`).join('')}</ul>
      </aside>`;
    return `
      <section class="command-report" aria-labelledby="command-report-heading">
        ${heading}
        ${table}
        ${warning}
      </section>`;
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
            <p>${timeBasisLine(window.DATA.by_mcp_usage?.window)}</p>
          </div>
          <input id="skill-name-filter" type="search"
            placeholder="Search skill names"
            aria-label="Search skills by name">
        </div>
        <div id="skill-results" aria-live="polite"></div>
        ${renderCommandUsage(window.DATA.by_command_usage)}
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
