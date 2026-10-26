'use strict';

// ---------- helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plural = (n, word, many = word + 's') => `${n.toLocaleString()} ${n === 1 ? word : many}`;

function ago(iso) {
  if (!iso) return '';
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 7 * 86400) return `${Math.floor(seconds / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

function bytes(n) {
  if (!n) return '0 KB';
  return n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB';
}

async function call(method, ...args) {
  try {
    const result = await window.pywebview.api[method](...args);
    return result ?? {};
  } catch (e) {
    return { error: String(e) };
  }
}

const KEY_NAMES = {
  ctrl_r: 'Right Ctrl', ctrl: 'Left Ctrl', shift_r: 'Right Shift', shift: 'Left Shift', alt_r: 'Right Alt',
  alt: 'Left Alt', caps_lock: 'Caps Lock', x1: 'Mouse X1', x2: 'Mouse X2',
  space: 'Space', menu: 'Menu key', scroll_lock: 'Scroll Lock', pause: 'Pause',
};
const keyName = (s) => KEY_NAMES[s.key] || s.key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

function shortcutSentence(shortcuts) {
  const enabled = (shortcuts || []).filter((s) => s.enabled !== false);
  if (!enabled.length) return 'No dictation shortcut is enabled. Turn one on in Settings.';
  const names = enabled.map(keyName).join(' or ');
  return enabled.every((s) => s.hold_mode)
    ? `Hold ${names} in any app while you speak, then let go to type it.`
    : `Press ${names} in any app, speak, then press it again to type what you said.`;
}

let toastTimer;
function toast(text, actionLabel, action) {
  const el = $('#toast');
  $('#toast-text').textContent = text;
  const button = $('#toast-action');
  button.style.display = actionLabel ? '' : 'none';
  button.textContent = actionLabel || '';
  button.onclick = async () => { el.classList.remove('show'); if (action) await action(); };
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), actionLabel ? 6000 : 2600);
}

// ---------- state ----------
const state = {
  page: 'home',             // one per sidebar item: 'home', 'insights', 'dictionary' or 'notetaker'
  status: null,
  home: null,
  insights: null,
  dictionary: null,
  dictTab: 'all',
  dictQuery: '',
  dictOpen: true,           // the Dictionary page shows its word list straight away
  heatOffset: 0,
  settingsSection: 'general',
};

function engineState(status) {
  if (!status || status.error) return 'unknown';
  const { client, server } = status;
  if (!client.running) return client.unreported ? 'stale' : 'off';
  if (client.recording) return 'recording';
  if (!server.listening) return 'server-down';
  if (!client.connected) return 'connecting';
  return 'ready';
}

// The client's live values win while it runs; saved settings otherwise.
function liveConfig() {
  const settings = state.home?.settings || {};
  const client = state.status?.client;
  return client?.running ? { ...settings, ...client } : settings;
}

// ---------- page ----------
async function load() {
  const [home, insights, dictionary, recent] = await Promise.all(
    [call('get_home'), call('get_insights'), call('get_dictionary'), call('get_recent', 5)]);
  state.home = home;
  state.insights = insights;
  state.dictionary = dictionary;
  state.recent = recent.items || [];
  if (home.client) state.status = { client: home.client, server: home.server, llm: home.llm };
}

// ---------- recent dictations (recovery) ----------
const RECENT_ALERT_MINUTES = 30;

function recentView() {
  const items = state.recent || [];
  if (!items.length) return '';
  const latest = items[0];
  const fresh = (Date.now() - new Date(latest.at).getTime()) / 60000 < RECENT_ALERT_MINUTES;
  const alert = latest.saved_only && fresh ? `
    <div class="unsent">
      <div class="unsent-head"><span class="chip warn">Not typed</span><span>Your last dictation wasn't typed: no text box was selected. It's saved here and on your clipboard.</span></div>
      <p class="unsent-text">${esc(latest.text)}</p>
      <button class="btn primary" data-copy-recent="0">${icon('doc')}Copy</button>
    </div>` : '';
  const rows = items.map((item, i) => `
    <div class="recent-row">
      <div class="recent-main">
        <div class="recent-meta">${esc(ago(item.at))}${item.app && item.app !== 'Unknown app' ? ` · ${esc(item.app)}` : ''}${item.saved_only ? ' · <span class="warn-text">Not typed</span>' : ''}</div>
        <div class="recent-text">${esc(item.text)}</div>
      </div>
      <button class="btn" data-copy-recent="${i}">Copy</button>
    </div>`).join('');
  return `
    ${alert}
    <button class="dict-toggle ${state.recentOpen ? 'open' : ''}" id="recent-toggle" aria-expanded="${!!state.recentOpen}">
      <span>Recent dictations · last ${items.length}</span>
      <span class="dict-toggle-action">${state.recentOpen ? 'Hide' : 'Show'}${icon('right')}</span>
    </button>
    ${state.recentOpen ? `<div class="recent-list">${rows}</div>` : ''}`;
}

function renderRecent() {
  const el = $('#recent');
  if (el) el.innerHTML = recentView();
}

async function copyRecent(index, button) {
  const item = (state.recent || [])[index];
  if (!item) return;
  const result = await call('copy_text', item.text);
  if (result.error) return toast(result.error);
  toast('Copied. Paste it where you were typing.');
  if (button) {
    const label = button.innerHTML;
    button.textContent = 'Copied';
    setTimeout(() => { button.innerHTML = label; }, 1800);
  }
}

function render() {
  return state.page === 'notetaker' ? renderNotetaker() : renderPage();
}

async function showPage(page) {
  state.page = page;
  $$('.nav-item[data-page]').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  $('#panel').scrollTop = 0;
  await render();
}

// Home, Insights and Dictionary share one load; each shows only its own section.
async function renderPage() {
  await load();
  $('#page').classList.remove('wide');
  if (state.page === 'insights') {
    $('#page').innerHTML = `<section id="insights">${insightsView()}</section>`;
  } else if (state.page === 'dictionary') {
    $('#page').innerHTML = `<section id="dictionary">${dictionaryView()}</section>`;
    bindDictionarySearch();
  } else {
    $('#page').innerHTML = `
      <h1 class="page-title">Welcome back, ${esc(state.home?.name || 'there')}</h1>
      <section class="hero" id="hero">
        <div class="hero-copy" id="hero-copy"></div>
        <div class="hero-wave"><canvas id="wave"></canvas></div>
      </section>
      <section class="recent" id="recent">${recentView()}</section>`;
    lastHero = '';
    refreshHero();
    startWave();
  }
}

function renderInsights() {
  const el = $('#insights');
  if (el) el.innerHTML = insightsView();
}

function renderDictionary() {
  const el = $('#dictionary');
  if (!el) return;
  el.innerHTML = dictionaryView();
  bindDictionarySearch();
}

// ---------- dictation banner ----------
// Start/Restart pressed: the banner stays put, with a spinner in the microphone chip, until the
// new client reports ready. The old client may still say 'ready' for a moment, so 'ready' only
// counts once the running client started after the click.
let enginePending = 0;
let micWasLoading = false;
let lastKeys = '';
const PENDING_MAX_MS = 60000;

function startingUp(s, client) {
  if (!enginePending) return false;
  const fresh = (client.started_at || 0) * 1000 >= enginePending - 2000;
  if ((fresh && (s === 'ready' || s === 'recording')) || Date.now() - enginePending > PENDING_MAX_MS) {
    enginePending = 0;
    return false;
  }
  return true;
}

function heroCopy() {
  const status = state.status || {};
  const client = status.client || {};
  const llm = status.llm || {};
  const starting = startingUp(engineState(status), client);
  const s = starting ? 'starting' : engineState(status);
  const cfg = liveConfig();
  const server = status.server || {};
  const host = esc(server.host || 'the desktop');
  const headline = {
    starting: ['Starting <em>…</em>', 'Loading your microphone and the speech engine. This takes a few seconds.'],
    ready: ['Utter is <em>ready</em>', shortcutSentence(cfg.shortcuts)],
    recording: ['Utter is <em>listening</em>', 'Press the same shortcut again to finish. The text goes to the app in front of you.'],
    off: ['Utter is <em>off</em>', 'Start dictation to use your voice in any app on this PC.'],
    'server-down': ['Speech engine <em>stopped</em>', 'Dictation is running but the local speech engine is not answering. Restart to bring it back.'],
    connecting: ['Connecting <em>…</em>', 'The speech engine is loading its model. This takes a few seconds after startup.'],
    unknown: ['Checking <em>status</em>', 'Reading the dictation client\'s live status…'],
    stale: ['Dictation is <em>running</em>', 'But it is an older build that does not report what it is doing. Restart it to see live status here.'],
  }[s];
  if (server.remote && s === 'server-down') {
    headline[0] = `Can't reach <em>${host}</em>`;
    headline[1] = `This PC uses the speech engine on ${server.host || 'the desktop'}. Make sure it is on, dictation is running there, and Tailscale is connected on both.`;
  } else if (server.remote && s === 'connecting') {
    headline[1] = `Connecting to the speech engine on ${server.host || 'the desktop'} over Tailscale.`;
  }
  // Saved settings may not list the keys, so keep the last ones seen while the client restarts.
  const keys = (cfg.shortcuts || []).filter((x) => x.enabled !== false && x.key).map(keyName).join(' / ') || (starting ? lastKeys : '');
  if (keys) lastKeys = keys;
  // Microphone chip: headset with a spinner until the client is ready, then the microphone's name.
  const chips = [];
  if (client.running || starting) {
    const micLoading = s === 'starting' || s === 'connecting' || s === 'server-down' || !client.microphone;
    const mic = micLoading
      ? '<span class="chip-spinner" aria-label="Loading microphone"></span>'
      : `<span class="${micWasLoading ? 'chip-arrive' : ''}">${esc(client.microphone.name)}</span>`;
    micWasLoading = micLoading;
    chips.push(`${icon('headset')}${mic}`);
    if (keys) chips.push(`${icon('keyboard')}<span>${esc(keys)}</span>`);
    if (server.remote) chips.push(`${icon('cpu')}<span>Speech on ${host}</span>`);
    // AI polish only shows up when it is on but its model server is not answering.
    if (cfg.llm_enabled && llm.reachable === false) {
      chips.push(`${icon('sparkle')}<span class="warn-text">AI polish needs ${esc(llm.label || llm.provider)}</span>`);
    }
  }
  const running = client.running || s === 'stale' || starting;
  const actions = running
    ? `<button class="btn light" data-engine="stop">${icon('stop')}Stop dictation</button>
       <button class="btn ghost-dark" data-engine="${s === 'server-down' ? 'restart-all' : 'restart'}">${icon('refresh')}Restart</button>`
    : `<button class="btn light" data-engine="start">${icon('play')}Start dictation</button>`;
  return `
    <div class="eyebrow">${s === 'recording' ? '<span class="dot rec"></span>' : ''}Dictation</div>
    <h2>${headline[0]}</h2>
    <p>${esc(headline[1])}</p>
    ${chips.length ? `<div class="hero-chips">${chips.map((c) => `<span class="hero-chip">${c}</span>`).join('')}</div>` : ''}
    <div class="hero-actions">${actions}</div>`;
}

