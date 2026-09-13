(function () {
  function renderSessionDetail(container, session, routeState) {
    const section = document.createElement('section');
    section.className = 'session-detail';

    const back = document.createElement('button');
    back.type = 'button';
    back.textContent = 'Back to dashboard';
    back.addEventListener('click', routeState.close);

    const heading = document.createElement('h2');
    heading.tabIndex = -1;
    heading.textContent = `Session ${String(session.session_id)}`;

    section.append(back, heading);
    container.replaceChildren(section);
    heading.focus();
    return () => container.replaceChildren();
  }

  window.renderSessionDetail = renderSessionDetail;
})();
