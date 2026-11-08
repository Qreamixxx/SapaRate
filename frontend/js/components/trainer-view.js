// <cqa-trainer-view> — sandbox: type a dialogue ("К: …" client, "О: …" operator), get the normal evaluation card.
import { api } from '../api.js';
import { esc, toast } from '../ui.js';

const EXAMPLE = `К: Здравствуйте, не могу вывести деньги, приложение просит обновить анкету.
О: Здравствуйте! Меня зовут Алия. Откройте «Меню → Поручения → Изменение сведений» и отправьте анкету.
К: Нашёл. А когда можно повторить вывод?
О: После обработки поручения, обычно в тот же день. Если появятся вопросы, напишите нам. Хорошего дня!`;

class TrainerView extends HTMLElement {
  connectedCallback() {
    this.innerHTML = `
      <div class="page-head"><div><h1>Тренажёр</h1>
        <div class="sub">Напишите диалог построчно: «К: …» — клиент, «О: …» — оператор. Система оценит его по текущему чек-листу так же, как обычный диалог.</div></div></div>
      <div class="card card-pad stack">
        <textarea class="textarea" id="trainerText" rows="12" placeholder="К: ...&#10;О: ..."></textarea>
        <div class="row"><button class="btn primary" id="trainerEval">Оценить</button>
          <button class="btn" id="trainerExample" type="button">Вставить пример</button>
          <span class="small muted" id="trainerMsg"></span></div>
      </div>`;
    this.querySelector('#trainerExample').addEventListener('click', () => { this.querySelector('#trainerText').value = EXAMPLE; });
    this.querySelector('#trainerEval').addEventListener('click', () => this.run());
  }

  async run() {
    const btn = this.querySelector('#trainerEval'), msg = this.querySelector('#trainerMsg');
    const text = this.querySelector('#trainerText').value;
    btn.disabled = true; msg.textContent = 'Оцениваю…';
    try {
      const r = await api.sandbox(text);
      location.hash = `#/dialog/${encodeURIComponent(r.conversation_id)}`;
    } catch (e) { msg.textContent = ''; toast(e.message, 'bad', 7000); btn.disabled = false; }
  }
}

customElements.define('cqa-trainer-view', TrainerView);
