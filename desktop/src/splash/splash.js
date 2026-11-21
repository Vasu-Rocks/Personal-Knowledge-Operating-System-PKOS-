'use strict';
const ICONS = { pending: '○', starting: '◌', restarting: '◌', running: '●', degraded: '◐', failed: '✕', stopped: '○' };
const steps = document.getElementById('steps');
const errorBox = document.getElementById('error');
const errorText = document.getElementById('error-text');
const sub = document.getElementById('sub');

function render(status) {
  if (!status) return;
  steps.replaceChildren(...Object.values(status.services).map((s) => {
    const li = document.createElement('li');
    li.className = s.status;
    const icon = document.createElement('span');
    icon.className = 'icon';
    icon.textContent = ICONS[s.status] || '○';
    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = s.label;
    const detail = document.createElement('span');
    detail.className = 'detail';
    detail.textContent = s.detail || (s.status === 'starting' ? 'Starting…' : '');
    li.append(icon, label, detail);
    return li;
  }));
  errorBox.hidden = !status.fatal;
  errorText.textContent = status.fatal || '';
  sub.textContent = status.fatal ? 'Something went wrong while starting.' : 'Starting your knowledge OS…';
}

window.pkos.onStatus(render);
window.pkos.getStatus().then(render);
document.getElementById('retry').addEventListener('click', () => {
  errorBox.hidden = true;
  window.pkos.retry();
});
document.getElementById('logs').addEventListener('click', () => window.pkos.openLogs());
document.getElementById('quit').addEventListener('click', () => window.pkos.quit());
