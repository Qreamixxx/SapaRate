// <cqa-dialog-list> — datasets, filters, batch evaluation and the list of dialogues.
import { api, startBatchConfirmed } from '../api.js';
import { shiftRefs, dateTime, esc, icon, num, scoreColor, store, toast } from '../ui.js';

class DialogList extends HTMLElement {
  connectedCallback() {
    this.state = {
      group: store.get('group', ''), lang: store.get('lang', ''), channel: store.get('channel', ''),
      status: store.get('status', ''), q: '', groups: [], items: [], checklists: [], stats: null,
      checklistKey: store.get('checklistKey', ''), job: null, loading: true,
      selected: new Set(store.get('selected', [])), summary: null, showSummary: store.get('sumOpen', false), showLoad: false,
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

  // "Needs attention": gross errors first, then the lowest totals (from saved evaluations of the shown set)
  async loadAttention() {
    const s = this.state;
    const evald = s.items.filter(c => c.latest && c.latest.total !== null);
    const bad = evald.filter(c => c.latest.critical_error || c.latest.total < 70)
      .sort((a, b) => (Number(b.latest.critical_error) - Number(a.latest.critical_error)) || (a.latest.total - b.latest.total)).slice(0, 5);
    const cards = await Promise.all(bad.map(async c => {
      let reason = '';
      try {
        const ev = await api.evaluation(c.latest.evaluation_id);
        const items = ev.result.items;
        if (c.latest.critical_error) {
          const v = items.find(i => i.status === 'violation');
          const t = shiftRefs(((v && v.explanation) || '').replace(/\s+/g, ' ').trim());
          reason = t.length > 90 ? t.slice(0, 87) + '…' : t;
        } else {
          const sc = items.filter(i => i.status === 'scored' && i.max_points > 0 && i.points < i.max_points - 0.0001);
          if (sc.length) reason = sc.reduce((m, i) => (i.points / i.max_points < m.points / m.max_points ? i : m), sc[0]).title;
        }
      } catch { /* the card is still shown without a reason */ }
      return { id: c.conversation_id, total: c.latest.total, critical: !!c.latest.critical_error, reason };
    }));
    s.attention = { cards, evaluated: evald.length };
    this.render();
  }

  attentionBlock() {
    const a = this.state.attention;
    if (!a || !a.evaluated) return '';
    if (!a.cards.length) return '<div class="attn-ok">Все диалоги без замечаний</div>';
    return `<div class="attn"><div class="attn-t">Требуют внимания</div><div class="attn-row">${a.cards.map(c => `
      <a class="attn-card ${c.critical ? 'crit' : ''}" href="#/dialog/${encodeURIComponent(c.id)}" data-attn="${esc(c.id)}">
        <div class="attn-top"><span class="mono">${esc(c.id)}</span><span class="attn-score" style="color:${scoreColor(c.total)}">${num(c.total, 0)}</span></div>
        <div class="attn-tag">${c.critical ? 'Грубая ошибка' : 'Низкий итог'}</div>
        <div class="attn-reason">${esc(c.reason || '—')}</div></a>`).join('')}</div></div>`;
  }

  render() {
    const s = this.state;
    const attnKey = `${s.group}|${s.items.length}|${s.items.map(c => (c.latest && c.latest.evaluation_id) || '').join(',')}`;
    if (this._attnKey !== attnKey) { this._attnKey = attnKey; this.loadAttention(); }
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
      <div class="searchbar"><input class="input" data-f="q" placeholder="Поиск по ID диалога или тексту обращения" value="${esc(s.q)}" autocomplete="off"></div>

      <div class="topbox">
      <div class="toprow">
      <div class="sumline">
        <span>Диалогов <b>${s.items.length}</b></span><span class="sep">·</span>
        <span>Средний итог <b style="color:${scoreColor(avg)}">${num(avg, 1)}</b></span><span class="sep">·</span>
        <button class="linkbtn" id="critStat" title="Показать диалоги с грубой ошибкой">Грубых ошибок <b style="color:${crit ? 'var(--bad)' : 'inherit'}">${crit}</b></button><span class="sep">·</span>
        <button class="linkbtn" id="sumToggle">${s.showSummary ? 'Свернуть ▴' : 'Подробнее ▾'}</button>
      </div>
      <button class="linkbtn" id="loadToggle">Загрузка и оценка ${(s.showLoad || (job && !job.finished)) ? '▾' : '▸'}</button>
      </div>

      ${this.summaryBlock()}

      <div class="loadbox">
        
        <div id="loadBody" ${(s.showLoad || (job && !job.finished)) ? '' : 'hidden'}>
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
        </div>
      </div>
      </div>

      ${this.attentionBlock()}

      <div class="card">
        <div class="toolbar">
          <select class="select" data-f="group"><option value="">Все наборы</option>${s.groups.map(g => `<option value="${esc(g.group_id)}" ${s.group === g.group_id ? 'selected' : ''}>${esc(g.group_id)} (${g.count})</option>`).join('')}</select>
          <select class="select" data-f="lang"><option value="">Все языки</option>${langs.map(l => `<option ${s.lang === l ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>
          <select class="select" data-f="channel"><option value="">Чаты и звонки</option><option value="chat" ${s.channel === 'chat' ? 'selected' : ''}>Только чаты</option><option value="call" ${s.channel === 'call' ? 'selected' : ''}>Только звонки</option></select>
          <select class="select" data-f="status"><option value="">Любой статус</option><option value="done" ${s.status === 'done' ? 'selected' : ''}>Оценённые</option><option value="todo" ${s.status === 'todo' ? 'selected' : ''}>Без оценки</option><option value="critical" ${s.status === 'critical' ? 'selected' : ''}>С грубой ошибкой</option></select>
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
    if (!s.showSummary) return '';
    if (!m || !m.evaluated) return '<div class="card card-pad small muted" style="margin-bottom:16px">Оценённых диалогов пока нет.</div>';
    const pct = (c, k) => (c.percent[k] ?? 0);
    const cell = c => c.type === 'scale'
      ? Object.entries(c.counts).filter(([k]) => k !== 'na').sort((a, b) => b[0] - a[0]).map(([k, n]) => `${k}: ${n}`).join(' · ') + (c.counts.na ? ` · N/A: ${c.counts.na}` : '')
      : c.type === 'critical'
        ? `нарушение: ${c.counts.yes || 0}`
        : `Да ${num(pct(c, 'yes'), 0)}% · Нет ${num(pct(c, 'no'), 0)}% · N/A ${num(pct(c, 'na'), 0)}%`;
    const st = s.stats || {};
    return `<div class="card card-pad stack" style="margin-bottom:16px">
      <div class="small muted">Оценено ${m.evaluated} из ${m.dialogues} · стоимость оценки $${num(st.avg_cost_usd ?? 0, 4)} · токены ${num(st.avg_input_tokens ?? 0, 0)}+${num(st.avg_output_tokens ?? 0, 0)}</div>
      <div class="table-wrap"><table class="list"><thead><tr><th>Критерий</th><th>Ответы (по последней оценке каждого диалога)</th></tr></thead>
        <tbody>${m.criteria.map(c => `<tr><td>${esc(c.title)}</td><td class="small">${cell(c)}</td></tr>`).join('')}</tbody></table></div>
      <div class="small">Диалогов с грубой ошибкой: ${m.critical.length ? m.critical.map(id => `<a href="#/dialog/${encodeURIComponent(id)}" class="mono">${esc(id)}</a>`).join(', ') : '0'}</div>
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
    this.querySelector('#sumToggle')?.addEventListener('click', () => { s.showSummary = !s.showSummary; store.set('sumOpen', s.showSummary); this.render(); });
    this.querySelector('#loadToggle')?.addEventListener('click', () => { s.showLoad = !s.showLoad; this.render(); });
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