// Update the text only when it changed; the wave canvas keeps running untouched.
let lastHero = '';
function refreshHero() {
  const hero = $('#hero');
  if (!hero) return;
  const html = heroCopy();   // first: it also ends a finished restart (enginePending)
  const s = engineState(state.status);
  waveMode = s === 'recording' ? 'recording' : (state.status?.client?.running || s === 'stale' || enginePending) ? 'ready' : 'off';
  hero.className = `hero ${waveMode}`;
  if (html === lastHero) return;
  lastHero = html;
  $('#hero-copy').innerHTML = html;
}

// ---------- wave animation: the Utter logo, moving ----------
// The logo is a 'u' between two short bars (assets/make_icon.py, 64-unit grid). Here two more
// bars per side fade it out into a waveform, and a travelling wave stretches each bar and arm.
// Everything is drawn on a canvas sized to its box and scaled so the tallest stretch still fits.
let waveMode = 'off';
let waveStarted = false;
const WAVE = {
  off: { amp: 0, speed: 0.4 },        // the plain logo, dimmed
  ready: { amp: 0.32, speed: 1.0 },
  recording: { amp: 1, speed: 2.6 },
};
const waveLevel = { amp: 0, speed: 0.4, phase: 0, color: 0, alpha: 0.35 };
// Side bars in logo units: offset from the centre and resting length. ±18.5 are the logo's own bars.
const LOGO_BARS = [[18.5, 10], [29, 7], [39.5, 4.5]];
const LOGO = { armX: 8, armTop: 13, armBottom: 3, stroke: 5.5 };
const UNITS_HIGH = 58;   // tallest stretch: arm top lifted 60% plus the u bobbing, with caps
const UNITS_WIDE = 92;

