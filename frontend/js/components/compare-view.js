// <cqa-compare-view> — compare two checklist versions: totals per dialogue, difference, changed criteria.
import { api } from '../api.js';
import { answerText, esc, num, scoreColor, store, toast } from '../ui.js';

class CompareView extends HTMLElement {
  connectedCallback() {
    this.state = { lists: [], groups: [], id: '', a: 0, b: 0, group: store.get('group', ''), data: null, loading: false, onlyChanged: true };
    this.innerHTML = '<div class="skeleton" style="height:300px"></div>';
    this.init();
  }

  async init() {
    try {
      const [lists, groups] = await Promise.all([api.checklists(), api.groups()]);
      const s = this.state;
      Object.assign(s, { lists, groups });
      s.id = lists[0]?.checklist_id || '';
      const vs = (lists[0]?.versions || []).map(v => v.version);
      s.b = vs[vs.length - 1] || 0;
      s.a = vs.length > 1 ? vs[vs.length - 2] : s.b;
      if (s.group && !groups.some(g => g.group_id === s.group)) s.group = '';
      this.render();
      if (vs.length > 1) this.run();
    } catch (e) { toast(e.message, 'bad'); }
  }

  async run() {
    const s = this.state;
    s.loading = true; this.render();
    try { s.data = await api.compare(s.id, s.a, s.b, s.group); } catch (e) { toast(e.message, 'bad'); s.data = null; }
    s.loading = false; this.render();
  }

  render() {
    const s = this.state, cl = s.lists.find(c => c.checklist_id === s.id);
    const vopts = sel => (cl?.versions || []).map(v => `<option value="${v.version}" ${v.version === sel ? 'selected' : ''}>v${v.version}</option>`).join('');
    const d = s.data;
    let body = '';
    if (s.loading) body = '<div class="skeleton" style="height:200px"></div>';
    else if (d) {
      const m = d.summary;
      const rows = d.rows.filter(r => !s.onlyChanged || r.changed.length || r.diff).sort((x, y) => Math.abs(y.diff || 0) - Math.abs(x.diff || 0));
      const delta = m.avg_a !== null && m.avg_b !== null ? m.avg_b - m.avg_a : null;
      body = `<div class="stats">
          <div class="card stat"><div class="k">Сравнено диалогов</div><div class="v">${m.compared}</div></div>
          <div class="card stat"><div class="k">Изменились</div><div class="v">${m.changed_dialogues}</div></div>
          <div class="card stat"><div class="k">Средний итог v${d.a}</div><div class="v" style="color:${scoreColor(m.avg_a)}">${num(m.avg_a, 1)}</div></div>
          <div class="card stat"><div class="k">Средний итог v${d.b}</div><div class="v" style="color:${scoreColor(m.avg_b)}">${num(m.avg_b, 1)}</div></div>
          <div class="card stat"><div class="k">Разница</div><div class="v">${delta === null ? '—' : (delta > 0 ? '+' : '') + num(delta, 2)}</div></div>
        </div>
        ${m.compared === 0 ? `<div class="alert info">Нет диалогов, оценённых обеими версиями. Оцените диалоги версией v${d.b} (Диалоги → «Переоценить выбранные»).
          Оценено только v${d.a}: ${m.only_in_a}, только v${d.b}: ${m.only_in_b}.</div>` : `
        <div class="card">
          <div class="toolbar"><label class="small"><input type="checkbox" id="onlyCh" ${s.onlyChanged ? 'checked' : ''}> только изменившиеся</label>
            <span class="grow"></span><span class="small muted">Показано: ${rows.length}</span></div>
          <div class="table-wrap"><table class="list"><thead><tr><th>Диалог</th><th>Итог v${d.a}</th><th>Итог v${d.b}</th><th>Разница</th><th>Что изменилось</th></tr></thead>
          <tbody>${rows.map(r => `<tr data-id="${esc(r.conversation_id)}" style="cursor:pointer">
            <td><b class="mono">${esc(r.conversation_id)}</b></td>
            <td>${num(r.total_a)}${r.critical_a ? ' <span class="flag-red">!</span>' : ''}</td>
            <td>${num(r.total_b)}${r.critical_b ? ' <span class="flag-red">!</span>' : ''}</td>
            <td><b style="color:${r.diff > 0 ? 'var(--good, #1e9e6a)' : r.diff < 0 ? 'var(--bad)' : 'inherit'}">${r.diff === null ? '—' : (r.diff > 0 ? '+' : '') + num(r.diff)}</b></td>
            <td class="small">${r.changed.length ? r.changed.map(c => `${esc(c.title)}: <b>${esc(this.val(c.before))}</b> → <b>${esc(this.val(c.after))}</b>`).join('<br>') : '<span class="muted">без изменений</span>'}</td></tr>`).join('')}</tbody></table></div>
        </div>`}`;
    }
    this.innerHTML = `
      <div class="page-head"><div><h1>Сравнение версий</h1>
        <div class="sub">Выберите две версии чек-листа: таблица покажет, как изменились итог и ответы по критериям у диалогов, оценённых обеими версиями. Старые оценки не удаляются.</div></div></div>
      <div class="card card-pad row" style="margin-bottom:16px;gap:12px;flex-wrap:wrap">
        <label class="field"><span>Версия «до»</span><select class="select" id="cmpA">${vopts(s.a)}</select></label>
        <label class="field"><span>Версия «после»</span><select class="select" id="cmpB">${vopts(s.b)}</select></label>
        <label class="field"><span>Набор</span><select class="select" id="cmpG"><option value="">Все наборы</option>${s.groups.map(g => `<option value="${esc(g.group_id)}" ${s.group === g.group_id ? 'selected' : ''}>${esc(g.group_id)} (${g.count})</option>`).join('')}</select></label>
        <button class="btn primary" id="cmpGo">Сравнить</button>
      </div>${body}`;
    this.querySelector('#cmpA').addEventListener('change', e => { s.a = +e.target.value; });
    this.querySelector('#cmpB').addEventListener('change', e => { s.b = +e.target.value; });
    this.querySelector('#cmpG').addEventListener('change', e => { s.group = e.target.value; });
    this.querySelector('#cmpGo').addEventListener('click', () => this.run());
    this.querySelector('#onlyCh')?.addEventListener('change', e => { s.onlyChanged = e.target.checked; this.render(); });
    this.querySelector('tbody')?.addEventListener('click', e => {
      const tr = e.target.closest('tr[data-id]');
      if (tr) location.hash = `#/dialog/${encodeURIComponent(tr.dataset.id)}`;
    });
  }

  val(x) {
    if (x.answer === 'na') return 'N/A';
    if (x.answer === 'score') return String(x.value);
    return { yes: 'Да', no: 'Нет' }[x.answer] || String(x.answer ?? '—');
  }
}

customElements.define('cqa-compare-view', CompareView);
