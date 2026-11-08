// <cqa-dialog-list> — datasets, filters, batch evaluation and the list of dialogues.
import { api, startBatchConfirmed } from '../api.js';
import { dateTime, esc, icon, num, scoreColor, store, toast } from '../ui.js';

class DialogList extends HTMLElement {
  connectedCallback() {
    this.state = {
      group: store.get('group', ''), lang: store.get('lang', ''), channel: store.get('channel', ''),
      status: store.get('status', ''), q: '', groups: [], items: [], checklists: [], stats: null,
      checklistKey: store.get('checklistKey', ''), job: null, loading: true,
      selected: new Set(store.get('selected', [])), summary: null, showSummary: store.get('showSummary', true),
    };
    this.innerHTML = '<div class="skeleton" style="height:420px"></div>';
    this.load();
  }

  disconnectedCallback() { clearInterval(this._poll); }

  async load() {
    try {
      const [groups, checklists, stats] = await Promise.all([api.groups(), api.checklists(), api.stats()]);
      Object.assign(this.state, { groups, checklists, stats });
      if (this.state.group && !groups.some(g => g.group_id === this.state.group)) this.state.group = '';
      const keys = checklists.map(c => `${c.checklist_id}@${c.latest}`);
      if (!keys.includes(this.state.checklistKey)) this.state.checklistKey = keys[0] || '';
      this.state.items = await api.conversations(this.state.group);
      this.state.summary = await api.summary(this.state.group).catch(() => null);
    } catch (e) { toast(e.message, 'bad'); }
    this.state.loading = false;
    this.render();
  }

  filtered() {
    const s = this.state, q = s.q.trim().toLowerCase();
    return s.items.filter(c =>
      (!s.lang || c.language === s.lang) &&
      (!s.channel || (s.channel === 'call' ? c.is_call : !c.is_call)) &&
      (!s.status || (s.status === 'done' ? c.latest : s.status === 'todo' ? !c.latest : c.latest?.critical_error)) &&
      (!q || c.conversation_id.toLowerCase().includes(q) || (c.preview || '').toLowerCase().includes(q)));
  }