function startWave() {
  if (waveStarted) return;
  waveStarted = true;
  let last = performance.now();
  const frame = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    drawWave(dt);
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

function drawWave(dt) {
  const canvas = $('#wave');
  if (!canvas) return;
  const box = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(box.width));
  const h = Math.max(1, Math.floor(box.height));
  if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
  }
  // Ease toward the target so switching state swells or settles instead of jumping.
  const target = WAVE[waveMode];
  const ease = 1 - Math.pow(0.02, dt);
  waveLevel.amp += (target.amp - waveLevel.amp) * ease;
  waveLevel.speed += (target.speed - waveLevel.speed) * ease;
  waveLevel.color += ((waveMode === 'recording' ? 1 : 0) - waveLevel.color) * ease;
  waveLevel.alpha += ((waveMode === 'off' ? 0.35 : 0.95) - waveLevel.alpha) * ease;
  waveLevel.phase += dt * waveLevel.speed * 3.2;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const unit = Math.min(h / UNITS_HIGH, w / UNITS_WIDE);
  const cx = w / 2;
  const cy = h / 2;
  const t = waveLevel.phase;
  const amp = waveLevel.amp;
  // Wave height at a horizontal position (logo units): two travelling sines, so it never looks mechanical.
  const wave = (x) => Math.sin(t - x * 0.16) * 0.7 + Math.sin(t * 1.6 + x * 0.09) * 0.3;

  // White and dim when off, white when ready, Utter teal while listening.
  const c = waveLevel.color;
  const r = Math.round(245 + (127 - 245) * c), g = Math.round(243 + (216 - 243) * c), b = Math.round(238 + (195 - 238) * c);
  ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${waveLevel.alpha})`;
  ctx.lineWidth = LOGO.stroke * unit;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // Side bars: each stretches with the wave around its resting length (never below a dot).
  for (const [offset, rest] of LOGO_BARS) {
    for (const x of [-offset, offset]) {
      const length = Math.max(0, rest * (1 + amp * 1.25 * wave(x)));
      ctx.beginPath();
      ctx.moveTo(cx + x * unit, cy - (length / 2) * unit);
      ctx.lineTo(cx + x * unit, cy + (length / 2) * unit);
      ctx.stroke();
    }
  }

  // The 'u': arms rise and fall on the wave, and the whole letter bobs gently.
  const bob = amp * 3 * Math.sin(t * 0.8);
  const leftTop = LOGO.armTop * (1 + amp * 0.6 * wave(-LOGO.armX));
  const rightTop = LOGO.armTop * (1 + amp * 0.6 * wave(LOGO.armX));
  const bottom = cy + (LOGO.armBottom + bob) * unit;
  ctx.beginPath();
  ctx.moveTo(cx - LOGO.armX * unit, cy - (leftTop - bob) * unit);
  ctx.lineTo(cx - LOGO.armX * unit, bottom);
  ctx.arc(cx, bottom, LOGO.armX * unit, Math.PI, 0, true);
  ctx.lineTo(cx + LOGO.armX * unit, cy - (rightTop - bob) * unit);
  ctx.stroke();
}

// ---------- insights ----------
function gauge(wpm, typingWpm) {
  const f = Math.max(0, Math.min((wpm || 0) / 200, 1));
  const angle = Math.PI * (1 - f);
  const x = (90 + 70 * Math.cos(angle)).toFixed(1);
  const y = (90 - 70 * Math.sin(angle)).toFixed(1);
  const times = wpm && typingWpm ? (wpm / typingWpm).toFixed(1) : null;
  return `
    <svg class="gauge" width="180" height="104" viewBox="0 0 180 104">
      <path d="M20 90 A70 70 0 0 1 160 90" fill="none" stroke="var(--line)" stroke-width="16" stroke-linecap="round"/>
      ${f > 0 ? `<path d="M20 90 A70 70 0 0 1 ${x} ${y}" fill="none" stroke="var(--accent)" stroke-width="16" stroke-linecap="round"/>` : ''}
      <text x="90" y="72" text-anchor="middle" font-size="13" fill="var(--muted)">${times ? 'vs typing' : 'no data yet'}</text>
      <text x="90" y="94" text-anchor="middle" font-size="22" fill="var(--text)">${times ? times + '×' : '—'}</text>
    </svg>`;
}

function signedDuration(minutes) {
  const size = Math.abs(minutes);
  const text = size >= 60 ? `${(size / 60).toFixed(1)} h` : `${size < 10 ? size.toFixed(1) : Math.round(size)} min`;
  return `${minutes < 0 ? '−' : '+'}${text}`;
}

function learnRate(bucket) {
  return bucket?.seen ? `${bucket.percent}% of ${plural(bucket.seen, 'time')}` : '—';
}

// Last 14 days of new mishearings per 1,000 words, tallest bar = worst day.
function sparkline(days) {
  const recent = days.slice(-14);
  if (recent.length < 2) return '';
  const max = Math.max(...recent.map((day) => day.new_per_1k), 1);
  return `<div class="spark">${recent.map((day) => `<div style="height:${Math.max(day.new_per_1k / max * 100, 6)}%" title="${esc(day.day)}: ${day.new_per_1k} per 1,000 words (${plural(day.new_mishearings, 'new word')})"></div>`).join('')}</div>`;
}

const CATEGORY_ICONS ={ other: 'infinity', ai: 'bot', documents: 'doc', code: 'code', messages: 'chat', email: 'mail' };

function heatmap(calendar, offset) {
  const weeks = 17;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const end = new Date(today);
  end.setDate(end.getDate() - offset * weeks * 7 + (6 - end.getDay()));
  const start = new Date(end);
  start.setDate(start.getDate() - weeks * 7 + 1);
  const values = Object.values(calendar).filter((v) => v > 0).sort((a, b) => a - b);
  const q = (p) => values[Math.min(values.length - 1, Math.floor(p * values.length))] || 0;
  const level = (v) => (!v ? 0 : values.length < 4 ? Math.max(1, Math.ceil((v / values[values.length - 1]) * 4)) : v <= q(0.25) ? 1 : v <= q(0.5) ? 2 : v <= q(0.75) ? 3 : 4);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

  let months = '';
  let lastMonth = -1;
  for (let w = 0; w < weeks; w++) {
    const d = new Date(start);
    d.setDate(d.getDate() + w * 7);
    // Label the first column of each month (its week starts within the month's first 7 days).
    const label = d.getMonth() !== lastMonth && d.getDate() <= 7 ? d.toLocaleDateString(undefined, { month: 'short' }) : '';
    if (label) lastMonth = d.getMonth();
    months += `<span>${label}</span>`;
  }
  const cols = `34px repeat(${weeks}, 1fr)`;
  let rows = '';
  ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach((name, day) => {
    let cells = '';
    for (let w = 0; w < weeks; w++) {
      const d = new Date(start);
      d.setDate(d.getDate() + w * 7 + day);
      const words = calendar[iso(d)] || 0;
      const cls = d > today ? 'future' : `l${level(words)}${d.getTime() === today.getTime() ? ' today' : ''}`;
      cells += `<div class="cell ${cls}" title="${d.toDateString()}: ${plural(words, 'word')}"></div>`;
    }
    rows += `<div class="heat-row" style="grid-template-columns:${cols}"><span>${name}</span>${cells}</div>`;
  });
  return `<div class="heat"><div class="heat-months" style="grid-template-columns:${cols}"><span></span>${months}</div>${rows}</div>`;
}

function insightsView() {
  const d = state.insights || {};
  const head = (sub) => `<div class="section-head"><h2 class="section-title">Insights</h2><span class="since">${esc(sub)}</span></div>`;
  if (d.error && d.total_words === undefined) return head('') + `<div class="error-box">${esc(d.error)}</div>`;
  const fixes = d.fixes || {};
  const cats = d.categories || [];
  const maxCat = Math.max(1, ...cats.map((c) => c.percent));
  const change = d.month_change_percent;
  const pill = change == null
    ? (d.words_this_month ? 'New this month' : 'No words this month')
    : `${change >= 0 ? '↗' : '↘'} ${Math.abs(change)}% this month`;
  const maxApp = Math.max(1, ...(d.apps || []).map((a) => a.words));
  const typingWpm = d.time_saved?.typing_wpm || 110;
  const saved = d.dictations ? d.time_saved?.minutes : null;
  const cleanup = d.cleanup || [];
  const spoken = cleanup.reduce((sum, a) => sum + a.spoken_words, 0);
  const cleanupPercent = spoken ? Math.round(cleanup.reduce((sum, a) => sum + a.changed_words, 0) / spoken * 100) : null;
  const learning = d.learning || {};
  const curve = (learning.days || []).filter((day) => day.new_per_1k != null);
  const latest = curve[curve.length - 1];
  const since = d.first_day
    ? `Since ${new Date(d.first_day + 'T00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })} · ${plural(d.dictations, 'dictation')} · ${d.speaking_minutes} min of speech`
    : 'Your numbers appear here after the first dictation.';
  return `
    ${head(since)}
    ${d.error ? `<div class="error-box">${esc(d.error)}</div>` : ''}
    <div class="grid-3">
      <section class="card">
        <div class="big">${d.wpm ?? '—'}</div>
        <div class="metric-label">Words per minute <span class="info" title="Words in what you said divided by recording time, for recordings of a second or longer. Compared with your typing speed of ${typingWpm} wpm.">i</span></div>
        ${gauge(d.wpm, typingWpm)}
      </section>
      <section class="card">
        <div class="big">${(fixes.total || 0).toLocaleString()}</div>
        <div class="metric-label">Fixes made by Utter</div>
        <div class="divider"></div>
        <div class="fix-row"><span><strong>${(fixes.dictionary || 0).toLocaleString()}</strong> dictionary fixes</span><span class="info" title="Sound-alike mistakes swapped for a word in your dictionary.">i</span></div>
        <div class="fix-row"><span><strong>${(fixes.rules || 0).toLocaleString()}</strong> replacements</span><span class="info" title="Exact phrases rewritten by a replacement rule, including spoken punctuation.">i</span></div>
        <div class="fix-row"><span><strong>${(fixes.ai_words || 0).toLocaleString()}</strong> words polished by AI</span><span class="info" title="Words AI polish removed, added or rewrote.">i</span></div>
        <div class="fix-row"><span><strong>${(fixes.learned || 0).toLocaleString()}</strong> words learned</span><span class="info" title="Words and replacements Utter added after you corrected its output.">i</span></div>
      </section>
      <section class="card">
        <div class="card-title-row"><div class="big">${(d.total_words || 0).toLocaleString()}</div><span class="pill">${esc(pill)}</span></div>
        <div class="metric-label">Total words dictated</div>
        <div class="divider"></div>
        <div class="fix-row"><span class="muted">Today</span><span>${plural(d.today?.words || 0, 'word')}</span></div>
        <div class="fix-row"><span class="muted">This month</span><span>${plural(d.words_this_month || 0, 'word')}</span></div>
      </section>
    </div>
    <div class="grid-3">
      <section class="card">
        <div class="big">${saved == null ? '—' : signedDuration(saved)}</div>
        <div class="metric-label">Time saved vs typing <span class="info" title="Time typing your dictated words at ${typingWpm} wpm would take, minus the time spent saying them. Negative when you type faster than you speak.">i</span></div>
        <div class="divider"></div>
        <div class="fix-row"><span class="muted">You speak</span><span>${d.wpm ? `${d.wpm} wpm` : '—'}</span></div>
        <div class="fix-row"><span class="muted">You type</span><span>${typingWpm} wpm</span></div>
      </section>
      <section class="card">
        <div class="big">${cleanupPercent == null ? '—' : `${cleanupPercent}%`}</div>
        <div class="metric-label">Words changed by cleanup <span class="info" title="Share of the words you said that replacements, dictionary fixes and AI polish removed or rewrote before typing. Punctuation changes count.">i</span></div>
        <div class="divider"></div>
        ${cleanup.length ? cleanup.slice(0, 4).map((a) => `
          <div class="fix-row"><span>${esc(a.name)}</span><span class="muted">${a.percent}% of ${plural(a.spoken_words, 'word')}</span></div>`).join('')
          : '<div class="empty">Appears after your first dictation.</div>'}
      </section>
      <section class="card">
        <div class="card-title-row"><div class="big">${latest?.new_per_1k ?? '—'}</div>${sparkline(curve)}</div>
        <div class="metric-label">New mishearings per 1,000 words <span class="info" title="Words the AI reviewer or you had to teach Utter, counted on the day each was first misheard. Falling means Utter knows your vocabulary. Only mistakes someone noticed count.">i</span></div>
        <div class="divider"></div>
        <div class="fix-row"><span class="muted">Right before learning</span><span>${learnRate(learning.before_learned)}</span></div>
        <div class="fix-row"><span class="muted">Right after learning</span><span>${learnRate(learning.after_learned)}</span></div>
      </section>
    </div>
    <div class="grid-2">
      <section class="card">
        <div class="card-title-row"><h2 class="card-title">Desktop usage</h2><span class="eyebrow">Total apps used | ${d.total_apps || 0}</span></div>
        ${cats.map((c, i) => `
          <div class="usage-row">
            ${icon(CATEGORY_ICONS[c.key] || 'infinity')}
            <div class="bar-track"><div class="bar lvl-${Math.min(i, 2)}" style="width:${Math.max(c.percent / maxCat * 100, 0)}%">${c.percent}%</div></div>
            <span class="usage-label">${c.count.toLocaleString()} ${esc(c.label)}</span>
          </div>`).join('')}
      </section>
      <section class="card">
        <div class="card-title-row"><h2 class="card-title">${plural(d.streak?.current || 0, 'day')} streak</h2><span class="eyebrow">Longest streak | ${plural(d.streak?.longest || 0, 'day')}</span></div>
        <div class="heat-nav">
          <button class="icon-btn" data-heat="-1" title="Earlier">${icon('left')}</button>
          <button class="icon-btn" data-heat="1" title="Later" ${state.heatOffset === 0 ? 'disabled style="opacity:.3"' : ''}>${icon('right')}</button>
        </div>
        ${heatmap(d.calendar || {}, state.heatOffset)}
        <div class="legend">More <div class="cell l4"></div><div class="cell l3"></div><div class="cell l2"></div><div class="cell l1"></div> Less</div>
      </section>
    </div>
    <section class="card">
      <div class="card-title-row"><h2 class="card-title">Where you dictate</h2><span class="eyebrow">Words by app</span></div>
      ${(d.apps || []).length ? d.apps.map((a) => `
        <div class="app-row"><span>${esc(a.name)}</span><div class="app-bar" style="width:${a.words / maxApp * 100}%"></div><span class="muted">${a.words.toLocaleString()} words</span></div>`).join('')
        : '<div class="empty">Apps appear here once you dictate into them.</div>'}
    </section>`;
}

// ---------- dictionary ----------
function group(entry) {
  if (entry.kind === 'word') return 0;
  return entry.advanced ? 2 : 1;
}

function filteredEntries() {
  const entries = state.dictionary?.entries || [];
  const tab = state.dictTab;
  const q = state.dictQuery.trim().toLowerCase();
  return entries
    .filter((e) => tab === 'all' || (tab === 'words' && e.kind === 'word') || (tab === 'replacements' && e.kind === 'replacement') || (tab === 'learned' && e.source === 'learned'))
    .filter((e) => !q || [e.text, e.heard, e.pattern].some((v) => v && v.toLowerCase().includes(q)))
    // Newest learned first, then your words, then replacements, with pattern rules last.
    .sort((a, b) => (b.learned_at || '').localeCompare(a.learned_at || '') || group(a) - group(b) || b.fixes - a.fixes || a.text.localeCompare(b.text));
}

function dictionaryList() {
  const list = filteredEntries();
  if (!list.length) {
    return `<div class="empty" style="padding:24px 6px">${state.dictQuery ? 'No matches.' : state.dictTab === 'learned' ? 'Nothing learned yet. Fix a misheard name right after dictating and it will appear here.' : 'No entries yet.'}</div>`;
  }
  return list.map((e, i) => {
    const uses = e.fixes ? `${plural(e.fixes, 'fix', 'fixes')}` : '';
    const chip = e.source === 'learned' ? '<span class="chip learned">Learned</span>' : e.advanced ? '<span class="chip manual">Advanced</span>' : '';
    let main, sub;
    if (e.kind === 'word') {
      main = esc(e.text);
      sub = e.source === 'learned'
        ? (e.learned_by === 'review' ? `Learned by AI review ${ago(e.learned_at)}` : `Learned from your correction ${ago(e.learned_at)}`)
        : 'Word';
    } else if (e.advanced) {
      main = `<code>${esc(e.pattern)}</code><span class="arrow">→</span>${esc(e.text) || '<span class="faint">(removed)</span>'}`;
      sub = 'Pattern rule. Edit it in hot-rule.txt';
    } else {
      main = `${esc(e.heard)}<span class="arrow">→</span>${esc(e.text) || '<span class="faint">(removed)</span>'}`;
      sub = e.source === 'learned'
        ? `Replacement learned${e.learned_by === 'review' ? ' by AI review' : ''} ${ago(e.learned_at)}`
        : 'Replacement';
    }
    const remove = e.advanced ? '<span></span>' : `<button class="icon-btn" data-remove="${i}" title="Remove">${icon('trash')}</button>`;
    return `<div class="entry"><div class="entry-main"><div class="entry-text">${main}</div><div class="entry-sub">${sub}</div></div>${chip || '<span></span>'}<span class="uses">${uses}</span>${remove}</div>`;
  }).join('');
}

function dictionaryView() {
  const d = state.dictionary || {};
  const entries = d.entries || [];
  const count = (fn) => entries.filter(fn).length;
  const tabs = [
    ['all', 'All', entries.length],
    ['words', 'Words', count((e) => e.kind === 'word')],
    ['replacements', 'Replacements', count((e) => e.kind === 'replacement')],
    ['learned', 'Learned', count((e) => e.source === 'learned')],
  ];
  return `
    <div class="section-head">
      <h2 class="section-title">Dictionary</h2>
      <button class="chip ${d.auto_learn ? 'on' : 'off'}" data-settings="dictation" style="border:0;padding:5px 11px">Learning from your fixes: ${d.auto_learn ? 'On' : 'Off'}</button>
      <span class="strip-spacer"></span>
      <button class="btn primary" id="add-entry">${icon('plus')}Add new</button>
    </div>
    <p class="section-note">Utter swaps sound-alike mistakes for these words, so names and jargon come out right. Fix a misheard name right after dictating and Utter adds it here on its own.</p>
    ${d.error ? `<div class="error-box">${esc(d.error)}</div>` : ''}
    <button class="dict-toggle ${state.dictOpen ? 'open' : ''}" id="dict-toggle" aria-expanded="${state.dictOpen}">
      <span>${plural(tabs[1][2], 'word')} · ${plural(tabs[2][2], 'replacement')} · ${tabs[3][2]} learned</span>
      <span class="dict-toggle-action">${state.dictOpen ? 'Hide' : 'Show all'}${icon('right')}</span>
    </button>
    ${state.dictOpen ? `
    <div class="toolbar">
      <div class="tabs">${tabs.map(([key, label, n]) => `<button class="tab ${state.dictTab === key ? 'active' : ''}" data-tab="${key}">${label}<span class="count">${n}</span></button>`).join('')}</div>
      <label class="search">${icon('search')}<input id="dict-search" placeholder="Search"></label>
    </div>
    <div id="dict-list">${dictionaryList()}</div>` : ''}`;
}

function bindDictionarySearch() {
  const search = $('#dict-search');
  if (!search) return;
  search.value = state.dictQuery;
  search.oninput = () => { state.dictQuery = search.value; $('#dict-list').innerHTML = dictionaryList(); };
}

async function reloadDictionary() {
  state.dictionary = await call('get_dictionary');
  renderDictionary();
}

async function removeEntry(index) {
  const e = filteredEntries()[index];
  if (!e) return;
  const key = e.kind === 'word' ? e.text : e.pattern;
  const result = await call('remove_entry', e.kind, e.source, key);
  if (result.error) return toast(result.error);
  await reloadDictionary();
  const label = e.kind === 'word' ? e.text : `${e.heard} → ${e.text}`;
  toast(`Removed "${label}"`, 'Undo', async () => {
    const undo = e.kind === 'word' ? await call('add_word', e.text, e.source) : await call('add_replacement', e.heard, e.text, e.source);
    if (undo.error) toast(undo.error);
    await reloadDictionary();
  });
}

function openAddModal(mode = 'word') {
  const backdrop = $('#backdrop');
  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-label="Add to dictionary">
      <h2>Add to dictionary</h2>
      <p>${mode === 'word' ? 'A name, brand or term Utter should spell your way.' : 'Something Utter keeps mishearing, and what it should write instead.'}</p>
      <div class="segmented"><button data-mode="word" class="${mode === 'word' ? 'active' : ''}">Word</button><button data-mode="replacement" class="${mode === 'replacement' ? 'active' : ''}">Replacement</button></div>
      ${mode === 'word'
        ? '<div class="field"><label for="f-word">Word</label><input id="f-word" placeholder="e.g. Brightloop" autocomplete="off"></div>'
        : `<div class="field"><label for="f-heard">When Utter writes</label><input id="f-heard" placeholder="e.g. cloud code" autocomplete="off"></div>
           <div class="field"><label for="f-replacement">Write instead</label><input id="f-replacement" placeholder="e.g. Claude Code" autocomplete="off"></div>`}
      <div class="form-error" id="f-error"></div>
      <div class="modal-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" id="f-submit">Add</button></div>
    </div>`;
  backdrop.classList.add('open');
  $('input', backdrop).focus();
  $$('[data-mode]', backdrop).forEach((b) => (b.onclick = () => openAddModal(b.dataset.mode)));
  const submit = async () => {
    const result = mode === 'word'
      ? await call('add_word', $('#f-word').value)
      : await call('add_replacement', $('#f-heard').value, $('#f-replacement').value);
    if (result.error) { $('#f-error').textContent = result.error; return; }
    closeModal(false);
    toast(mode === 'word' ? 'Added. Utter will use it within a few seconds.' : 'Replacement added.');
    await reloadDictionary();
  };
  $('#f-submit').onclick = submit;
  $$('input', backdrop).forEach((input) => input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') submit(); }));
}

function closeModal(refresh = true) {
  const backdrop = $('#backdrop');
  backdrop.classList.remove('open');
  backdrop.innerHTML = '';
  if (refresh) render();
}

// ---------- settings ----------
const SETTINGS_SECTIONS = [
  ['general', 'General', 'gear'],
  ['system', 'System', 'cpu'],
  ['dictation', 'Dictation', 'mic'],
  ['notetaker', 'Notetaker', 'record'],
  ['connectors', 'Connectors', 'plug'],
  ['mcp', 'MCP', 'mcp'],
  ['privacy', 'Data and privacy', 'archive'],
];

function toggle(key, value) {
  return `<label class="switch"><input type="checkbox" data-setting="${key}" ${value ? 'checked' : ''}><span></span></label>`;
}

function row(title, desc, control) {
  return `<div class="row"><div class="row-text"><div class="row-title">${title}</div>${desc ? `<div class="row-desc">${desc}</div>` : ''}</div>${control}</div>`;
}

function settingsBody(s) {
  const v = s.values;
  const section = state.settingsSection;
  if (section === 'general') {
    const shortcuts = v.shortcuts || [];
    const allHold = shortcuts.length && shortcuts.every((x) => x.hold_mode);
    return `
      <h2 class="serif">General</h2>
      <div class="group-title">You</div>
      <div class="group">
        ${row('Your name', 'Used for the greeting on Home.', `<input type="text" data-text-setting="display_name" value="${esc(v.display_name || '')}">`)}
        ${row('Dark mode', 'Matches the moon button at the top of the window.', toggle('theme', v.theme === 'dark'))}
      </div>
      <div class="group-title">Dictation shortcuts</div>
      <div class="group">
        ${shortcuts.map((x, i) => row(esc(keyName(x)), x.type === 'mouse' ? 'Mouse button' : 'Keyboard key', `<label class="switch"><input type="checkbox" data-shortcut="${i}" ${x.enabled !== false ? 'checked' : ''}><span></span></label>`)).join('')}
        ${row('Hold to talk', allHold ? 'Hold the shortcut while you speak; let go to finish.' : 'Off: press once to start and again to finish.', `<label class="switch"><input type="checkbox" data-hold ${allHold ? 'checked' : ''}><span></span></label>`)}
      </div>
      <p class="note">Shortcut changes apply after dictation restarts. <button class="link" data-engine="restart">Restart dictation now</button></p>`;
  }
  if (section === 'system') {
    return `
      <h2 class="serif">System</h2>
      <div class="group-title">App settings</div>
      <div class="group">
        ${row('Launch Utter at login', 'Starts the speech engine and dictation when you sign in to Windows.', toggle('launch_at_login', s.launch_at_login))}
        ${row('Start dictation when this window opens', 'If dictation is off, opening Utter turns it on.', toggle('start_engine_with_app', v.start_engine_with_app))}
        ${row('Show status bar while dictating', 'A small pill at the bottom of the screen while Utter listens or polishes.', toggle('recording_status_bar', v.recording_status_bar))}
      </div>
      <div class="group-title">Sound</div>
      <div class="group">
        ${row('Dictation sounds', 'A soft chime when recording starts and stops.', toggle('dictation_sounds', v.dictation_sounds))}
        ${row('Quiet other apps while dictating', 'Music and other sounds go quiet while you speak, and come back when you finish.', toggle('mute_while_dictating', v.mute_while_dictating))}
        ${v.mute_while_dictating ? `
        ${row('How', v.quiet_mode === 'lower' ? 'Music keeps playing at 20% of its volume.' : 'Other apps are muted completely.', `<select class="select" data-choice="quiet_mode">
            <option value="mute" ${v.quiet_mode !== 'lower' ? 'selected' : ''}>Mute</option>
            <option value="lower" ${v.quiet_mode === 'lower' ? 'selected' : ''}>Lower volume</option>
          </select>`)}
        ${row('Only music and video apps', 'Spotify, media players and web browsers. Calls, games and everything else are left alone.', toggle('quiet_media_only', v.quiet_media_only))}` : ''}
      </div>
      <div class="group-title">Microphone</div>
      <div class="group">
        ${row('Microphone', microphoneNote(v.audio_input_device), microphoneSelect(v.audio_input_device))}
      </div>
      <p class="note">Utter checks for new or unplugged microphones every 5 seconds and never switches in the middle of a recording.</p>`;
  }
  if (section === 'dictation') {
    const llm = s.llm || {};
    return `
      <h2 class="serif">Dictation</h2>
      <div class="group-title">Corrections</div>
      <div class="group">
        ${row('Dictionary corrections', 'Swap sound-alike mistakes for words in your dictionary.', toggle('hot', v.hot))}
        ${row('Replacement rules', 'Rewrite exact phrases and spoken punctuation ("comma", "new line").', toggle('hot_rule', v.hot_rule))}
        ${row('Learn from my corrections', 'After each dictation, Utter watches the text field for 90 seconds. Names you fix are added to your dictionary. Terminals and password fields are skipped, and only the corrected word is kept.', toggle('auto_learn', v.auto_learn))}
        ${row('Review my dictations with AI', `When you are idle, a smarter AI (through your Codex CLI and ChatGPT login) reads new dictations and adds misheard names and terms to your dictionary, e.g. "codecs" to "Codex". The text of those dictations is sent to OpenAI. ${reviewNote()}`, toggle('auto_review', v.auto_review))}
      </div>
      <div class="group-title">AI polish</div>
      <div class="group">
        ${row('AI polish', `Removes filler words and fixes punctuation in long dictations using ${esc(llm.model || 'the model')} (${esc(llm.provider || '')}${llm.local ? ', on this PC' : ''}). Double-tap Right Shift to switch it while dictating.`, toggle('llm_enabled', v.llm_enabled))}
        ${row('Only polish dictations longer than', 'Shorter ones are typed straight away, with no delay.', `<span><input type="number" min="0" step="10" data-number-setting="llm_min_chars" value="${v.llm_min_chars}"> <span class="muted">chars</span></span>`)}
      </div>
      ${v.llm_enabled && llm.reachable === false ? `<p class="note warn">${esc(llm.label || llm.provider)} is not answering on this PC, so long dictations cannot be polished. Start ${esc(llm.label || llm.provider)} with ${esc(llm.model)} or turn AI polish off.</p>` : ''}
      <div class="group-title">Output</div>
      <div class="group">
        ${row('Paste instead of typing', 'Faster for long text. Uses the clipboard briefly.', toggle('paste', v.paste))}
        ${row('Keep the result on the clipboard', 'So you can paste it again if the text lands in the wrong place.', toggle('copy_output_to_clipboard', v.copy_output_to_clipboard))}
      </div>`;
  }
  if (section === 'notetaker') {
    const nt = s.notetaker || {};
    const llm = s.llm || {};
    const localName = `${llm.label || llm.provider || 'local model'}${llm.model ? ` (${llm.model})` : ''}`;
    return `
      <h2 class="serif">Notetaker</h2>
      <div class="group-title">Meeting notes</div>
      <div class="group">
        ${row('Write the notes with', nt.summarizer === 'codex'
          ? 'gpt-6-luna through the Codex app server, with your ChatGPT login. The meeting transcript is sent to OpenAI.'
          : `The AI polish model on this PC, ${esc(localName)}. Nothing leaves this PC.${llm.local && llm.reachable === false ? ` <span class="warn-text">${esc(llm.label || llm.provider)} is not answering right now.</span>` : ''}`,
          `<select class="select" data-nt-pref="summarizer">
            <option value="codex" ${nt.summarizer === 'codex' ? 'selected' : ''} ${nt.codex ? '' : 'disabled'}>Codex (gpt-6-luna)${nt.codex ? '' : ', not installed'}</option>
            <option value="local" ${nt.summarizer !== 'codex' ? 'selected' : ''}>Local AI</option>
          </select>`)}
        ${nt.codex ? row('ChatGPT account', '<span id="codex-email">Checking…</span>', '<span id="codex-action"></span>') : ''}
      </div>
      <div class="group-title">Calls</div>
      <div class="group">
        ${row('Offer to take notes when a call starts', 'A small window appears in the bottom-right corner when you join a Google Meet in your browser, or a Zoom or Teams call. Utter only checks which app is using the microphone and what its windows are called.', `<label class="switch"><input type="checkbox" data-nt-toggle="call_popup" ${nt.call_popup !== 'off' ? 'checked' : ''}><span></span></label>`)}
      </div>
      <div class="group-title">What is recorded</div>
      <div class="group">
        ${row('Your microphone and the call', 'Your side comes from the microphone dictation uses; everyone else comes from what this PC plays. Wear headphones so the call is not heard twice.', '')}
        ${row('Audio is never saved', 'Speech is transcribed on this PC as you go. Only the text, the notes and your contacts are kept.', '<span class="chip on">Local</span>')}
        ${row('Notes and contacts', esc(nt.path || ''), '<button class="btn" data-open="notes">Open</button>')}
      </div>
      <p class="note">Let people know when you take notes on a call.</p>`;
  }
  if (section === 'connectors') return connectorsBody(s.connectors || {});
  if (section === 'mcp') return mcpBody(s.connectors || {});
  const storage = s.storage || {};
  const google = s.connectors?.google || {};
  const agentNames = (s.connectors?.agents || []).filter((a) => a.added).map((a) => a.name);
  return `
    <h2 class="serif">Data and privacy</h2>
    <div class="group-title">Recording</div>
    <div class="group">
      ${row('Save audio recordings', 'Keeps each recording next to the daily notes, named by date and first words.', toggle('save_audio', v.save_audio))}
    </div>
    <div class="group-title">Where your data lives</div>
    <div class="group">
      ${row('Transcript archive', `Every dictation's text, the app it went to and the fixes applied. ${bytes(storage.archive_bytes)}.`, '<button class="btn" data-open="transcripts">Open</button>')}
      ${row('Recordings and daily notes', `${plural(storage.audio_files || 0, 'audio file')} in the year folders of ${esc(s.paths?.audio || 'the dictation folder')}.`, '<button class="btn" data-open="audio">Open</button>')}
      ${row('Dictionary files', 'hot.txt (your words) and hot-rule.txt (your replacements). Learned entries live in hot-learned.txt and hot-rule-learned.txt.', '<button class="btn" data-open="hot">Open</button>')}
      ${row('Logs', 'What the client and speech engine did, for troubleshooting.', '<button class="btn" data-open="logs">Open</button>')}
    </div>
    <div class="group-title">Who reads it</div>
    <div class="group">
      ${row('Speech recognition', 'Runs on this PC. Audio is never uploaded.', '<span class="chip on">Local</span>')}
      ${row('AI polish', s.llm?.local ? `Runs on this PC through ${esc(s.llm.label)} when it is on.` : `Sends text to ${esc(s.llm?.provider)} when it is on.`, s.llm?.local ? '<span class="chip on">Local</span>' : '<span class="chip warn">Online</span>')}
      ${row('Meeting notes', s.notetaker?.summarizer === 'codex' ? 'Written by Codex: meeting transcripts are sent to OpenAI through your ChatGPT login.' : 'Written by the AI model on this PC. Meeting audio is never saved.', s.notetaker?.summarizer === 'codex' ? '<span class="chip warn">Online</span>' : '<span class="chip on">Local</span>')}
      ${row('AI dictionary review', s.values.auto_review ? 'Sends the text of new dictations to OpenAI through your Codex CLI login, in batches while you are idle, to learn misheard words. Turn it off in Dictation.' : 'Off. No dictations are sent for review.', s.values.auto_review ? '<span class="chip warn">Online</span>' : '<span class="chip off">Off</span>')}
      ${row('Coding agents (Utter MCP)', agentNames.length ? `${esc(agentNames.join(', '))} can read your dictations, insights, dictionary and meetings when you ask. What they read is sent to their model's provider.` : 'None added.', agentNames.length ? '<span class="chip warn">Online</span>' : '<span class="chip off">Off</span>')}
      ${row('LM Studio (Utter MCP)', s.connectors?.lmstudio?.added ? 'A model on this PC can read your dictations, insights, dictionary and meetings when you switch Utter on in a chat. Nothing is sent online.' : 'Not added.', s.connectors?.lmstudio?.added ? '<span class="chip on">Local</span>' : '<span class="chip off">Off</span>')}
      ${row('Google Calendar', google.connected ? `Utter reads your calendar (read-only) as ${esc(google.email)}: today's events for the Notetaker and call detection, and meetings when an AI asks about them.` : 'Not connected.', google.connected ? '<span class="chip on">Read-only</span>' : '<span class="chip off">Off</span>')}
    </div>`;
}

// ---------- connectors and MCP ----------
function connector(logoName, name, desc, actions) {
  return `
    <div class="connector">
      <div class="connector-text">
        <div class="connector-name">${logo(logoName)}${name}</div>
        <div class="connector-desc">${desc}</div>
      </div>
      <div class="connector-actions">${actions}</div>
    </div>`;
}

const spinner = '<span class="spinner" aria-label="Working"></span>';
const linkBtn = (key, label) => `<button class="btn small" data-link="${key}">${label}</button>`;

function connectorsBody(c) {
  const g = c.google || {};
  let desc = 'Lets your AI match what you dictated to the meetings you were in';
  let actions = `<button class="btn" data-connector="${g.has_client ? 'google-connect' : 'google-setup'}">Connect</button>`;
  if (g.connected) {
    desc = `Connected as ${esc(g.email)}. Read-only: Utter reads today's events for the Notetaker and meetings when your AI asks about them.`;
    actions = `<span class="chip on">Connected</span><button class="btn" data-connector="google-disconnect">Disconnect</button>`;
  } else if (g.pending) {
    desc = `${spinner}Finish signing in to Google in your browser…`;
    actions = '<button class="btn" disabled>Connecting…</button>';
  } else if (g.error) {
    desc = `<span class="warn-text">${esc(g.error)}</span>`;
  }
  const setup = state.googleSetup && !g.connected && !g.pending ? `
    <div class="setup">
      <p>Google needs a sign-in app from your own Google Cloud project. It's a one-time setup of about 5 minutes, and only you can use it.</p>
      <ol class="steps">
        <li><span>Turn on the <strong>Google Calendar API</strong>.</span>${linkBtn('google_calendar_api', 'Open')}</li>
        <li><span>Set up the consent screen: <strong>External</strong>, add yourself as a test user, then <strong>Publish app</strong> so sign-in doesn't expire after 7 days.</span>${linkBtn('google_consent', 'Open')}</li>
        <li><span>Create an OAuth client of type <strong>Desktop app</strong> and download its JSON file.</span>${linkBtn('google_clients', 'Open')}</li>
        <li><span>Choose that file. Utter then opens Google sign-in. Google warns that the app is unverified: choose <strong>Advanced</strong>, then continue.</span><button class="btn primary small" data-connector="google-file">Choose file</button></li>
      </ol>
    </div>` : '';
  return `
    <h2 class="serif">Connectors</h2>
    <p class="lead">Connecting your apps lets your AI answer questions about your meetings and what you said in them.</p>
    ${connector('gcal', 'Google Calendar', desc, actions)}
    ${setup}
    <div class="connector-foot">
      <span class="logo-badge">${logo('codex')}</span>
      <span class="connector-foot-text">Give Codex, Claude Code, Pi or LM Studio access to your dictations, insights and meetings</span>
      <button class="btn" data-section="mcp">Go to MCP</button>
    </div>`;
}

