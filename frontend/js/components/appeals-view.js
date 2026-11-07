// <cqa-appeals-view> — reviewer screen: disputed score, comment, dialogue fragment, decision + reason.
import { api } from '../api.js';
import { SPEAKER, answerChip, answerText, dateTime, emit, esc, icon, msgTime, num, scoreColor, toast } from '../ui.js';

class AppealsView extends HTMLElement {
  connectedCallback() {
    this.state = { tab: 'open', items: [], forms: {} };
    this.innerHTML = '<div class="skeleton" style="height:360px"></div>';
    this.load();
  }

  async load() {
    try {
      this.state.items = await api.appeals(this.state.tab === 'open' ? 'open' : 'resolved');
      this.state.counts = {
        open: this.state.tab === 'open' ? this.state.items.length : (await api.appeals('open')).length,
      };
    } catch (e) { toast(e.message, 'bad'); }
    this.render();
  }

  render() {
    const s = this.state;
    this.innerHTML = `
      <div class="page-head">
        <div><h1>Апелляции</h1><div class="sub">Проверяющий видит спорную оценку, комментарий и фрагмент диалога, затем подтверждает или меняет оценку с причиной.</div></div>
        <div class="tabs">
          <button class="tab ${s.tab === 'open' ? 'active' : ''}" data-tab="open">Открытые${s.counts?.open ? ` (${s.counts.open})` : ''}</button>
          <button class="tab ${s.tab === 'resolved' ? 'active' : ''}" data-tab="resolved">Рассмотренные</button>
        </div>
      </div>
      ${s.items.length ? s.items.map(a => this.card(a)).join('') : `<div class="card empty"><h3>${s.tab === 'open' ? 'Открытых апелляций нет' : 'Рассмотренных апелляций пока нет'}</h3>
        Апелляцию подают из карточки оценки кнопкой «Оспорить» у критерия.</div>`}`;
    this.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => { s.tab = b.dataset.tab; this.load(); }));
    this.bind();
  }

  card(a) {
    const d = a.disputed;
    const disputedRow = { ...d, type: a.criterion?.type, scale_max: a.current_item?.scale_max };
    const keyIds = new Set([...(d.evidence_ids || [])]);
    const conv = { is_call: a.is_call };
    const fragment = (a.fragment || []).map(t => `<div class="frag ${keyIds.has(t.id) ? 'key' : ''}">
        <div class="fh">#${t.id} · ${esc(SPEAKER[t.speaker] || t.speaker)} · ${esc(msgTime(conv, t))}</div>${esc(t.text)}</div>`).join('')
      || '<div class="muted small">Модель не указала реплики</div>';

    return `<article class="card appeal" data-ap="${a.appeal_id}">
      <div class="row">
        <div class="grow">
          <div class="crumbs"><a href="#/dialog/${encodeURIComponent(a.conversation_id)}?ev=${a.evaluation_id}" class="mono">${esc(a.conversation_id)}</a>
            · ${a.is_call ? 'звонок' : 'чат'} · ${esc(a.language || '')} · чек-лист v${a.checklist_version ?? '?'} · подана ${dateTime(a.created_at)}</div>
          <h3 style="font-size:17px"><span class="mono muted" style="font-size:12px">${esc(a.criterion_id)}</span> ${esc(a.criterion_title)}</h3>
        </div>
        ${a.status === 'open' ? '<span class="badge" style="color:var(--warn)">на рассмотрении</span>'
          : a.status === 'changed' ? '<span class="badge" style="color:var(--ok)">оценка изменена</span>'
            : '<span class="badge">оценка подтверждена</span>'}
      </div>
      <div class="appeal-grid">
        <div class="stack">
          <div class="box"><h4>Оспариваемая оценка</h4>
            <div class="row">${answerChip(disputedRow)}${d.points !== null && d.points !== undefined ? `<b>${num(d.points)} / ${num(d.max_points)}</b>` : '<span class="muted">без баллов</span>'}</div>
            <div class="small" style="margin-top:8px;color:var(--ink-2)">${esc(d.explanation)}</div></div>
          <div class="box"><h4>Комментарий апелляции</h4><div>${esc(a.comment)}</div></div>
          ${a.criterion ? `<div class="box"><h4>Правило чек-листа</h4><div class="small">${esc(a.criterion.yes_rule || '')}
            ${a.criterion.type === 'scale' ? `<ul style="margin:6px 0 0;padding-left:18px">${a.criterion.scale.map(st => `<li><b>${num(st.value)}</b> — ${esc(st.label)}</li>`).join('')}</ul>` : ''}
            ${a.criterion.na_allowed && a.criterion.na_rule ? `<div style="margin-top:6px"><b>N/A:</b> ${esc(a.criterion.na_rule)}</div>` : ''}</div></div>` : ''}
        </div>
        <div class="stack">
          <div class="box"><h4>Фрагмент диалога</h4><div class="fragment">${fragment}</div></div>
          ${a.status === 'open' ? this.form(a) : this.decision(a)}
        </div>
      </div></article>`;
  }

  options(a) {
    const c = a.criterion;
    if (!c) return [];
    if (c.type === 'critical') return [['yes', 'Нарушение есть'], ['no', 'Нарушения нет']];
    const opts = c.type === 'scale' ? c.scale.map(st => [`score:${st.value}`, `${num(st.value)} — ${st.label}`])
      : [['yes', 'Да'], ['no', 'Нет']];
    if (c.na_allowed) opts.push(['na', 'N/A — неприменимо']);
    return opts;
  }

  form(a) {
    const f = this.state.forms[a.appeal_id] || { action: 'confirm' };
    return `<div class="box decision-form"><h4>Решение проверяющего</h4>
      <div class="seg"><button data-act="confirm" class="${f.action === 'confirm' ? 'on' : ''}">Подтвердить оценку</button>
        <button data-act="change" class="${f.action === 'change' ? 'on' : ''}">Изменить оценку</button></div>
      <label class="field ${f.action === 'change' ? '' : 'hidden'}" data-newwrap><span>Новый ответ</span>
        <select class="select" data-new>${this.options(a).map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('')}</select></label>
      <label class="field"><span>Причина решения</span><textarea class="textarea" data-reason rows="3" placeholder="Обязательно: почему оценка подтверждена или изменена"></textarea></label>
      <div class="row"><span class="small muted grow">Итог сейчас: <b style="color:${scoreColor(a.totals?.current)}">${num(a.totals?.current)}</b>. После решения пересчитается автоматически.</span>
        <button class="btn primary" data-submit>${icon('flag')} Принять решение</button></div></div>`;
  }

  decision(a) {
    const d = a.decision || {};
    const c = a.criterion || {};
    const before = a.disputed;
    return `<div class="box"><h4>Решение</h4>
      <div class="flow">
        <div class="flow-step"><span class="k">Исходно</span><b>${esc(answerText(c.type, before.answer, before.value))}${before.points !== null && before.points !== undefined ? ` · ${num(before.points)}` : ''}</b></div>
        <span class="arrow">→</span>
        <div class="flow-step"><span class="k">Решение</span><b>${d.action === 'change' ? esc(answerText(c.type, d.answer, d.value)) : 'подтверждено'}${d.points_after !== null && d.points_after !== undefined ? ` · ${num(d.points_after)}` : ''}</b></div>
      </div>
      <div class="small" style="margin-top:8px"><b>Причина:</b> ${esc(d.reason)}</div>
      <div class="flow" style="margin-top:12px">
        <div class="flow-step"><span class="k">Итог до</span><cqa-score-ring size="64" value="${d.total_before ?? ''}" static></cqa-score-ring></div>
        <span class="arrow">→</span>
        <div class="flow-step"><span class="k">Итог после</span><cqa-score-ring size="64" value="${d.total_after ?? ''}" static></cqa-score-ring></div>
        <span class="small muted">${dateTime(d.decided_at)}</span>
      </div></div>`;
  }

  bind() {
    this.querySelectorAll('[data-ap]').forEach(card => {
      const id = card.dataset.ap;
      card.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
        this.state.forms[id] = { action: b.dataset.act };
        card.querySelectorAll('[data-act]').forEach(x => x.classList.toggle('on', x === b));
        card.querySelector('[data-newwrap]').classList.toggle('hidden', b.dataset.act !== 'change');
      }));
      card.querySelector('[data-submit]')?.addEventListener('click', () => this.submit(card, id));
    });
  }

  async submit(card, id) {
    const action = (this.state.forms[id] || { action: 'confirm' }).action;
    const reason = card.querySelector('[data-reason]').value.trim();
    if (!reason) return toast('Укажите причину решения', 'bad');
    const body = { action, reason };
    if (action === 'change') {
      const v = card.querySelector('[data-new]').value;
      if (v.startsWith('score:')) { body.answer = 'score'; body.value = +v.slice(6); } else body.answer = v;
    }
    const btn = card.querySelector('[data-submit]');
    btn.disabled = true;
    try {
      const r = await api.decide(id, body);
      const d = r.appeal.decision;
      toast(`Решение принято. Итог: ${num(d.total_before)} → ${num(d.total_after)}`, 'ok');
      emit('cqa:appeals-changed');
      this.load();
    } catch (e) { toast(e.message, 'bad'); btn.disabled = false; }
  }
}

customElements.define('cqa-appeals-view', AppealsView);
