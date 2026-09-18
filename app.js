const requestTotal = document.querySelector('#request-total');
const successRate = document.querySelector('#success-rate');
const fallbackTotal = document.querySelector('#fallback-total');
const latency = document.querySelector('#latency');
const eventList = document.querySelector('#event-list');
const toast = document.querySelector('#toast');

const events = [
  ['success', 'Request completed', 'gpt-4o · 842 tokens', 'OpenAI'],
  ['fallback', 'Fallback route used', 'claude-3-5-sonnet · timeout', 'Anthropic'],
  ['limit', 'Rate limit absorbed', 'team: growth · 429 avoided', 'Queue']
];

function renderEvent(event) {
  const symbol = event.kind === 'fallback' ? '↪' : event.kind === 'limit' ? '◌' : '✓';
  return `<span class="event-symbol ${event.kind}">${symbol}</span><div><strong>${event.title}</strong><small>${event.detail}</small></div><time>${event.time}</time><span class="event-route">${event.provider}</span>`;
}

function renderMetrics(metrics) {
  requestTotal.textContent = metrics.requests.toLocaleString();
  successRate.innerHTML = `${metrics.successRate}<span>%</span>`;
  fallbackTotal.textContent = metrics.fallbacks.toLocaleString();
  latency.innerHTML = `${metrics.latency}<span>ms</span>`;
  if (metrics.events.length) eventList.innerHTML = metrics.events.slice(0, 4).map((event) => `<div class="event-row">${renderEvent(event)}</div>`).join('');
}

async function loadMetrics() {
  const response = await fetch('/api/metrics');
  if (!response.ok) throw new Error('Gateway metrics unavailable');
  renderMetrics(await response.json());
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2600);
}

document.querySelector('#send-request').addEventListener('click', async () => {
  const button = document.querySelector('#send-request');
  button.disabled = true;
  try {
    const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Client-ID': 'dashboard' }, body: JSON.stringify({ prompt: 'Explain gateway routing' }) });
    const result = await response.json();
    if (response.status === 429) {
      showToast(`Rate limit active. Retry in ${result.retryAfter}s.`);
      return;
    }
    if (!response.ok) throw new Error(result.error || 'Gateway request failed');
    renderMetrics(result.metrics);
    showToast(result.route === 'Anthropic' ? 'OpenAI timed out. Request routed to Anthropic.' : 'Request completed through OpenAI.');
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll('.range').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.range').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    showToast(`Traffic window changed to ${button.textContent}.`);
  });
});

document.querySelectorAll('.nav-item').forEach((item) => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((navItem) => navItem.classList.remove('active'));
    item.classList.add('active');
  });
});

loadMetrics().catch(() => showToast('Gateway API is offline. Start server.py first.'));