function mcpBody(c) {
  const g = c.google || {};
  return `
    <h2 class="serif">MCP</h2>
    <p class="lead">Ask an AI about what you dictated: find something you said, sum up your week, or recall what you said in a meeting. Read-only: no app can change anything in Utter.</p>
    ${agentsCard(c.agents || [])}
    ${lmstudioCard(c.lmstudio || {})}
    <div class="group-title">What they can read</div>
    <div class="group">
      ${row('Dictations', 'Search and read what you dictated, when, and which app it went to.', '')}
      ${row('Insights', 'Words per minute, totals, streaks and the apps you dictate into.', '')}
      ${row('Dictionary', 'Your words and replacements, including learned ones.', '')}
      ${row('Meetings', g.connected ? 'Your Google Calendar events, with what you dictated during each.' : 'Connect Google Calendar in Connectors to add your meetings.', g.connected ? '<span class="chip on">On</span>' : '<button class="btn small" data-section="connectors">Connect</button>')}
    </div>
    <p class="note">What a coding agent reads is sent to its model's provider, such as OpenAI for Codex and Anthropic for Claude Code. LM Studio keeps it on this PC.</p>`;
}

// The coding agents start the Utter MCP on this PC. Each agent's own config lists it (see the README),
// so this card only reports; adding or removing Utter happens in that config.
function agentsCard(list) {
  const lines = list.map((a) => {
    let state = '<span class="faint">Not added</span>';
    if (a.error) state = `<span class="warn-text">${esc(a.error)}</span>`;
    else if (a.added && !a.enabled) state = 'Switched off';
    else if (a.added && !a.up_to_date) state = '<span class="warn-text">Points at a different Python. Update the utter entry in its MCP config.</span>';
    else if (a.added) state = a.last_used ? `Last read your data ${esc(ago(new Date(a.last_used * 1000).toISOString()))}` : 'Added, not used yet';
    return `<div class="model-line">${icon(a.added && !a.error ? 'code' : 'x')}<span><strong>${esc(a.name)}</strong> · ${state}</span></div>`;
  }).join('');
  const added = list.filter((a) => a.added).length;
  const desc = `Ask them about your dictations, e.g. <code>codex "what did I dictate yesterday?"</code> They start Utter on this PC, so there is no tunnel or key. Add an <code>utter</code> server that runs <code>.venv\\Scripts\\python.exe -m utter.mcp_server</code> from this folder to each agent's MCP config.${lines}`;
  return connector('codex', 'Coding agents', desc, `<span class="chip ${added ? 'on' : 'off'}">${added} of ${list.length} added</span>`);
}

