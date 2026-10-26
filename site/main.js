'use strict';

/* ---------------------------------------------------------------
 * Logo wave: the Utter mark (a 'u' between short bars, from
 * assets/make_icon.py) extended with smaller bars and moved by a
 * travelling wave. Same drawing as the desktop app's banner.
 * ------------------------------------------------------------- */
const LOGO_BARS = [[18.5, 10], [29, 7], [39.5, 4.5]];
const LOGO = { armX: 8, armTop: 13, armBottom: 3, stroke: 5.5 };
const MODES = { ready: { amp: 0.32, speed: 1 }, listening: { amp: 1, speed: 2.6 } };
const wave = { mode: 'ready', amp: 0.3, speed: 1, phase: 0, color: 0, visible: true };
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function drawWave(canvas, dt) {
  const box = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(box.width));
  const h = Math.max(1, Math.round(box.height));
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
  }
  const target = MODES[wave.mode];
  const ease = 1 - Math.pow(0.02, dt);
  wave.amp += (target.amp - wave.amp) * ease;
  wave.speed += (target.speed - wave.speed) * ease;
  wave.color += ((wave.mode === 'listening' ? 1 : 0) - wave.color) * ease;
  wave.phase += dt * wave.speed * 3.2;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const unit = Math.min(h / 62, w / 96);
  const cx = w / 2;
  const cy = h / 2;
  const t = wave.phase;
  const amp = wave.amp;
  const motion = (x) => Math.sin(t - x * 0.16) * 0.7 + Math.sin(t * 1.6 + x * 0.09) * 0.3;
  const c = wave.color;
  const mix = (a, b) => Math.round(a + (b - a) * c);
  ctx.strokeStyle = `rgb(${mix(243, 127)}, ${mix(239, 216)}, ${mix(230, 195)})`;
  ctx.lineWidth = LOGO.stroke * unit;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.shadowColor = `rgba(127, 216, 195, ${0.15 + 0.45 * c})`;
  ctx.shadowBlur = 18 * c + 4;

  for (const [offset, rest] of LOGO_BARS) {
    for (const x of [-offset, offset]) {
      const length = Math.max(0, rest * (1 + amp * 1.25 * motion(x)));
      ctx.beginPath();
      ctx.moveTo(cx + x * unit, cy - (length / 2) * unit);
      ctx.lineTo(cx + x * unit, cy + (length / 2) * unit);
      ctx.stroke();
    }
  }
  const bob = amp * 3 * Math.sin(t * 0.8);
  const leftTop = LOGO.armTop * (1 + amp * 0.6 * motion(-LOGO.armX));
  const rightTop = LOGO.armTop * (1 + amp * 0.6 * motion(LOGO.armX));
  const bottom = cy + (LOGO.armBottom + bob) * unit;
  ctx.beginPath();
  ctx.moveTo(cx - LOGO.armX * unit, cy - (leftTop - bob) * unit);
  ctx.lineTo(cx - LOGO.armX * unit, bottom);
  ctx.arc(cx, bottom, LOGO.armX * unit, Math.PI, 0, true);
  ctx.lineTo(cx + LOGO.armX * unit, cy - (rightTop - bob) * unit);
  ctx.stroke();
}

