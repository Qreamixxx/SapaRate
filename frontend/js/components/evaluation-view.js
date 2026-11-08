// <cqa-evaluation-view conversation-id="..."> — result card: total ring, sections, criteria with
// explanations and evidence, transcript with jump-to-message and audio seek for calls, appeal button.
import { api } from '../api.js';
import {
  SPEAKER, TYPE_LABEL, answerChip, answerText, clock, dateTime, emit, esc, icon, modal, msgTime, num,
  rowStatusClass, scoreColor, store, toast,
} from '../ui.js';

class EvaluationView extends HTMLElement {
  connectedCallback() {
    this.cid = this.getAttribute('conversation-id');
    this.wantedEv = new URLSearchParams(location.hash.split('?')[1] || '').get('ev');
    this.state = { conv: null, evals: [], ev: null, checklists: [], checklistKey: '', openAppeals: [], busy: false };
    this.innerHTML = '<div class="skeleton" style="height:520px"></div>';
    this.load();
  }

  async load() {
    try {
      const [conv, evals, checklists] = await Promise.all([api.conversation(this.cid), api.evaluationsFor(this.cid), api.checklists()]);
      Object.assign(this.state, { conv, evals, checklists });
      this.state.ev = evals.find(e => e.evaluation_id === this.wantedEv) || evals[0] || null;
      const preferred = this.state.ev?.checklist_id || store.get('checklistKey', '').split('@')[0];
      const cl = checklists.find(c => c.checklist_id === preferred) || checklists[0];
      this.state.checklistKey = cl ? `${cl.checklist_id}@${cl.latest}` : '';
      await this.loadAppeals();
    } catch (e) {
      this.innerHTML = `<div class="card empty"><h3>Не удалось открыть диалог</h3>${esc(e.message)}<p><a href="#/dialogs">← К списку</a></p></div>`;
      return;
    }
    this.renderShell();
    this.renderLeft();
  }

  async loadAppeals() {
    const ev = this.state.ev;
    this.state.openAppeals = ev ? await api.appeals('open', ev.evaluation_id).catch(() => []) : [];
  }

  // ---------- layout (rendered once so the audio player keeps its position) ----------
  renderShell() {
    const c = this.state.conv;
    this.innerHTML = `
      <div class="page-head">
        <div>
          <div class="crumbs"><a href="#/dialogs">${icon('back')} Диалоги</a></div>
          <h1 class="mono" style="font-size:22px">${esc(c.conversation_id)}</h1>
          <div class="row" style="margin-top:6px">
            <span class="badge ${c.is_call ? 'call' : 'chat'}">${c.is_call ? 'звонок' : 'чат'}</span>
            <span class="badge">${esc(c.language || '—')}</span>
            <span class="badge">${c.transcript.length} реплик</span>
            <span class="badge">набор ${esc(c.group_id || '—')}</span>
          </div>
        </div>
        <div class="row" id="controls"></div>
      </div>
      <div class="history" id="history" style="margin-bottom:14px"></div>
      <div class="eval-grid">
        <div id="left"></div>
        <div class="card transcript">
          <div class="transcript-head">
            <div class="row"><h3 class="grow">Транскрипт</h3>
              <div class="legend"><span>Клиент — слева</span><span>Оператор — справа</span><span>Бот и система — по центру</span></div></div>
            ${c.is_call ? `<audio id="audio" controls preload="metadata"></audio>
              <div class="small muted" id="audioMsg">Загружаю запись… Клик по ▶ у реплики или по доказательству перематывает запись.</div>` : ''}
          </div>
          <div class="messages" id="messages">${c.transcript.map(t => this.msg(t)).join('')}</div>
        </div>
      </div>`;
    this.querySelector('#messages').addEventListener('click', e => {
      const p = e.target.closest('.play');
      if (p) this.seek(+p.dataset.id);
    });
    if (c.is_call) this.loadAudio();
  }

  msg(t) {
    const c = this.state.conv;
    const canPlay = c.is_call && t.audio_sec !== null && t.audio_sec !== undefined;
    return `<div class="msg sp-${esc(t.speaker)}" id="m-${t.id}" data-id="${t.id}">
      <div class="msg-head"><span class="mid">#${t.id + 1}</span><span class="who">${esc(SPEAKER[t.speaker] || t.speaker)}</span>
        <span>${esc(msgTime(c, t))}</span>
        ${canPlay ? `<button class="play" data-id="${t.id}" title="Воспроизвести с ${clock(t.audio_sec)}">${icon('play')}</button>` : ''}</div>
      <div class="bubble">${esc(t.text)}</div></div>`;
  }

