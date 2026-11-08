import { modal } from './ui.js';

// All requests to the backend go through here. For Dynamics 365 embedding set window.CQA_API_BASE.
const BASE = () => (window.CQA_API_BASE || '').replace(/\/$/, '');

async function req(method, path, body) {
  const res = await fetch(BASE() + path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg).join('; ') : `Ошибка ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

const q = params => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));
  return s.toString() ? `?${s}` : '';
};

export const api = {
  sandbox: text => req('POST', '/api/sandbox', { text }),
  health: () => req('GET', '/api/health'),
  stats: () => req('GET', '/api/stats'),
  groups: () => req('GET', '/api/groups'),
  fetchGroup: group_id => req('POST', '/api/groups/fetch', { group_id }),
  uploadGroup: (group_id, payload) => req('POST', '/api/groups/upload', { group_id, payload }),
  conversations: group_id => req('GET', '/api/conversations' + q({ group_id })),
  conversation: id => req('GET', `/api/conversations/${encodeURIComponent(id)}`),
  audio: id => req('GET', `/api/conversations/${encodeURIComponent(id)}/audio`),
  evaluationsFor: id => req('GET', `/api/conversations/${encodeURIComponent(id)}/evaluations`),
  evaluation: id => req('GET', `/api/evaluations/${encodeURIComponent(id)}`),
  evaluate: body => req('POST', '/api/evaluations', body),
  batch: body => req('POST', '/api/batches', body),
  job: id => req('GET', `/api/batches/${encodeURIComponent(id)}`),
  checklists: () => req('GET', '/api/checklists'),
  checklist: (id, version) => req('GET', `/api/checklists/${encodeURIComponent(id)}` + q({ version })),
  saveChecklist: (checklist_id, data) => req('POST', '/api/checklists', { checklist_id, data }),
  summary: group_id => req('GET', '/api/summary' + q({ group_id })),
  compare: (checklist_id, a, b, group_id) => req('GET', '/api/compare' + q({ checklist_id, a, b, group_id })),
  appeals: (status, evaluation_id) => req('GET', '/api/appeals' + q({ status, evaluation_id })),
  createAppeal: body => req('POST', '/api/appeals', body),
  decide: (id, body) => req('POST', `/api/appeals/${encodeURIComponent(id)}/decision`, body),
};

// Starts a batch; more than 3 model requests need a confirmation. Returns the job, or null if the user cancelled.
export async function startBatchConfirmed(body) {
  const plan = await api.batch({ ...body, dry_run: true });
  if (!plan.total) return { total: 0, finished: true, done: 0, failed: 0, errors: [] };
  if (plan.total > 3) {
    const ok = await modal({ title: 'Подтвердите запуск', text: `Будет <b>${plan.total}</b> запросов к модели. Продолжить?`, fields: [], okLabel: 'Продолжить' });
    if (!ok) return null;
  }
  return api.batch(body);
}