function lmstudioCard(lm) {
  let desc = 'Let a model on this PC read the same data. Nothing leaves the PC, and no account or key is needed';
  let actions = '<button class="btn" data-connector="lmstudio-add">Add to LM Studio</button>';
  if (!lm.installed) {
    desc = 'LM Studio is not installed. Install it and open it once, then add Utter here.';
    actions = '<button class="btn" data-link="lmstudio_download">Get LM Studio</button>';
  } else if (lm.error) {
    desc = `<span class="warn-text">${esc(lm.error)}</span>`;
  } else if (lm.added) {
    const used = lm.last_used
      ? `Last read your data ${esc(ago(new Date(lm.last_used * 1000).toISOString()))}${lm.last_models?.length ? ` with ${esc(lm.last_models.join(', '))}` : ''}.`
      : 'In a chat, switch on <strong>mcp/utter</strong> and use a model that supports tools.';
    desc = lm.up_to_date ? `Added. ${used}` : '<span class="warn-text">Added, but Utter has moved since. Update so LM Studio can start it.</span>';
    actions = `${lm.up_to_date ? '' : '<button class="btn primary" data-connector="lmstudio-add">Update</button>'}<button class="btn" data-connector="lmstudio-remove">Remove</button>`;
    return connector('lmstudio', 'LM Studio', desc + lmstudioModels(lm), actions);
  }
  return connector('lmstudio', 'LM Studio', desc, actions);
}