  async loadAudio() {
    const audio = this.querySelector('#audio'), msg = this.querySelector('#audioMsg');
    try {
      const r = await api.audio(this.cid);
      audio.src = r.src;
      audio.addEventListener('error', () => {
        msg.innerHTML = `Запись не загрузилась в плеер. <a href="${esc(this.state.conv.audio_url)}" target="_blank" rel="noopener">Открыть запись в новой вкладке</a>`;
      }, { once: true });
      msg.textContent = 'Клик по ▶ у реплики или по доказательству перематывает запись.';
    } catch (e) {
      msg.innerHTML = `${esc(e.message)}. <a href="${esc(this.state.conv.audio_url)}" target="_blank" rel="noopener">Открыть запись отдельно</a>`;
    }
  }

  // ---------- left column ----------
  renderLeft() {
    this.renderControls();
    this.renderHistory();
    const left = this.querySelector('#left');
    const ev = this.state.ev;
    if (!ev) {
      left.innerHTML = `<div class="card empty"><h3>Диалог ещё не оценён</h3>
        Выберите чек-лист вверху и нажмите «Оценить». Модель ответит по каждому критерию, а баллы посчитает система.</div>`;
      return;
    }
    if (!this._leftBound) { this.bindLeft(); this._leftBound = true; }
    const r = ev.result;
    const bySection = (r.sections || []).map(s => ({ ...s, items: r.items.filter(i => i.section === s.id) }));
    const orphans = r.items.filter(i => !(r.sections || []).some(s => s.id === i.section));
    if (orphans.length) bySection.push({ id: '_', title: 'Прочее', items: orphans, points: null, max: null });

    left.innerHTML = this.summary(ev) + bySection.filter(s => s.items.length).map(s => `
      <div class="section-head"><h3>${esc(s.title)}</h3>
        <span class="pts">${s.points !== null && s.points !== undefined ? `${num(s.points)} / ${num(s.max)}` : ''}</span></div>
      ${s.items.map(i => this.crit(i)).join('')}`).join('');
  }

  renderControls() {
    const s = this.state;
    const options = s.checklists.flatMap(c => c.versions.slice().reverse().map(v =>
      `<option value="${esc(c.checklist_id)}@${v.version}" ${s.checklistKey === `${c.checklist_id}@${v.version}` ? 'selected' : ''}>${esc(c.name)} · v${v.version}</option>`)).join('');
    this.querySelector('#controls').innerHTML = `
      <select class="select" id="clSel" title="Чек-лист для оценки">${options}</select>
      <button class="btn primary" id="evalBtn" ${s.busy ? 'disabled' : ''}>
        ${s.busy ? '<span class="spinner"></span> Модель оценивает…' : `${icon('spark')} ${s.ev ? 'Переоценить' : 'Оценить'}`}</button>`;
    this.querySelector('#clSel').addEventListener('change', e => { s.checklistKey = e.target.value; });
    this.querySelector('#evalBtn').addEventListener('click', () => this.evaluate());
  }

  renderHistory() {
    const s = this.state, box = this.querySelector('#history');
    if (s.evals.length < 2) { box.innerHTML = ''; return; }
    box.innerHTML = `<span class="small muted" style="align-self:center;margin-right:4px">История оценок:</span>` +
      s.evals.map(e => `<button class="hist ${e.evaluation_id === s.ev?.evaluation_id ? 'active' : ''}" data-ev="${e.evaluation_id}">
        <span class="sw" style="background:${scoreColor(e.result.total)}"></span>${num(e.result.total)} · v${e.checklist_version}
        <span class="muted" style="font-weight:600">${dateTime(e.created_at)}</span></button>`).join('');
    box.querySelectorAll('[data-ev]').forEach(b => b.addEventListener('click', async () => {
      s.ev = s.evals.find(e => e.evaluation_id === b.dataset.ev);
      history.replaceState(null, '', `#/dialog/${encodeURIComponent(this.cid)}?ev=${s.ev.evaluation_id}`);
      await this.loadAppeals();
      this.clearHighlight();
      this.renderLeft();
    }));
  }

