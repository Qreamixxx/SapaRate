// <cqa-checklist-editor> — edit criteria (text, weight, type, N/A, scale), every save = new version,
// then re-apply the new version to a dataset.
import { api } from '../api.js';
import { TYPE_LABEL, esc, icon, modal, num, toast } from '../ui.js';

const clone = o => JSON.parse(JSON.stringify(o));
const DEFAULT_SCALE = [{ value: 10, label: 'Выполнено полностью' }, { value: 5, label: 'Выполнено частично' }, { value: 0, label: 'Не выполнено' }];

class ChecklistEditor extends HTMLElement {
  connectedCallback() {
    this.state = { list: [], id: '', version: null, original: null, draft: null, groups: [], saved: null, job: null };
    this.innerHTML = '<div class="skeleton" style="height:520px"></div>';
    this.init();
  }

  disconnectedCallback() { clearInterval(this._poll); }

  async init() {
    try {
      const [list, groups] = await Promise.all([api.checklists(), api.groups()]);
      Object.assign(this.state, { list, groups });
      if (list.length) await this.open(list[0].checklist_id, list[0].latest);
      else this.innerHTML = '<div class="card empty"><h3>Чек-листов нет</h3></div>';
    } catch (e) { toast(e.message, 'bad'); }
  }

  async open(id, version) {
    const cl = await api.checklist(id, version);
    Object.assign(this.state, { id, version: cl.version, original: cl, draft: clone(cl) });
    this.render();
  }

  latest() { return this.state.list.find(c => c.checklist_id === this.state.id)?.latest || 0; }

  // ---------- render ----------
  render() {
    const s = this.state, d = s.draft;
    const cur = s.list.find(c => c.checklist_id === s.id);
    this.innerHTML = `
      <div class="page-head">
        <div><h1>Чек-лист</h1><div class="sub">Критерии, формулировки, вес, тип ответа и N/A. Каждое сохранение создаёт новую версию — старые оценки остаются привязаны к своей версии.</div></div>
        <div class="row">
          <select class="select" id="clPick">${s.list.map(c => `<option value="${esc(c.checklist_id)}" ${c.checklist_id === s.id ? 'selected' : ''}>${esc(c.name)} (${esc(c.checklist_id)})</option>`).join('')}</select>
          <select class="select" id="verPick">${(cur?.versions || []).slice().reverse().map(v => `<option value="${v.version}" ${v.version === s.version ? 'selected' : ''}>v${v.version} · ${v.criteria} крит.</option>`).join('')}</select>
        </div>
      </div>
      <div class="ed-grid">
        <div class="ed-side" id="side"></div>
        <div>
          <div class="card card-pad" style="margin-bottom:14px">
            <h3 style="margin-bottom:12px">Общие настройки</h3>
            <div class="ed-row-2">
              <label class="field"><span>Название</span><input class="input" data-path="name" value="${esc(d.name)}"></label>
              <div class="ed-row-2" style="margin:0">
                <label class="field"><span>Знаков округления</span><input class="input" type="number" min="0" max="6" data-path="rounding" data-num value="${d.rounding}"></label>
                <label class="field"><span>Максимум итога</span><input class="input" type="number" min="1" data-path="max_total" data-num value="${d.max_total}"></label>
              </div>
            </div>
            <div class="ed-row-2">
              <label class="field"><span>Порог ожидания ответа в чате, сек</span><input class="input" type="number" min="0" data-path="wait_threshold_sec" data-num value="${d.wait_threshold_sec || 0}"></label>
              <label class="check" style="align-self:end;padding-bottom:9px"><input type="checkbox" data-path="critical_zeroes_total" ${d.critical_zeroes_total ? 'checked' : ''}> Грубая ошибка обнуляет итог</label>
            </div>
            <label class="field"><span>Дополнительные правила для модели</span><textarea class="textarea" rows="2" data-path="extra_rules">${esc(d.extra_rules || '')}</textarea></label>
          </div>

          <div class="card card-pad" style="margin-bottom:14px">
            <div class="row" style="margin-bottom:10px"><h3 class="grow">Секции</h3><button class="btn sm" data-action="add-sec">${icon('plus')} Секция</button></div>
            ${d.sections.map((sec, i) => `<div class="sec-edit">
              <input class="input mono" data-path="sections.${i}.id" value="${esc(sec.id)}" title="id секции">
              <input class="input" data-path="sections.${i}.title" value="${esc(sec.title)}">
              <button class="icon-btn" data-action="del-sec" data-i="${i}" title="Удалить секцию">${icon('trash')}</button></div>`).join('')}
          </div>

          <div id="crits">${d.criteria.map((c, i) => this.critCard(c, i)).join('')}</div>
          <button class="btn" data-action="add-crit" style="width:100%;padding:12px">${icon('plus')} Добавить критерий</button>
        </div>
      </div>`;
    this.renderSide();
    this.bind();
  }