// The model that answers is the one loaded in LM Studio; it is picked per chat, not per MCP server.
const SMALL_CONTEXT = 16384;
function lmstudioModels(lm) {
  if (!lm.running) return '<div class="model-line">LM Studio is closed.</div>';
  const models = lm.models || [];
  if (!models.length) return '<div class="model-line">No model loaded. Pick one at the top of a chat.</div>';
  return models.map((m) => {
    const k = m.context ? `${Math.round(m.context / 1024)}K context` : '';
    const warn = !m.tools ? 'not trained for tools, so it may not call Utter'
      : m.context && m.context < SMALL_CONTEXT ? `raise its context to 16K or more when you load it, or long searches won't fit` : '';
    return `<div class="model-line">${icon('cpu')}<span><strong>${esc(m.name)}</strong>${k ? ` · ${k}` : ''}${warn ? ` · <span class="warn-text">${warn}</span>` : ''}</span></div>`;
  }).join('');
}

async function connectorAction(action) {
  const toggles = { 'google-setup': 'googleSetup' };
  if (toggles[action]) {
    state[toggles[action]] = !state[toggles[action]];
    return openSettings();
  }
  const calls = {
    'google-file': () => call('choose_google_client'),
    'google-connect': () => call('connect_google'),
    'google-disconnect': () => call('disconnect_google'),
    'lmstudio-add': () => call('add_to_lmstudio'),
    'lmstudio-remove': () => call('remove_from_lmstudio'),
  };
  const result = await calls[action]();
  if (result.error) return toast(result.error);
  if (result.cancelled) return;
  if (action === 'google-file') state.googleSetup = false;
  if (action === 'google-disconnect') toast('Google Calendar disconnected');
  if (action === 'lmstudio-add') toast('Added to LM Studio. Restart LM Studio if it is open.');
  if (action === 'lmstudio-remove') toast('Removed from LM Studio');
  openSettings();
}