  summary(ev) {
    const r = ev.result, o = ev.original;
    const changed = o.total !== r.total;
    const delta = changed && o.total !== null && r.total !== null ? r.total - o.total : null;
    const na = r.items.filter(i => i.status === 'na');
    const naWeight = na.reduce((a, i) => a + i.weight, 0);
    const prev = this.state.evals.find(e => e.checklist_id === ev.checklist_id && e.checklist_version !== ev.checklist_version
      && e.created_at < ev.created_at);
    const u = ev.usage || {};
    return `<div class="card summary">
      <cqa-score-ring size="170" value="${r.total ?? ''}" label="из ${num(r.max_total, 0)}" memory="${ev.evaluation_id}"></cqa-score-ring>
      <div class="summary-side">
        <div class="total-line"><span class="big">Итоговая оценка</span>
          ${changed ? `<span class="muted">исходно ${num(o.total)}</span>${delta !== null ? `<span class="delta ${delta >= 0 ? 'up' : 'down'}">${delta >= 0 ? '+' : ''}${num(delta)} после апелляций</span>` : ''}` : ''}
          ${prev ? `<span class="muted small">· с чек-листом v${prev.checklist_version} было ${num(prev.result.total)}</span>` : ''}</div>
        ${r.critical_error
          ? `<div class="alert bad">${icon('alert')}<div>Выявлена грубая ошибка (${r.critical_items.map(esc).join(', ')}).${r.total === 0 && r.total_before_critical ? ` Итог обнулён, без неё было бы ${num(r.total_before_critical)}.` : ' Отмечена отдельно от итога.'}</div></div>`
          : '<div class="alert ok">Грубых ошибок не выявлено</div>'}
        ${na.length ? `<div class="alert info small"><div>N/A: ${na.map(i => `<b>${esc(i.criterion_id)}</b>`).join(', ')} — вес ${num(naWeight)} распределён между остальными критериями пропорционально.</div></div>` : ''}
        <div class="sec-bars">${(r.sections || []).filter(s => s.max).map(s => `
          <div class="sec-bar"><div class="lbl"><span>${esc(s.title)}</span><span>${num(s.points)} / ${num(s.max)}</span></div>
          <div class="track"><div style="width:${s.percent}%;background:${scoreColor(s.percent)}"></div></div></div>`).join('')}</div>
        <div class="meta"><span>Чек-лист: <b>${esc(ev.checklist_name || ev.checklist_id)} v${ev.checklist_version}</b></span>
          <span>Модель: <b>${esc(u.model || '—')}</b></span>
          <span>Токены: <b>${num(u.input_tokens, 0)} + ${num(u.output_tokens, 0)}</b></span>
          <span>Стоимость: <b>$${num(u.cost_usd ?? 0, 4)}</b></span>
          <span>Время: <b>${num((u.latency_ms || 0) / 1000, 1)} с</b></span>
          <span>${dateTime(ev.created_at)}</span></div>
      </div></div>`;
  }

  crit(i) {
    const conv = this.state.conv;
    const pending = this.state.openAppeals.some(a => a.criterion_id === i.criterion_id);
    const missed = i.answer === 'no' || (i.type === 'scale' && i.answer === 'score' && +i.value < +i.scale_max)
      || (i.type === 'critical' && i.answer === 'yes');
    let meta;
    if (i.type === 'critical') meta = 'Грубая ошибка · без баллов, отмечается отдельно';
    else if (i.status === 'na') meta = `${TYPE_LABEL[i.type]} · вес ${num(i.weight)} — исключён (N/A), вес перераспределён`;
    else meta = `${TYPE_LABEL[i.type]} · вес ${num(i.weight)}${Math.abs(i.effective_weight - i.weight) > 0.005 ? ` → ${num(i.effective_weight)} после перераспределения N/A` : ''}`;

    const pts = i.type === 'critical' ? '' : i.status === 'na' ? '<span class="crit-pts"><small>исключён</small></span>'
      : `<span class="crit-pts">${num(i.points)}<small> / ${num(i.max_points)}</small></span>`;

    const evidence = (i.evidence_ids || []).map(id => {
      const t = conv.transcript[id];
      if (!t) return '';
      return `<button class="ev" data-ids="${id}"><span class="ev-id">#${id + 1}</span>
        <span class="ev-who">${esc(SPEAKER[t.speaker] || t.speaker)} ${esc(msgTime(conv, t))}</span>
        <span class="ev-text">${esc(t.text)}</span></button>`;
    }).join('');
    const rng = i.checked_range;
    const o = i.override;

    return `<article class="card crit ${rowStatusClass(i)}" data-cid="${esc(i.criterion_id)}">
      <div class="crit-head">
        <div><div class="crit-title"><span class="cid">${esc(i.criterion_id)}</span>${esc(i.title)}</div>
          <div class="crit-meta">${meta}</div></div>
        <div class="crit-right">${pts}${answerChip(i)}</div>
      </div>
      ${i.status === 'na'
        ? `<div class="na-reason"><b>Почему N/A:</b> ${this.linkify(i.explanation)}</div>`
        : `<p class="crit-expl">${this.linkify(i.explanation)}</p>`}
      ${evidence || rng ? `<div class="evidence">
        ${evidence ? `<div class="small muted" style="font-weight:700">${missed ? 'Где ожидалось действие / ошибка:' : 'Доказательство:'}</div>${evidence}` : ''}
        ${rng ? `<button class="range-btn" data-range="${rng[0]}-${rng[1]}">Проверен участок #${rng[0] + 1}–#${rng[1] + 1}</button>` : ''}
      </div>` : ''}
      ${o ? `<div class="override"><div class="ov-line">
          <span>Исходно: ${esc(answerText(i.type, o.original_answer, o.original_value))}${o.original_points !== null && o.original_points !== undefined ? ` · ${num(o.original_points)}` : ''}</span>
          <span class="muted">→</span>
          <span>Решение проверяющего: ${esc(answerText(i.type, i.answer, i.value))}${i.points !== null ? ` · ${num(i.points)}` : ''}</span></div>
          <div class="small" style="margin-top:4px">Причина: ${esc(o.reason)}</div></div>` : ''}
      <div class="crit-foot">
        ${pending ? `<span class="pending-tag"><span class="spinner" style="width:11px;height:11px"></span> Апелляция на рассмотрении</span>`
          : `<button class="btn sm" data-appeal="${esc(i.criterion_id)}">${icon('flag')} Оспорить</button>`}
      </div></article>`;
  }

