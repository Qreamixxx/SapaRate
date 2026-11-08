// Small shared helpers: escaping, number formatting, colors, icons, toasts, modal.

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const num = (v, digits = 2) => v === null || v === undefined || Number.isNaN(+v) ? '—'
  : (+v).toLocaleString('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: 0 });

// 0 → red, 50 → amber, 100 → green
export function scoreColor(v) {
  if (v === null || v === undefined || Number.isNaN(+v)) return 'var(--muted)';
  const p = Math.max(0, Math.min(100, +v)) / 100;
  const hue = p * 128;
  const light = 44 - Math.sin(p * Math.PI) * 4;
  return `hsl(${hue.toFixed(1)} 72% ${light.toFixed(1)}%)`;
}

export const clock = sec => {
  if (sec === null || sec === undefined) return '';
  const s = Math.max(0, Math.round(sec));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

export const dateTime = iso => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
};

export const SPEAKER = { client: 'Клиент', operator: 'Оператор', bot: 'Бот', system: 'Система' };
export const TYPE_LABEL = { binary: 'Да / Нет', scale: 'Шкала', critical: 'Грубая ошибка' };

export function msgTime(conv, t) {
  return conv.is_call ? clock(t.offset_sec) : (t.timestamp || '');
}

// Answer chip for a scored row
export function answerChip(row) {
  const a = row.answer;
  if (row.type === 'critical') {
    return a === 'yes' ? '<span class="chip violation">Нарушение</span>' : '<span class="chip clean">Нет нарушений</span>';
  }
  if (a === 'na') return '<span class="chip na">N/A</span>';
  if (row.type === 'scale') {
    const cls = +row.value >= +row.scale_max ? 'full' : +row.value === 0 ? 'zero' : '';
    return `<span class="chip score ${cls}">${num(row.value)} из ${num(row.scale_max)}</span>`;
  }
  return a === 'yes' ? '<span class="chip yes">Да</span>' : '<span class="chip no">Нет</span>';
}

export function answerText(type, answer, value) {
  if (type === 'critical') return answer === 'yes' ? 'Нарушение' : 'Нет нарушений';
  if (answer === 'na') return 'N/A';
  if (type === 'scale') return `ступень ${num(value)}`;
  return answer === 'yes' ? 'Да' : answer === 'no' ? 'Нет' : '—';
}

export function rowStatusClass(row) {
  if (row.type === 'critical') return row.answer === 'yes' ? 'st-violation' : 'st-clean';
  if (row.answer === 'na') return 'st-na';
  if (row.type === 'scale') return `st-score ${+row.value >= +row.scale_max ? 'full' : +row.value === 0 ? 'zero' : ''}`;
  return row.answer === 'yes' ? 'st-yes' : 'st-no';
}

const ICONS = {
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  flag: '<path d="M4 22V4a1 1 0 0 1 1-1h11l-1.5 4L16 11H5"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  play: '<path d="M6 4l14 8-14 8z" fill="currentColor" stroke="none"/>',
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 18l-6-6 6-6"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/>',
  upload: '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>',
  cloud: '<path d="M7 18a5 5 0 1 1 .9-9.9A6 6 0 0 1 19 10a4 4 0 0 1-1 8z"/>',
  alert: '<path d="M12 9v4M12 17h.01M10.3 3.9L2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
};
export const icon = name => `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;

export function toast(message, kind = 'info', ms = 3800) {
  const box = document.getElementById('toasts');
  if (!box) return;
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// Simple modal. fields: [{name, label, type:'textarea'|'text', placeholder}] → resolves with values or null
export function modal({ title, text = '', fields = [], okLabel = 'Отправить' }) {
  return new Promise(resolve => {
    const back = document.createElement('div');
    back.className = 'modal-back';
    back.innerHTML = `<form class="modal card">
      <h3>${esc(title)}</h3>
      ${text ? `<div class="muted">${text}</div>` : ''}
      ${fields.map(f => `<label class="field"><span>${esc(f.label)}</span>
        ${f.type === 'textarea'
          ? `<textarea class="textarea" name="${f.name}" rows="4" placeholder="${esc(f.placeholder || '')}" required></textarea>`
          : `<input class="input" name="${f.name}" placeholder="${esc(f.placeholder || '')}" required>`}</label>`).join('')}
      <div class="modal-actions">
        <button type="button" class="btn" data-cancel>Отмена</button>
        <button type="submit" class="btn primary">${esc(okLabel)}</button>
      </div></form>`;
    const close = v => { back.remove(); resolve(v); };
    back.addEventListener('click', e => { if (e.target === back || e.target.hasAttribute('data-cancel')) close(null); });
    back.querySelector('form').addEventListener('submit', e => {
      e.preventDefault();
      const out = {};
      fields.forEach(f => { out[f.name] = back.querySelector(`[name="${f.name}"]`).value.trim(); });
      close(out);
    });
    document.body.appendChild(back);
    back.querySelector('textarea, input')?.focus();
  });
}

// Replies are stored 0-based, shown 1-based (like evidence_turns in results.json): [10] -> [11] in a text.
export const shiftRefs = text => String(text ?? '').replace(/\[(\d+)\]/g, (_, n) => `[${+n + 1}]`);

export const store = {
  get(key, fallback) { try { const v = localStorage.getItem('cqa:' + key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem('cqa:' + key, JSON.stringify(value)); } catch { /* storage unavailable */ } },
};

export const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }));