// While Google sign-in is still open in the browser, refresh the page until it settles.
let connectorPoll;
function watchConnectors(section, c) {
  clearTimeout(connectorPoll);
  if (section !== 'connectors' || !c.google?.pending) return;
  connectorPoll = setTimeout(() => {
    if ($('#backdrop').classList.contains('open') && state.settingsSection === section) openSettings();
  }, 1500);
}

async function openSettings(section) {
  if (section) state.settingsSection = section;
  const [s, connectors] = await Promise.all([call('get_settings'), call('get_connectors')]);
  if (s.error) return toast(s.error);
  s.connectors = connectors.error ? {} : connectors;
  const backdrop = $('#backdrop');
  backdrop.innerHTML = `
    <div class="modal settings" role="dialog" aria-label="Settings">
      <nav class="settings-nav">
        <div class="eyebrow">Settings</div>
        ${SETTINGS_SECTIONS.map(([key, label, ic]) => `<button class="nav-item ${state.settingsSection === key ? 'active' : ''}" data-section="${key}">${icon(ic)}${label}</button>`).join('')}
        <div class="version">Utter ${esc(s.version)}</div>
      </nav>
      <div class="settings-body">
        <button class="icon-btn close-btn" data-close title="Close">${icon('x')}</button>
        ${settingsBody(s)}
      </div>
    </div>`;
  backdrop.classList.add('open');
  $$('[data-section]', backdrop).forEach((b) => (b.onclick = () => openSettings(b.dataset.section)));
  $$('[data-setting]', backdrop).forEach((input) => (input.onchange = () => saveSetting(input.dataset.setting, input.checked, input)));
  $$('[data-text-setting]', backdrop).forEach((input) => (input.onchange = () => saveSetting(input.dataset.textSetting, input.value.trim(), input)));
  $$('[data-number-setting]', backdrop).forEach((input) => (input.onchange = () => saveSetting(input.dataset.numberSetting, parseInt(input.value || '0', 10), input)));
  $$('[data-choice]', backdrop).forEach((select) => (select.onchange = async () => {
    await saveSetting(select.dataset.choice, select.value, select);
    openSettings();   // refresh the description under the choice
  }));
  refreshCodexAccount();
  $$('[data-nt-toggle]', backdrop).forEach((input) => (input.onchange = async () => {
    const result = await call('set_notetaker_pref', input.dataset.ntToggle, input.checked ? 'on' : 'off');
    if (result.error) { input.checked = !input.checked; return toast(result.error); }
    toast('Saved');
  }));
  $$('[data-nt-pref]', backdrop).forEach((select) => (select.onchange = async () => {
    const result = await call('set_notetaker_pref', select.dataset.ntPref, select.value);
    if (result.error) return toast(result.error);
    if (state.nt) state.nt.prefs = result.prefs;
    toast('Saved');
    openSettings();
  }));
  const mic = $('[data-mic]', backdrop);
  if (mic) {
    mic.onchange = async () => {
      await saveSetting('audio_input_device', mic.value || null, mic);
      // The client switches within a few seconds; refresh the note once it has.
      setTimeout(() => { if (state.settingsSection === 'system' && $('#backdrop').classList.contains('open')) openSettings('system'); }, 6500);
    };
  }
  $$('[data-shortcut]', backdrop).forEach((input) => (input.onchange = () => saveShortcuts(s.values.shortcuts, (list) => { list[+input.dataset.shortcut].enabled = input.checked; })));
  const hold = $('[data-hold]', backdrop);
  if (hold) hold.onchange = () => saveShortcuts(s.values.shortcuts, (list) => list.forEach((x) => { x.hold_mode = hold.checked; }));
  $$('[data-connector]', backdrop).forEach((b) => (b.onclick = () => connectorAction(b.dataset.connector)));
  watchConnectors(state.settingsSection, s.connectors);
}

// The ChatGPT account the Codex CLI is signed in to: just the email, and a way to switch it.
let codexPoll;
async function refreshCodexAccount(refresh = false) {
  clearTimeout(codexPoll);
  if (!$('#codex-email')) return;
  const before = state.codexEmail;
  const a = await call('get_codex_account', refresh);
  const email = $('#codex-email');
  const action = $('#codex-action');
  if (!email) return;
  if (a.error && !a.login) { email.textContent = a.error; action.innerHTML = ''; return; }
  if (a.login === 'waiting') {
    email.textContent = 'Finish signing in in your browser.';
    action.innerHTML = '<button class="btn" data-codex="cancel">Cancel</button>';
    codexPoll = setTimeout(() => refreshCodexAccount(), 2000);
    return;
  }
  state.codexEmail = a.email;
  email.innerHTML = a.email ? esc(a.email) : 'Not signed in';
  if (a.error) email.innerHTML += ` <span class="warn-text">${esc(a.error)}</span>`;
  action.innerHTML = `<button class="btn" data-codex="switch">${a.email ? 'Switch account' : 'Sign in'}</button>`;
  if (before !== undefined && a.email && a.email !== before) toast(`Codex now uses ${a.email}.`);
}

async function codexAccountAction(what) {
  const result = await call(what === 'cancel' ? 'cancel_codex_login' : 'switch_codex_account');
  if (result.error) return toast(result.error);
  if (what !== 'cancel') toast('Sign in with the account you want in your browser.');
  refreshCodexAccount();
}

// What the AI reviewer last did, from the client's live status.
function reviewNote() {
  const review = state.status?.client?.review;
  if (!review || !state.status?.client?.running) return '';
  if (review.error) return `<span class="warn-text">Last try failed: ${esc(review.error)}. It retries in 15 minutes.</span>`;
  if (review.last_run) return `Last review ${esc(ago(new Date(review.last_run * 1000).toISOString()))}: ${esc(review.last_result || '')}.`;
  return 'Waiting for a quiet moment to review.';
}