  linkify(text) {
    return esc(text || '').replace(/\[(\d+(?:\s*[,;]\s*\d+)*)\]/g, (_, list) =>
      list.split(/\s*[,;]\s*/).map(n => `<button class="ref" data-ids="${n}">[${+n + 1}]</button>`).join(' '));
  }

  bindLeft() {
    const left = this.querySelector('#left');
    left.addEventListener('click', e => {
      const ids = e.target.closest('[data-ids]');
      if (ids) return this.highlight(ids.dataset.ids.split(',').map(Number), true);
      const rng = e.target.closest('[data-range]');
      if (rng) { const [a, b] = rng.dataset.range.split('-').map(Number); return this.highlightRange(a, b); }
      const ap = e.target.closest('[data-appeal]');
      if (ap) return this.appeal(ap.dataset.appeal);
    });
  }

  // ---------- transcript interactions ----------
  clearHighlight() {
    this.querySelectorAll('.msg.hl, .msg.in-range').forEach(m => m.classList.remove('hl', 'in-range'));
  }

  highlight(ids, seek) {
    this.clearHighlight();
    const els = ids.map(id => this.querySelector(`#m-${id}`)).filter(Boolean);
    els.forEach(el => el.classList.add('hl'));
    if (els[0]) els[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (seek && this.state.conv.is_call && ids.length) this.seek(ids[0], false);
  }

  highlightRange(a, b) {
    this.clearHighlight();
    for (let i = a; i <= b; i++) this.querySelector(`#m-${i}`)?.classList.add('in-range');
    this.querySelector(`#m-${a}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  seek(id, mark = true) {
    const audio = this.querySelector('#audio');
    const t = this.state.conv.transcript[id];
    if (!audio || !t || t.audio_sec === null || t.audio_sec === undefined) return;
    if (mark) this.highlight([id], false);
    const go = () => { audio.currentTime = Math.max(0, t.audio_sec - 1); audio.play().catch(() => {}); };
    if (audio.readyState >= 1) go(); else audio.addEventListener('loadedmetadata', go, { once: true });
  }

  // ---------- actions ----------
  async evaluate() {
    const s = this.state;
    const [checklist_id, v] = s.checklistKey.split('@');
    s.busy = true;
    this.renderControls();
    this.querySelector('#left').style.opacity = '.55';
    try {
      const ev = await api.evaluate({ conversation_id: this.cid, checklist_id, version: +v });
      s.evals.unshift(ev);
      s.ev = ev;
      history.replaceState(null, '', `#/dialog/${encodeURIComponent(this.cid)}?ev=${ev.evaluation_id}`);
      await this.loadAppeals();
      toast(`Оценка готова: ${num(ev.result.total)}`, 'ok');
    } catch (e) { toast(e.message, 'bad', 7000); }
    s.busy = false;
    this.querySelector('#left').style.opacity = '';
    this.clearHighlight();
    this.renderLeft();
  }

  async appeal(criterionId) {
    const item = this.state.ev.result.items.find(i => i.criterion_id === criterionId);
    const res = await modal({
      title: `Апелляция: ${item.title}`,
      text: `Текущий ответ: <b>${esc(answerText(item.type, item.answer, item.value))}</b>${item.points !== null ? ` · ${num(item.points)} балл.` : ''}. Опишите, почему оценка неверна.`,
      fields: [{ name: 'comment', label: 'Комментарий', type: 'textarea', placeholder: 'Например: оператор представился в реплике #10, модель это не учла' }],
      okLabel: 'Подать апелляцию',
    });
    if (!res || !res.comment) return;
    try {
      await api.createAppeal({ evaluation_id: this.state.ev.evaluation_id, criterion_id: criterionId, comment: res.comment });
      toast('Апелляция отправлена проверяющему', 'ok');
      await this.loadAppeals();
      this.renderLeft();
      emit('cqa:appeals-changed');
    } catch (e) { toast(e.message, 'bad'); }
  }
}

customElements.define('cqa-evaluation-view', EvaluationView);
