// Router + sidebar. Each screen is a standalone web component, so any of them can be embedded
// on its own (e.g. as a Dynamics 365 HTML web resource) with window.CQA_API_BASE set to the backend.
import { api } from './api.js';
import { esc, icon } from './ui.js';
import './components/score-ring.js';
import './components/dialog-list.js';
import './components/evaluation-view.js';
import './components/appeals-view.js';
import './components/checklist-editor.js';
import './components/compare-view.js';
import './components/trainer-view.js';

const routes = {
  dialogs: () => '<cqa-dialog-list></cqa-dialog-list>',
  dialog: id => `<cqa-evaluation-view conversation-id="${esc(id)}"></cqa-evaluation-view>`,
  appeals: () => '<cqa-appeals-view></cqa-appeals-view>',
  checklist: () => '<cqa-checklist-editor></cqa-checklist-editor>',
  trainer: () => '<cqa-trainer-view></cqa-trainer-view>',
  compare: () => '<cqa-compare-view></cqa-compare-view>',
};

function render() {
  const path = location.hash.replace(/^#\/?/, '').split('?')[0];
  const [name, ...rest] = path.split('/');
  const route = routes[name] ? name : 'dialogs';
  const arg = decodeURIComponent(rest.join('/'));
  document.getElementById('view').innerHTML = route === 'dialog' && !arg ? routes.dialogs() : routes[route](arg);
  const active = route === 'dialog' ? 'dialogs' : route;
  document.querySelectorAll('.nav-links a').forEach(a => a.classList.toggle('active', a.dataset.route === active));
  window.scrollTo(0, 0);
}

// ---- theme (remembered in localStorage; default light)
const THEME_KEY = 'cqa:theme';
function savedTheme() { try { return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'; } catch { return 'light'; } }
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const b = document.getElementById('themeToggle');
  b.textContent = t === 'dark' ? '☀ Светлая' : '☾ Тёмная';
  b.setAttribute('aria-pressed', String(t === 'dark'));
}
document.getElementById('themeToggle').addEventListener('click', () => {
  const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem(THEME_KEY, t); } catch { /* storage unavailable: theme is just not remembered */ }
  applyTheme(t);
  render(); // JS-coloured elements (score ring) pick up the new theme
});
applyTheme(savedTheme());

// ---- model badge + popover with the chain of models and providers
let lastHealth = null;
const PROVIDER_NAME = { gemini: 'Gemini', openai: 'Groq (запасной)', mock: 'MOCK' };
function popHtml(h) {
  if (!h) return '<b>Сервер недоступен</b>';
  if (h.provider === 'mock') return '<b>MOCK-режим</b><div>Нет ключа модели: оценки — заглушки.</div>';
  const models = String(h.model || '').split(',').map(x => x.trim()).filter(Boolean);
  return `<div class="pop-t">Цепочка провайдеров</div><div>${h.chain.map(c => esc(PROVIDER_NAME[c] || c)).join(' → ')}</div>
    <div class="pop-t">Модели Gemini по порядку</div><ol>${models.map(m => `<li>${esc(m)}</li>`).join('')}</ol>
    <div class="pop-t">Статус</div><div><span class="dot" style="background:var(--ok)"></span>работает · оценок в базе: ${h.evaluations}</div>`;
}
const pop = document.getElementById('modelPop'), badge0 = document.getElementById('providerInfo');
let pinned = false;
function showPop() { pop.innerHTML = popHtml(lastHealth); pop.hidden = false; badge0.setAttribute('aria-expanded', 'true'); }
function hidePop() { pop.hidden = true; pinned = false; badge0.setAttribute('aria-expanded', 'false'); }
badge0.addEventListener('mouseenter', showPop);
badge0.addEventListener('mouseleave', () => { if (!pinned) pop.hidden = true; });
badge0.addEventListener('click', e => { e.stopPropagation(); if (pinned) hidePop(); else { pinned = true; showPop(); } });
document.addEventListener('click', e => { if (pinned && !pop.contains(e.target)) hidePop(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') hidePop(); });

async function refreshSidebar() {
  try {
    const h = await api.health();
    lastHealth = h;
    const color = h.provider === 'mock' ? 'var(--warn)' : 'var(--ok)';
    badge0.innerHTML = `<span class="dot" style="background:${color}"></span>${h.provider === 'mock' ? 'MOCK' : 'модель'}`;
    if (!pop.hidden) pop.innerHTML = popHtml(h);
    const badge = document.getElementById('appealBadge');
    badge.hidden = !h.open_appeals;
    badge.textContent = h.open_appeals || '';
  } catch {
    lastHealth = null;
    badge0.innerHTML = '<span class="dot" style="background:var(--bad)"></span>Сервер недоступен';
  }
}

document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
window.addEventListener('hashchange', () => { render(); refreshSidebar(); });
window.addEventListener('cqa:appeals-changed', refreshSidebar);
render();
refreshSidebar();
setInterval(refreshSidebar, 30000);
