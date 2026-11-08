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

const routes = {
  dialogs: () => '<cqa-dialog-list></cqa-dialog-list>',
  dialog: id => `<cqa-evaluation-view conversation-id="${esc(id)}"></cqa-evaluation-view>`,
  appeals: () => '<cqa-appeals-view></cqa-appeals-view>',
  checklist: () => '<cqa-checklist-editor></cqa-checklist-editor>',
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

async function refreshSidebar() {
  try {
    const h = await api.health();
    const color = h.provider === 'mock' ? 'var(--warn)' : '#4fd1a0';
    const tip = h.provider === 'mock' ? 'MOCK-режим: нет ключа модели, оценки-заглушки' : `Цепочка: ${h.chain.join(' → ')}\nМодели: ${h.model}\nОценок в базе: ${h.evaluations}`;
    const info = document.getElementById('providerInfo');
    info.title = tip;
    info.innerHTML = `<span class="dot" style="background:${color}"></span>${h.provider === 'mock' ? 'MOCK' : 'модель'}`;
    const badge = document.getElementById('appealBadge');
    badge.hidden = !h.open_appeals;
    badge.textContent = h.open_appeals || '';
  } catch {
    document.getElementById('providerInfo').innerHTML = '<span class="dot" style="background:#e8574a"></span>Сервер недоступен';
  }
}

document.querySelectorAll('[data-icon]').forEach(el => { el.innerHTML = icon(el.dataset.icon); });
window.addEventListener('hashchange', () => { render(); refreshSidebar(); });
window.addEventListener('cqa:appeals-changed', refreshSidebar);
render();
refreshSidebar();
setInterval(refreshSidebar, 30000);