// The list comes from the running client, which probes microphones every 5 seconds.
function microphoneSelect(preferred) {
  const client = state.status?.client || {};
  const names = [...(client.microphones || [])];
  if (preferred && !names.some((n) => sameMic(n, preferred))) names.push(preferred);
  const options = names.map((name) => {
    const connected = (client.microphones || []).some((n) => sameMic(n, name));
    const label = connected ? name : `${name} (not connected)`;
    return `<option value="${esc(name)}" ${preferred && sameMic(name, preferred) ? 'selected' : ''}>${esc(label)}</option>`;
  });
  return `<select class="select" data-mic>
      <option value="" ${preferred ? '' : 'selected'}>Automatic (headphones first)</option>
      ${options.join('')}
    </select>`;
}

function microphoneNote(preferred) {
  const client = state.status?.client || {};
  const current = client.microphone?.name;
  if (!client.running) return 'Start dictation to see the microphones on this PC.';
  if (!preferred) return `Headphones or a headset first, then a USB mic, then the Windows default.${current ? ` Now using ${esc(current)}.` : ''}`;
  const connected = (client.microphones || []).some((n) => sameMic(n, preferred));
  return connected
    ? `Always uses ${esc(preferred)} when it is connected.`
    : `${esc(preferred)} is not connected, so Utter picks automatically${current ? ` (now ${esc(current)})` : ''}. It switches back when you reconnect it.`;
}

// Windows shortens some device names, so a prefix of either name is the same microphone.
function sameMic(a, b) {
  const x = a.toLowerCase().trim();
  const y = b.toLowerCase().trim();
  return x.startsWith(y) || y.startsWith(x);
}

async function saveSetting(key, value, input) {
  if (key === 'theme') value = value ? 'dark' : 'light';
  const result = await call('set_setting', key, value);
  if (result.error) {
    toast(result.error);
    if (input && input.type === 'checkbox') input.checked = !input.checked;
    return;
  }
  if (key === 'theme') applyTheme(value);
  if (key === 'launch_at_login' && input) input.checked = result.value;
  if (key === 'mute_while_dictating') openSettings();   // show or hide its options
  toast('Saved');
}

async function saveShortcuts(current, change) {
  const list = current.map((x) => ({ key: x.key, type: x.type, enabled: x.enabled !== false, hold_mode: !!x.hold_mode }));
  change(list);
  if (!list.some((x) => x.enabled)) {
    toast('Keep at least one shortcut on, or you cannot start dictation.');
    return openSettings();
  }
  const result = await call('set_setting', 'shortcuts', list);
  if (result.error) return toast(result.error);
  toast('Saved. Restart dictation to use the new shortcuts.', 'Restart', () => engineAction('restart'));
  openSettings();
}

function openHelp() {
  const cfg = liveConfig();
  const backdrop = $('#backdrop');
  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-label="Help" style="width:min(520px,100%)">
      <h2>How to use Utter</h2>
      <p>${esc(shortcutSentence(cfg.shortcuts))}</p>
      <div class="group" style="margin-bottom:16px">
        ${row('Double-tap Right Shift', 'Switch AI polish on or off while you work.', '')}
        ${row('Esc', 'Stop AI polish output that is still typing.', '')}
        ${row('Say "comma", "full stop" or "new line"', 'At the start or end of a sentence, these become punctuation.', '')}
        ${row('Fix a misheard name', 'Edit it in place within 90 seconds and Utter learns it.', '')}
      </div>
      <div class="modal-actions"><button class="btn" data-open="setup">Open setup notes</button><button class="btn primary" data-close>Done</button></div>
    </div>`;
  backdrop.classList.add('open');
}

// ---------- engine actions ----------
async function engineAction(action) {
  const labels = { start: 'Starting dictation…', stop: 'Stopping dictation…', restart: 'Restarting dictation…', 'restart-all': 'Restarting…' };
  toast(labels[action] || 'Working…');
  if (action !== 'stop') {
    enginePending = Date.now();
    refreshHero();
  }
  if (action === 'restart-all') {
    await call('engine_action', 'stop');
    action = 'start';
  }
  const result = await call('engine_action', action);
  if (result.error) {
    enginePending = 0;
    toast(result.error);
  }
  setTimeout(pollStatus, 1500);
}

// ---------- theme ----------
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $('#theme-toggle').innerHTML = icon(theme === 'dark' ? 'sun' : 'moon');
}

// ---------- polling ----------
let polls = 0;
async function pollStatus() {
  const status = await call('get_status');
  if (!status.error) state.status = status;
  refreshHero();
  // A new dictation finished: refresh Recent so a not-typed one shows up straight away.
  const lastOutput = status.client?.last_output_at;
  if (lastOutput && lastOutput !== state.lastOutputSeen) {
    const first = state.lastOutputSeen === undefined;
    state.lastOutputSeen = lastOutput;
    if (!first) {
      state.recent = (await call('get_recent', 5)).items || [];
      renderRecent();
    }
  }
  await notetakerPoll();
  polls += 1;
  if (polls % 30 === 0 && state.page === 'insights') {
    state.insights = await call('get_insights');
    renderInsights();
  }
}

// ---------- events ----------
document.addEventListener('click', (ev) => {
  const t = ev.target.closest('button, [data-settings], [data-close]');
  if (!t) {
    if (ev.target.id === 'backdrop') closeModal();
    return;
  }
  if (t.dataset.action === 'settings') return openSettings();
  if (t.dataset.action === 'help') return openHelp();
  if (t.dataset.engine) return engineAction(t.dataset.engine);
  if (t.dataset.settings) return openSettings(t.dataset.settings);
  if (t.hasAttribute('data-close')) return closeModal();
  if (t.dataset.open) return call('open_path', t.dataset.open).then((r) => r.error && toast(r.error));
  if (t.dataset.link) return call('open_link', t.dataset.link).then((r) => r.error && toast(r.error));
  if (t.dataset.copyRecent !== undefined) return copyRecent(+t.dataset.copyRecent, t);
  if (t.dataset.codex) return codexAccountAction(t.dataset.codex);
  if (t.id === 'recent-toggle') {
    state.recentOpen = !state.recentOpen;
    return renderRecent();
  }
  if (t.dataset.tab) {
    state.dictTab = t.dataset.tab;
    return renderDictionary();
  }
  if (t.dataset.remove !== undefined) return removeEntry(+t.dataset.remove);
  if (t.id === 'add-entry') return openAddModal('word');
  if (t.id === 'dict-toggle') {
    state.dictOpen = !state.dictOpen;
    renderDictionary();
    if (state.dictOpen) $('#dict-search')?.focus({ preventScroll: true });
    return;
  }
  if (t.dataset.heat) {
    state.heatOffset = Math.max(0, state.heatOffset - Number(t.dataset.heat));
    return renderInsights();
  }
  if (t.id === 'theme-toggle') {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    call('set_setting', 'theme', next);
  }
});

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && $('#backdrop').classList.contains('open')) closeModal();
});

// ---------- zoom: Ctrl+Plus, Ctrl+Minus, Ctrl+0, Ctrl+wheel ----------
// The window's own browser shortcuts are off, so the page asks Utter to zoom; the level is remembered.
const ZOOM_STEPS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5];
let zoomLevel = 1;
let zoomWheelAt = 0;

async function zoomTo(level) {
  const result = await call('set_zoom', level);
  if (result.error) return toast(result.error);
  zoomLevel = result.zoom;
  toast(`Zoom ${Math.round(zoomLevel * 100)}%`, zoomLevel === 1 ? '' : 'Reset', () => zoomTo(1));
}

function zoomStep(direction) {
  const i = ZOOM_STEPS.reduce((best, z, k) => (Math.abs(z - zoomLevel) < Math.abs(ZOOM_STEPS[best] - zoomLevel) ? k : best), 0);
  zoomTo(ZOOM_STEPS[Math.max(0, Math.min(ZOOM_STEPS.length - 1, i + direction))]);
}

document.addEventListener('keydown', (ev) => {
  if (!ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const direction = { '=': 1, '+': 1, '-': -1, '_': -1 }[ev.key];
  if (direction) { ev.preventDefault(); zoomStep(direction); }
  else if (ev.key === '0') { ev.preventDefault(); zoomTo(1); }
});

window.addEventListener('wheel', (ev) => {
  if (!ev.ctrlKey || Date.now() - zoomWheelAt < 150) return;
  zoomWheelAt = Date.now();
  zoomStep(ev.deltaY < 0 ? 1 : -1);
}, { passive: true });

window.addEventListener('pywebviewready', async () => {
  const level = await call('get_zoom');
  if (typeof level === 'number') zoomLevel = level;
});

// Refresh numbers when you come back to the window, without disturbing a search in progress.
window.addEventListener('focus', async () => {
  if ($('#backdrop').classList.contains('open') || document.activeElement?.id === 'dict-search') return;
  if (state.page === 'notetaker') return;
  await load();
  refreshHero();
  renderInsights();
  renderDictionary();
});

window.addEventListener('pywebviewready', async () => {
  hydrateIcons();
  applyTheme((await call('get_theme')) === 'dark' ? 'dark' : 'light');
  await render();
  // Every second, so the banner reacts quickly when you start or stop dictating.
  setInterval(pollStatus, 1000);
});