function startWave() {
  const canvas = document.getElementById('wave');
  if (!canvas) return;
  new IntersectionObserver(([entry]) => { wave.visible = entry.isIntersecting; }).observe(canvas);
  let last = performance.now();
  const frame = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (wave.visible) drawWave(canvas, reduceMotion ? 0 : dt);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

/* ---------------------------------------------------------------
 * Demo: a messy sentence streams in while "listening", then the
 * fillers strike out and collapse and the misheard word is fixed.
 * ------------------------------------------------------------- */
const SCRIPT = [
  { t: 'Um,', drop: true }, { t: 'so', drop: true }, { t: 'can', to: 'Can' }, { t: 'you' }, { t: 'send' },
  { t: 'the,', to: 'the' }, { t: 'uh,', drop: true }, { t: 'deck' }, { t: 'to' }, { t: 'cloud', to: 'Claude', fix: true },
  { t: 'before' }, { t: 'Friday,', drop: true }, { t: 'no', drop: true }, { t: 'wait,', drop: true }, { t: 'Thursday?' },
];
const FIXES = [
  'removed <b>um, so, uh</b>',
  '<b>cloud → Claude</b> from your dictionary',
  'kept your correction: <b>Thursday</b>',
];

const doc = document.getElementById('doc-text');
const fixes = document.getElementById('doc-fixes');
const stage = document.getElementById('stage');
const stateLabel = document.querySelector('#stage-state b');
let run = 0;            // bumps on every new take, so older timelines stop
let held = false;
let streamed = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function setMode(mode, label) {
  wave.mode = mode === 'listening' ? 'listening' : 'ready';
  stage.classList.toggle('listening', mode === 'listening');
  stateLabel.textContent = label;
}

function reset() {
  doc.innerHTML = '<span class="caret"></span>';
  fixes.innerHTML = '';
  streamed = 0;
}

function addWord(i) {
  const word = SCRIPT[i];
  const span = document.createElement('span');
  span.className = 'w heard';
  span.textContent = word.t + ' ';
  span.dataset.i = i;
  doc.insertBefore(span, doc.querySelector('.caret'));
  streamed = i + 1;
}

async function polish(id) {
  setMode('ready', 'Cleaning up');
  doc.querySelector('.caret')?.remove();
  const spans = [...doc.querySelectorAll('.w')];
  spans.forEach((span) => span.classList.remove('heard'));
  for (const span of spans) {
    if (SCRIPT[span.dataset.i].drop) {
      span.classList.add('strike');
      await sleep(90);
      if (id !== run) return;
    }
  }
  await sleep(650);
  if (id !== run) return;
  for (const span of spans) {
    const word = SCRIPT[span.dataset.i];
    if (word.drop) span.classList.add('gone');
    if (word.to) span.textContent = word.to + ' ';
    if (word.fix) span.classList.add('fixed');
  }
  await sleep(500);
  if (id !== run) return;
  setMode('ready', 'Typed');
  for (const html of FIXES) {
    const li = document.createElement('li');
    li.innerHTML = html;
    fixes.appendChild(li);
    await sleep(260);
    if (id !== run) return;
  }
}

// Self-playing loop, until a visitor holds Space or the wave.
async function autoplay() {
  const id = ++run;
  while (id === run) {
    reset();
    setMode('ready', 'Ready');
    await sleep(1300);
    if (id !== run) return;
    setMode('listening', 'Listening');
    for (let i = 0; i < SCRIPT.length; i++) {
      addWord(i);
      await sleep(210 + Math.random() * 120);
      if (id !== run) return;
    }
    await sleep(450);
    if (id !== run) return;
    await polish(id);
    await sleep(4200);
  }
}

async function holdStart() {
  if (held) return;
  held = true;
  const id = ++run;
  reset();
  setMode('listening', 'Listening');
  for (let i = 0; i < SCRIPT.length && held && id === run; i++) {
    addWord(i);
    await sleep(190 + Math.random() * 110);
  }
}

async function holdEnd() {
  if (!held) return;
  held = false;
  const id = ++run;
  for (let i = streamed; i < SCRIPT.length; i++) addWord(i);   // finish the sentence on release
  await sleep(250);
  if (id !== run) return;
  await polish(id);
  await sleep(5000);
  if (id === run) autoplay();
}

function bindHold() {
  const isTyping = () => ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);
  document.addEventListener('keydown', (ev) => {
    if (ev.code !== 'Space' || ev.repeat || isTyping()) return;
    if (document.activeElement?.tagName === 'BUTTON' || document.activeElement?.tagName === 'A') return;
    const rect = stage.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) return;  // only when the demo is on screen
    ev.preventDefault();
    holdStart();
  });
  document.addEventListener('keyup', (ev) => { if (ev.code === 'Space') holdEnd(); });
  const pad = document.querySelector('.stage-wave');
  pad.addEventListener('pointerdown', (ev) => { ev.preventDefault(); pad.setPointerCapture(ev.pointerId); holdStart(); });
  pad.addEventListener('pointerup', holdEnd);
  pad.addEventListener('pointercancel', holdEnd);
}

/* ---------------------------------------------------------------
 * Copy the agent setup prompt
 * ------------------------------------------------------------- */
async function copyPrompt(button) {
  const text = document.getElementById('prompt-text').textContent.trim();
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  const label = button.querySelector('[data-copy-label]');
  const original = label.textContent;
  button.classList.add('copied');
  label.textContent = 'Copied — paste it into your agent';
  setTimeout(() => { button.classList.remove('copied'); label.textContent = original; }, 2400);
}

document.querySelectorAll('[data-copy="prompt"]').forEach((button) => button.addEventListener('click', () => copyPrompt(button)));

/* tour: the frame tilts flat as it scrolls into view; clips play one after another while it is on screen */
const frame = document.getElementById('frame');
const video = document.getElementById('tour-video');
const caption = document.getElementById('tour-caption');
const tabs = [...document.querySelectorAll('.tour-tab')];
let onScreen = false;

function showClip(tab, play = true) {
  tabs.forEach((t) => {
    const active = t === tab;
    t.classList.toggle('active', active);
    t.setAttribute('aria-selected', active);
    t.style.setProperty('--p', 0);
  });
  const clip = tab.dataset.clip;
  video.poster = `assets/tour/${clip}.jpg`;
  video.src = `assets/tour/${clip}.mp4`;
  caption.textContent = tab.dataset.caption;
  if (play && onScreen && !reduceMotion) video.play().catch(() => {});
}

tabs.forEach((tab) => tab.addEventListener('click', () => showClip(tab)));
video.addEventListener('timeupdate', () => {
  const active = tabs.find((t) => t.classList.contains('active'));
  if (active && video.duration) active.style.setProperty('--p', video.currentTime / video.duration);
});
video.addEventListener('ended', () => {
  const next = tabs[(tabs.findIndex((t) => t.classList.contains('active')) + 1) % tabs.length];
  setTimeout(() => showClip(next), 700);
});
if (reduceMotion) video.controls = true;

new IntersectionObserver(([entry]) => {
  onScreen = entry.isIntersecting;
  if (onScreen) frame.classList.add('in');
  if (reduceMotion) return;
  if (onScreen) video.play().catch(() => {});
  else video.pause();
}, { threshold: 0.35 }).observe(frame);

startWave();
bindHold();
if (reduceMotion) {
  reset();
  SCRIPT.forEach((_, i) => addWord(i));
  polish(++run);
} else {
  autoplay();
}