  render() {
    const s = this.state;
    const rows = this.filtered();
    const scored = s.items.filter(c => c.latest && c.latest.total !== null);
    const avg = scored.length ? scored.reduce((a, c) => a + c.latest.total, 0) / scored.length : null;
    const crit = s.items.filter(c => c.latest?.critical_error).length;
    const langs = [...new Set(s.items.map(c => c.language))].filter(Boolean);
    const clOptions = s.checklists.flatMap(c => c.versions.slice().reverse().map(v =>
      `<option value="${esc(c.checklist_id)}@${v.version}" ${s.checklistKey === `${c.checklist_id}@${v.version}` ? 'selected' : ''}>${esc(c.name)} · v${v.version}${v.version === c.latest ? ' (последняя)' : ''}</option>`)).join('');
    const st = s.stats || {};
    const job = s.job;

    this.innerHTML = `
      <div class="page-head">
        <div><h1>Диалоги</h1><div class="sub">Чаты и звонки операторов. Выберите диалог, чтобы оценить его и увидеть обоснование.</div></div>
      </div>

      <div class="stats">
        <div class="card stat"><div class="k">Диалогов</div><div class="v">${s.items.length}</div></div>
        <div class="card stat"><div class="k">Оценено</div><div class="v">${scored.length}<small> / ${s.items.length}</small></div></div>
        <div class="card stat"><div class="k">Средний итог</div><div class="v" style="color:${scoreColor(avg)}">${num(avg, 1)}</div></div>
        <div class="card stat" id="critStat" style="cursor:pointer" title="Показать диалоги с грубой ошибкой"><div class="k">Грубые ошибки</div><div class="v" style="color:${crit ? 'var(--bad)' : 'inherit'}">${crit}</div></div>
        <div class="card stat"><div class="k">Стоимость оценки</div><div class="v">$${num(st.avg_cost_usd ?? 0, 4)}<small> · ${num(st.avg_input_tokens ?? 0, 0)}+${num(st.avg_output_tokens ?? 0, 0)} ток.</small></div></div>
      </div>

      ${this.summaryBlock()}

      <div class="panel-split">
        <div class="card card-pad stack">
          <h3>Наборы диалогов</h3>
          <div class="row">
            <input class="input grow" id="groupId" placeholder="group_id, например DEV" value="">
            <button class="btn primary" id="fetchBtn">${icon('cloud')} Загрузить из API</button>
          </div>
          <div class="row">
            <label class="btn" style="cursor:pointer">${icon('upload')} Загрузить JSON-файл<input type="file" id="fileIn" accept=".json,application/json" hidden></label>
            <span class="small muted">Если API недоступен: сохраните ответ GET в файл.</span>
          </div>
        </div>
        <div class="card card-pad stack">
          <h3>Пакетная оценка</h3>
          <div class="row">
            <select class="select grow" id="clSel">${clOptions}</select>
          </div>
          <div class="row">
            <button class="btn primary" id="batchMissing" ${job && !job.finished ? 'disabled' : ''}>${icon('spark')} Оценить неоценённые</button>
            <button class="btn" id="batchAll" ${job && !job.finished ? 'disabled' : ''}>${icon('refresh')} Переоценить показанные (${rows.length})</button>
            <button class="btn" id="batchSel" ${(job && !job.finished) || !s.selected.size ? 'disabled' : ''}>${icon('refresh')} Переоценить выбранные (${s.selected.size})</button>
          </div>
          ${job ? `<div class="stack" style="gap:6px">
              <div class="progress"><div style="width:${job.total ? Math.round((job.done + job.failed) / job.total * 100) : 100}%"></div></div>
              <div class="small muted">${job.finished ? 'Готово' : '<span class="spinner" style="width:11px;height:11px"></span> Идёт оценка'}: ${job.done} из ${job.total}${job.failed ? `, ошибок: <b style="color:var(--bad)">${job.failed}</b>` : ''}
              ${job.errors?.length ? ` — <span title="${esc(job.errors.map(e => `${e.conversation_id}: ${e.error}`).join('\n'))}">${esc(job.errors[0].error.slice(0, 120))}</span>` : ''}</div></div>` : ''}
        </div>
      </div>

      <div class="card">
        <div class="toolbar">
          <select class="select" data-f="group"><option value="">Все наборы</option>${s.groups.map(g => `<option value="${esc(g.group_id)}" ${s.group === g.group_id ? 'selected' : ''}>${esc(g.group_id)} (${g.count})</option>`).join('')}</select>
          <select class="select" data-f="lang"><option value="">Все языки</option>${langs.map(l => `<option ${s.lang === l ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
          <select class="select" data-f="channel"><option value="">Чаты и звонки</option><option value="chat" ${s.channel === 'chat' ? 'selected' : ''}>Только чаты</option><option value="call" ${s.channel === 'call' ? 'selected' : ''}>Только звонки</option></select>
          <select class="select" data-f="status"><option value="">Любой статус</option><option value="done" ${s.status === 'done' ? 'selected' : ''}>Оценённые</option><option value="todo" ${s.status === 'todo' ? 'selected' : ''}>Без оценки</option><option value="critical" ${s.status === 'critical' ? 'selected' : ''}>С грубой ошибкой</option></select>
          <input class="input" data-f="q" placeholder="Поиск по ID или тексту" value="${esc(s.q)}">
          <span class="grow"></span><span class="small muted">Показано: ${rows.length}</span>
        </div>
        ${s.items.length === 0 ? `<div class="empty"><h3>Диалогов пока нет</h3>Введите group_id (например, <b>DEV</b>) и нажмите «Загрузить из API».</div>` : `
        <div class="table-wrap"><table class="list">
          <thead><tr><th style="width:30px"><input type="checkbox" id="selAll" title="Выбрать все показанные" ${rows.length && rows.every(c => s.selected.has(c.conversation_id)) ? 'checked' : ''}></th><th>Итог</th><th>Диалог</th><th>Канал</th><th>Язык</th><th>Реплик</th><th>Обращение клиента</th><th>Чек-лист</th><th>Оценено</th></tr></thead>
          <tbody id="dlgBody">${rows.map(c => this.row(c)).join('')}</tbody>
        </table></div>`}
      </div>`;
    this.bind();
  }

  summaryBlock() {
    const s = this.state, m = s.summary;
    if (!m || !m.evaluated) return '';
    const pct = (c, k) => (c.percent[k] ?? 0);
    const cell = c => c.type === 'scale'
      ? Object.entries(c.counts).filter(([k]) => k !== 'na').sort((a, b) => b[0] - a[0]).map(([k, n]) => `${k}: ${n}`).join(' · ') + (c.counts.na ? ` · N/A: ${c.counts.na}` : '')
      : c.type === 'critical'
        ? `нарушение: ${c.counts.yes || 0}`
        : `Да ${num(pct(c, 'yes'), 0)}% · Нет ${num(pct(c, 'no'), 0)}% · N/A ${num(pct(c, 'na'), 0)}%`;
    return `<div class="card card-pad stack" style="margin-bottom:16px">
      <div class="row"><h3 class="grow">Сводка по набору${s.group ? ` ${esc(s.group)}` : ''}</h3>
        <span class="small muted">Оценено ${m.evaluated} из ${m.dialogues} · средний итог <b>${num(m.avg_total, 1)}</b></span>
        <button class="btn sm" id="sumToggle">${s.showSummary ? 'Свернуть' : 'Развернуть'}</button></div>
      ${s.showSummary ? `<div class="table-wrap"><table class="list"><thead><tr><th>Критерий</th><th>Ответы (по последней оценке каждого диалога)</th></tr></thead>
        <tbody>${m.criteria.map(c => `<tr><td>${esc(c.title)}</td><td class="small">${cell(c)}</td></tr>`).join('')}</tbody></table></div>
        <div class="small">Диалогов с грубой ошибкой: ${m.critical.length ? m.critical.map(id => `<a href="#/dialog/${encodeURIComponent(id)}" class="mono">${esc(id)}</a>`).join(', ') : '0'}</div>` : ''}
    </div>`;
  }

  row(c) {
    const l = c.latest;
    return `<tr data-id="${esc(c.conversation_id)}">
      <td><input type="checkbox" class="rowSel" data-sel="${esc(c.conversation_id)}" ${this.state.selected.has(c.conversation_id) ? 'checked' : ''}></td>
      <td><div class="score-cell"><cqa-score-ring size="38" value="${l ? l.total ?? '' : ''}" static></cqa-score-ring>
        ${l?.critical_error ? `<span class="flag-red" title="Грубая ошибка">${icon('alert')}</span>` : ''}
        ${l?.appealed ? '<span class="badge" title="Есть решение по апелляции">апелл.</span>' : ''}</div></td>
      <td><b class="mono">${esc(c.conversation_id)}</b></td>
      <td><span class="badge ${c.is_call ? 'call' : 'chat'}">${c.is_call ? 'звонок' : 'чат'}</span></td>
      <td><span class="badge">${esc(c.language || '—')}</span></td>
      <td class="muted">${c.messages} <span class="small">(опер. ${c.operator_messages})</span></td>
      <td><div class="preview">${esc(c.preview)}</div></td>
      <td class="small muted">${l ? `v${l.checklist_version}` : '—'}</td>
      <td class="small muted">${l ? dateTime(l.created_at) : '—'}</td></tr>`;
  }

  bind() {
    const s = this.state;
    this.querySelectorAll('[data-f]').forEach(el => {
      const ev = el.tagName === 'INPUT' ? 'input' : 'change';
      el.addEventListener(ev, async () => {
        s[el.dataset.f] = el.value;
        if (el.dataset.f !== 'q') store.set(el.dataset.f, el.value);
        if (el.dataset.f === 'group') { s.items = await api.conversations(s.group).catch(e => (toast(e.message, 'bad'), [])); }
        const pos = el.selectionStart;
        this.render();
        if (el.dataset.f === 'q') { const inp = this.querySelector('[data-f="q"]'); inp.focus(); inp.setSelectionRange(pos, pos); }
      });
    });
    this.querySelector('#dlgBody')?.addEventListener('change', e => {
      const id = e.target.dataset?.sel;
      if (!id) return;
      e.target.checked ? s.selected.add(id) : s.selected.delete(id);
      store.set('selected', [...s.selected]);
      this.render();
    });
    this.querySelector('#selAll')?.addEventListener('change', e => {
      this.filtered().forEach(c => e.target.checked ? s.selected.add(c.conversation_id) : s.selected.delete(c.conversation_id));
      store.set('selected', [...s.selected]);
      this.render();
    });
    this.querySelector('#critStat')?.addEventListener('click', () => { s.status = 'critical'; store.set('status', 'critical'); this.render(); });
    this.querySelector('#sumToggle')?.addEventListener('click', () => { s.showSummary = !s.showSummary; store.set('showSummary', s.showSummary); this.render(); });
    this.querySelector('#batchSel')?.addEventListener('click', () => this.batch(false, [...s.selected]));
    this.querySelector('#dlgBody')?.addEventListener('click', e => {
      if (e.target.closest('input')) return;
      const tr = e.target.closest('tr[data-id]');
      if (tr) location.hash = `#/dialog/${encodeURIComponent(tr.dataset.id)}`;
    });
    this.querySelector('#clSel')?.addEventListener('change', e => { s.checklistKey = e.target.value; store.set('checklistKey', s.checklistKey); });
    this.querySelector('#fetchBtn').addEventListener('click', () => this.fetchGroup());
    this.querySelector('#groupId').addEventListener('keydown', e => { if (e.key === 'Enter') this.fetchGroup(); });
    this.querySelector('#fileIn').addEventListener('change', e => this.uploadFile(e.target.files[0]));
    this.querySelector('#batchMissing')?.addEventListener('click', () => this.batch(true));
    this.querySelector('#batchAll')?.addEventListener('click', () => this.batch(false));
  }

  async fetchGroup() {
    const g = this.querySelector('#groupId').value.trim();
    if (!g) return toast('Введите group_id', 'bad');
    const btn = this.querySelector('#fetchBtn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Загрузка…';
    try {
      const r = await api.fetchGroup(g);
      toast(`Загружено диалогов: ${r.count} (${r.group_id})`, 'ok');
      this.state.group = r.group_id; store.set('group', r.group_id);
      await this.load();
    } catch (e) { toast(e.message, 'bad'); btn.disabled = false; btn.innerHTML = `${icon('cloud')} Загрузить из API`; }
  }

  async uploadFile(file) {
    if (!file) return;
    const g = this.querySelector('#groupId').value.trim() || file.name.replace(/\.json$/i, '');
    try {
      const payload = JSON.parse(await file.text());
      const r = await api.uploadGroup(g, payload);
      toast(`Загружено из файла: ${r.count} (${r.group_id})`, 'ok');
      this.state.group = r.group_id; store.set('group', r.group_id);
      await this.load();
    } catch (e) { toast(`Файл не загружен: ${e.message}`, 'bad'); }
  }

  async batch(onlyMissing, selectedIds) {
    const [checklist_id, v] = this.state.checklistKey.split('@');
    if (!checklist_id) return toast('Нет чек-листа', 'bad');
    const ids = selectedIds || this.filtered().map(c => c.conversation_id);
    if (!ids.length) return toast(selectedIds ? 'Ничего не выбрано' : 'Нет диалогов в списке', 'bad');
    try {
      const job = await startBatchConfirmed({ checklist_id, version: +v, conversation_ids: ids, only_missing: onlyMissing });
      if (!job) return; // cancelled in the confirmation window
      if (!job.total) return toast('Все показанные диалоги уже оценены этой версией чек-листа', 'ok');
      this.state.job = job;
      this.render();
      this.poll(job.job_id);
    } catch (e) { toast(e.message, 'bad'); }
  }

  poll(jobId) {
    clearInterval(this._poll);
    let last = -1;
    this._poll = setInterval(async () => {
      try {
        const job = await api.job(jobId);
        this.state.job = job;
        if (job.done + job.failed !== last || job.finished) {
          last = job.done + job.failed;
          this.state.items = await api.conversations(this.state.group);
          this.state.stats = await api.stats();
          this.state.summary = await api.summary(this.state.group).catch(() => null);
          this.render();
        }
        if (job.finished) {
          clearInterval(this._poll);
          toast(`Пакет готов: ${job.done} оценено${job.failed ? `, ${job.failed} с ошибкой` : ''}`, job.failed ? 'bad' : 'ok');
        }
      } catch (e) { clearInterval(this._poll); toast(e.message, 'bad'); }
    }, 2000);
  }
}

customElements.define('cqa-dialog-list', DialogList);
