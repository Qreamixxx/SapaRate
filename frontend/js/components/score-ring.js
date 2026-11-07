// <cqa-score-ring value="87.33" size="170" label="из 100"> — animated ring, color goes red → amber → green.
import { num, scoreColor } from '../ui.js';

const LAST = new Map();

class ScoreRing extends HTMLElement {
  static get observedAttributes() { return ['value', 'size', 'label']; }

  connectedCallback() { this.render(); }
  attributeChangedCallback() { if (this.isConnected) this.render(); }

  render() {
    const size = +this.getAttribute('size') || 160;
    const stroke = Math.max(5, Math.round(size * 0.085));
    const raw = this.getAttribute('value');
    const value = raw === null || raw === '' || raw === 'null' ? null : +raw;
    const label = this.getAttribute('label') ?? '';
    const r = (size - stroke) / 2;
    const C = 2 * Math.PI * r;
    const c = size / 2;
    const fontSize = Math.round(size * (size < 60 ? 0.3 : 0.24));

    this.innerHTML = `<div class="ring" style="width:${size}px;height:${size}px" role="img" aria-label="Оценка ${value === null ? 'нет' : num(value)}">
      <svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
        <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="var(--ring-track)" stroke-width="${stroke}"/>
        <circle class="arc" cx="${c}" cy="${c}" r="${r}" fill="none" stroke-width="${stroke}" stroke-linecap="round"
          stroke-dasharray="${C}" stroke-dashoffset="${C}" transform="rotate(-90 ${c} ${c})"/>
      </svg>
      <div class="ring-center">
        <span class="ring-num" style="font-size:${fontSize}px">—</span>
        ${label && size >= 90 ? `<span class="ring-label">${label}</span>` : ''}
      </div></div>`;

    const arc = this.querySelector('.arc');
    const numEl = this.querySelector('.ring-num');
    if (value === null) {
      arc.style.stroke = 'var(--muted)';
      numEl.style.color = 'var(--muted)';
      numEl.textContent = '—';
      return;
    }
    // "memory" attribute: remembers the last value shown for this key, so after an appeal the ring
    // animates from the old total to the new one instead of from zero.
    const key = this.getAttribute('memory');
    const from = this._prev ?? (key && LAST.has(key) ? LAST.get(key) : 0);
    const to = Math.max(0, Math.min(100, value));
    this._prev = to;
    if (key) LAST.set(key, to);
    const animate = !this.hasAttribute('static') && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const duration = animate ? 1100 : 0;
    const start = performance.now();
    const step = now => {
      const t = duration ? Math.min(1, (now - start) / duration) : 1;
      const eased = 1 - Math.pow(1 - t, 3);
      const v = from + (to - from) * eased;
      const color = scoreColor(v);
      arc.style.stroke = color;
      arc.style.strokeDashoffset = String(C * (1 - v / 100));
      numEl.style.color = color;
      numEl.textContent = t < 1 ? num(v, 0) : num(value, size < 60 ? 0 : 2);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

customElements.define('cqa-score-ring', ScoreRing);