  isChanged(c) {
    const o = this.state.original.criteria.find(x => x.id === c.id);
    return !o || JSON.stringify(o) !== JSON.stringify(c);
  }

  critCard(c, i) {
    const d = this.state.draft;
    const sections = d.sections.map(s => `<option value="${esc(s.id)}" ${s.id === c.section ? 'selected' : ''}>${esc(s.title)}</option>`).join('');
    const isCrit = c.type === 'critical';
    return `<div class="card ed-crit ${this.isChanged(c) ? 'changed' : ''}" data-ci="${i}">
      <div class="ed-crit-head">
        <div class="row"><span class="badge mono">${esc(c.id)}</span><b>${esc(c.title || 'Новый критерий')}</b>
          ${this.isChanged(c) ? '<span class="badge" style="color:var(--warn)">изменён</span>' : ''}</div>
        <div class="row" style="gap:6px">
          <button class="icon-btn" data-action="up" data-i="${i}" title="Выше">${icon('up')}</button>
          <button class="icon-btn" data-action="down" data-i="${i}" title="Ниже">${icon('down')}</button>
          <button class="icon-btn" data-action="dup" data-i="${i}" title="Копировать">${icon('copy')}</button>
          <button class="icon-btn" data-action="del-crit" data-i="${i}" title="Удалить" style="color:var(--bad)">${icon('trash')}</button>
        </div>
      </div>
      <div class="ed-row">
        <label class="field"><span>ID</span><input class="input mono" data-path="criteria.${i}.id" value="${esc(c.id)}"></label>
        <label class="field"><span>Название</span><input class="input" data-path="criteria.${i}.title" value="${esc(c.title)}"></label>
        <label class="field"><span>Секция</span><select class="select" data-path="criteria.${i}.section">${sections}</select></label>
        <label class="field"><span>Тип ответа</span><select class="select" data-path="criteria.${i}.type" data-rerender>
          ${Object.entries(TYPE_LABEL).map(([k, l]) => `<option value="${k}" ${c.type === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field"><span>Вес</span><input class="input" type="number" min="0" step="any" data-path="criteria.${i}.weight" data-num value="${c.weight}" ${isCrit ? 'disabled title="Грубая ошибка без веса"' : ''}></label>
      </div>
      <label class="field" style="margin-bottom:10px"><span>${isCrit ? 'Что считается грубой ошибкой' : c.type === 'scale' ? 'Что оценивается (правило для модели, необязательно)' : 'Когда ответ «Да» (правило для модели)'}</span>
        <textarea class="textarea" rows="2" data-path="criteria.${i}.yes_rule">${esc(c.yes_rule || '')}</textarea></label>
      ${c.type === 'scale' ? `<div class="field" style="margin-bottom:10px"><span>Ступени шкалы (баллы считаются как ступень / максимум × вес)</span>
        <div class="scale-rows">${(c.scale || []).map((st, j) => `<div class="scale-row">
          <input class="input" type="number" step="any" data-path="criteria.${i}.scale.${j}.value" data-num value="${st.value}">
          <input class="input" data-path="criteria.${i}.scale.${j}.label" value="${esc(st.label)}">
          <button class="icon-btn" data-action="del-step" data-i="${i}" data-j="${j}">${icon('trash')}</button></div>`).join('')}
          <button class="btn sm" data-action="add-step" data-i="${i}" style="align-self:flex-start">${icon('plus')} Ступень</button></div></div>` : ''}
      ${isCrit ? '' : `<label class="check" style="margin-bottom:8px"><input type="checkbox" data-path="criteria.${i}.na_allowed" data-rerender ${c.na_allowed ? 'checked' : ''}> Разрешён N/A</label>`}
      ${c.na_allowed && !isCrit ? `<label class="field" style="margin-bottom:10px"><span>Когда N/A</span>
        <textarea class="textarea" rows="2" data-path="criteria.${i}.na_rule">${esc(c.na_rule || '')}</textarea></label>` : ''}
      <label class="field"><span>Примечание (необязательно)</span><textarea class="textarea" rows="1" data-path="criteria.${i}.note">${esc(c.note || '')}</textarea></label>
    </div>`;
  }

  renderSide() {
    const s = this.state, d = s.draft;
    const weighted = d.criteria.filter(c => c.type !== 'critical' && +c.weight > 0);
    const sum = weighted.reduce((a, c) => a + (+c.weight || 0), 0);
    const dirty = JSON.stringify(stripMeta(d)) !== JSON.stringify(stripMeta(s.original));
    const job = s.job;
    this.querySelector('#side').innerHTML = `
      <div class="card card-pad stack">
        <h3>Версия</h3>
        <div class="small muted">Открыта <b>v${s.version}</b>${s.version !== this.latest() ? ` (последняя — v${this.latest()})` : ''}. Сохранение создаст <b>v${this.latest() + 1}</b>.</div>
        ${dirty ? '<div class="alert info small">Есть несохранённые изменения</div>' : ''}
        <button class="btn primary" data-action="save" ${dirty ? '' : 'disabled'}>Сохранить как v${this.latest() + 1}</button>
        <div class="row"><button class="btn sm grow" data-action="reset" ${dirty ? '' : 'disabled'}>Сбросить</button>
          <button class="btn sm grow" data-action="save-new">Как новый чек-лист</button></div>
      </div>
      ${s.saved ? `<div class="card card-pad stack saved-panel">
        <h3>Версия v${s.saved.version} сохранена</h3>
        <div class="small">Примените её к диалогам набора — старые оценки сохранятся в истории.</div>
        <div class="row"><select class="select grow" id="applyGroup">${s.groups.map(g => `<option value="${esc(g.group_id)}">${esc(g.group_id)} (${g.count})</option>`).join('')}</select>
          <button class="btn primary" data-action="apply" ${job && !job.finished ? 'disabled' : ''} title="Весь выбранный набор">Переоценить набор</button></div>
        <div class="row"><button class="btn grow" data-action="apply-sel" ${job && !job.finished || !this.selectedIds().length ? 'disabled' : ''}>Переоценить выбранные (${this.selectedIds().length})</button>
          <a class="btn grow" href="#/compare">Сравнение версий →</a></div>
        <div class="small muted">Выбранные — галочки в списке «Диалоги».</div>
        ${job ? `<div class="progress"><div style="width:${job.total ? Math.round((job.done + job.failed) / job.total * 100) : 100}%"></div></div>
          <div class="small">${job.finished ? 'Готово' : 'Идёт оценка'}: ${job.done} из ${job.total}${job.failed ? `, ошибок ${job.failed}` : ''}. <a href="#/dialogs">Открыть диалоги →</a></div>` : ''}
      </div>` : ''}
      <div class="card card-pad stack">
        <div class="row"><h3 class="grow">Веса</h3><span class="small muted">сумма ${num(sum)}</span></div>
        <div class="weights">${weighted.map(c => `<div class="w"><span class="mono">${esc(c.id)}</span>
          <div class="bar"><div style="width:${sum ? (+c.weight / sum * 100) : 0}%"></div></div>
          <span class="num">${num(sum ? +c.weight / sum * (+d.max_total || 100) : 0, 1)}</span></div>`).join('')}</div>
        <div class="small muted">Справа — доля в итоге из ${num(d.max_total, 0)}. При N/A вес критерия перераспределяется между остальными пропорционально.</div>
      </div>`;
  }

  // ---------- events ----------
  bind() {
    this.querySelector('#clPick').addEventListener('change', e => {
      const c = this.state.list.find(x => x.checklist_id === e.target.value);
      this.state.saved = null;
      this.open(c.checklist_id, c.latest);
    });
    this.querySelector('#verPick').addEventListener('change', e => this.open(this.state.id, +e.target.value));
    this.addEventListener('input', this._onInput || (this._onInput = e => this.onInput(e)));
    this.addEventListener('change', this._onChange || (this._onChange = e => this.onChange(e)));
    this.addEventListener('click', this._onClick || (this._onClick = e => this.onClick(e)));
  }

  setPath(path, value) {
    const keys = path.split('.');
    let o = this.state.draft;
    keys.slice(0, -1).forEach(k => { o = o[k]; });
    o[keys[keys.length - 1]] = value;
  }

  readInput(el) {
    if (el.type === 'checkbox') return el.checked;
    if (el.hasAttribute('data-num')) return el.value === '' ? 0 : +el.value;
    return el.value;
  }

  onInput(e) {
    const el = e.target.closest('[data-path]');
    if (!el || el.type === 'checkbox' || el.tagName === 'SELECT') return;
    this.setPath(el.dataset.path, this.readInput(el));
    const card = el.closest('[data-ci]');
    if (card) {
      const c = this.state.draft.criteria[+card.dataset.ci];
      card.classList.toggle('changed', this.isChanged(c));
      if (el.dataset.path.endsWith('.title')) card.querySelector('.ed-crit-head b').textContent = c.title || 'Новый критерий';
    }
    this.renderSide();
  }

  onChange(e) {
    const el = e.target.closest('[data-path]');
    if (!el || !(el.type === 'checkbox' || el.tagName === 'SELECT')) return;
    const value = this.readInput(el);
    this.setPath(el.dataset.path, value);
    const m = el.dataset.path.match(/^criteria\.(\d+)\.type$/);
    if (m) {
      const c = this.state.draft.criteria[+m[1]];
      if (value === 'scale' && !(c.scale || []).length) c.scale = clone(DEFAULT_SCALE);
      if (value === 'critical') { c.weight = 0; c.na_allowed = false; }
    }
    if (el.hasAttribute('data-rerender')) this.rerenderKeepScroll(); else this.renderSide();
  }

  rerenderKeepScroll() {
    const y = window.scrollY;
    this.render();
    window.scrollTo(0, y);
  }

  async onClick(e) {
    const b = e.target.closest('[data-action]');
    if (!b) return;
    const d = this.state.draft, i = +b.dataset.i, j = +b.dataset.j;
    switch (b.dataset.action) {
      case 'add-crit': {
        const n = d.criteria.length + 1;
        let id = `c${String(n).padStart(2, '0')}`;
        while (d.criteria.some(c => c.id === id)) id += '_new';
        d.criteria.push({ id, section: d.sections[0]?.id || '', title: '', type: 'binary', weight: 10, na_allowed: false, yes_rule: '', na_rule: '', note: '' });
        this.rerenderKeepScroll();
        this.querySelector(`[data-ci="${d.criteria.length - 1}"] [data-path$=".title"]`)?.focus();
        return;
      }
      case 'del-crit': if (confirmDelete(d.criteria[i])) { d.criteria.splice(i, 1); this.rerenderKeepScroll(); } return;
      case 'dup': { const c = clone(d.criteria[i]); c.id += '_copy'; d.criteria.splice(i + 1, 0, c); this.rerenderKeepScroll(); return; }
      case 'up': if (i > 0) { [d.criteria[i - 1], d.criteria[i]] = [d.criteria[i], d.criteria[i - 1]]; this.rerenderKeepScroll(); } return;
      case 'down': if (i < d.criteria.length - 1) { [d.criteria[i + 1], d.criteria[i]] = [d.criteria[i], d.criteria[i + 1]]; this.rerenderKeepScroll(); } return;
      case 'add-step': d.criteria[i].scale.push({ value: 0, label: '' }); this.rerenderKeepScroll(); return;
      case 'del-step': d.criteria[i].scale.splice(j, 1); this.rerenderKeepScroll(); return;
      case 'add-sec': d.sections.push({ id: `s${d.sections.length + 1}`, title: 'Новая секция' }); this.rerenderKeepScroll(); return;
      case 'del-sec': {
        const used = d.criteria.some(c => c.section === d.sections[i].id);
        if (used) return toast('В секции есть критерии — сначала перенесите их', 'bad');
        d.sections.splice(i, 1); this.rerenderKeepScroll(); return;
      }
      case 'reset': this.state.draft = clone(this.state.original); this.rerenderKeepScroll(); return;
      case 'save': return this.save(this.state.id);
      case 'save-new': {
        const r = await modal({ title: 'Новый чек-лист', text: 'Текущие настройки сохранятся как отдельный чек-лист (v1).',
          fields: [{ name: 'id', label: 'ID (латиница, без пробелов)', placeholder: 'calls-quality' }, { name: 'name', label: 'Название', placeholder: 'Чек-лист звонков' }], okLabel: 'Создать' });
        if (r) { this.state.draft.name = r.name || this.state.draft.name; return this.save(r.id); }
        return;
      }
      case 'apply': return this.apply();
      case 'apply-sel': return this.apply(this.selectedIds());
      default:
    }
  }

  async save(id) {
    try {
      const saved = await api.saveChecklist(id, stripMeta(this.state.draft));
      this.state.list = await api.checklists();
      this.state.saved = saved;
      this.state.job = null;
      toast(`Сохранено: ${saved.name} v${saved.version}`, 'ok');
      await this.open(saved.checklist_id, saved.version);
    } catch (e) { toast(e.message, 'bad', 8000); }
  }

  selectedIds() { try { return JSON.parse(localStorage.getItem('cqa:selected') || '[]'); } catch { return []; } }

  async apply(ids) {
    const s = this.state;
    const group_id = this.querySelector('#applyGroup')?.value;
    try {
      const job = await api.batch({ checklist_id: s.saved.checklist_id, version: s.saved.version, group_id, only_missing: true, ...(ids ? { conversation_ids: ids } : {}) });
      s.job = job;
      this.renderSide();
      if (!job.total) return toast('Все диалоги набора уже оценены этой версией', 'ok');
      clearInterval(this._poll);
      this._poll = setInterval(async () => {
        try {
          s.job = await api.job(job.job_id);
          this.renderSide();
          if (s.job.finished) { clearInterval(this._poll); toast(`Переоценено: ${s.job.done}${s.job.failed ? `, ошибок ${s.job.failed}` : ''}`, s.job.failed ? 'bad' : 'ok'); }
        } catch (e) { clearInterval(this._poll); toast(e.message, 'bad'); }
      }, 2000);
    } catch (e) { toast(e.message, 'bad'); }
  }
}

function stripMeta(cl) {
  const { checklist_id, version, created_at, ...rest } = cl; // eslint-disable-line no-unused-vars
  return rest;
}

function confirmDelete(c) {
  return window.confirm(`Удалить критерий ${c.id} «${c.title}»? Изменение применится после сохранения новой версии.`);
}

customElements.define('cqa-checklist-editor', ChecklistEditor);
