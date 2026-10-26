'use strict';
// Notetaker page: record a meeting live, then read its AI summary and link the people in it to contacts.
// Uses the helpers in app.js ($, call, esc, toast, icon, state).

state.nt = {
  notes: [], live: null, prefs: {}, me: 'Me', codex: false,
  today: null,              // null until the calendar has answered once
  tab: 'notes', query: '', searchOpen: false,
  selected: null, note: null, contacts: [], view: 'summary', open: false,
};

const SUMMARIZERS = { local: 'Local AI', codex: 'Codex (gpt-6-luna)' };

function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, '0');
  return `${h ? h + ':' : ''}${mm}:${String(s % 60).padStart(2, '0')}`;
}
function length(seconds) {
  const m = Math.max(1, Math.round((seconds || 0) / 60));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ''}`.trim();
}
const timeOf = (unix) => new Date(unix * 1000).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }).toLowerCase().replace(' ', '');
function dayOf(unix) {
  const d = new Date(unix * 1000);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return 'Today';
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}
const speakerName = (speaker) => (speaker === 'me' ? state.nt.me : 'Others');

// Summary text marks people as [[Name]]: linked ones read as contacts, the rest can be linked with a click.
function withMentions(text) {
  const links = state.nt.note?.links || {};
  return String(text || '').split(/\[\[([^\]]+)\]\]/).map((part, i) => {
    if (i % 2 === 0) return esc(part);
    return `<button class="mention ${links[part] ? 'linked' : ''}" data-mention="${esc(part)}">${esc(part)}</button>`;
  }).join('');
}

// ---------- loading ----------
// The calendar can take a couple of seconds, so the page never waits for it: the Today card fills in when it answers.
async function loadToday() {
  const today = await call('get_today_meetings');
  state.nt.today = today.error && today.connected === undefined ? { connected: false, meetings: [] } : today;
  const card = $('#nt-today');
  if (card && state.page === 'notetaker') card.innerHTML = todayView();
}

async function loadNotetaker() {
  loadToday();
  const [data, contacts] = await Promise.all([
    call('get_notetaker', state.nt.query),
    state.nt.tab === 'contacts' ? call('get_contacts') : null,
  ]);
  if (data.error) return toast(data.error);
  Object.assign(state.nt, { notes: data.notes, live: data.live, prefs: data.prefs, me: data.me, codex: data.codex });
  if (contacts) state.nt.contacts = contacts.contacts || [];
  await loadNote();
}

async function loadNote() {
  const id = state.nt.selected;
  if (id == null) { state.nt.note = null; return; }
  const note = await call('get_note', id);
  state.nt.note = note.error ? null : note;
  if (note.error) { state.nt.selected = null; state.nt.open = false; }
}

async function renderNotetaker() {
  await loadNotetaker();
  $('#page').classList.add('wide');
  $('#page').innerHTML = `
    <div class="nt">
      <div class="nt-main">
        <div class="page-head">
          <h1 class="page-title">Notetaker</h1>
          <div class="nt-head-actions">
            <button class="icon-btn" data-settings="notetaker" title="Notetaker settings">${icon('gear')}</button>
            <span id="nt-start-slot">${startButton()}</span>
          </div>
        </div>
        <div id="nt-live">${liveView()}</div>
        <section class="nt-today" id="nt-today">${todayView()}</section>
        <div class="toolbar nt-toolbar">
          <div class="tabs">
            <button class="tab ${state.nt.tab === 'notes' ? 'active' : ''}" data-nt-tab="notes">Past notes</button>
            <button class="tab ${state.nt.tab === 'contacts' ? 'active' : ''}" data-nt-tab="contacts">Contacts</button>
          </div>
          ${state.nt.tab === 'notes'
            ? `<label class="search nt-search">${icon('search')}<input id="nt-search" placeholder="Search notes" value="${esc(state.nt.query)}"></label>`
            : `<button class="btn" data-contact-new>${icon('plus')}Add contact</button>`}
        </div>
        <div id="nt-list">${state.nt.tab === 'notes' ? notesList() : contactsList()}</div>
      </div>
      <aside class="nt-detail" id="nt-detail">${detailView()}</aside>
    </div>`;
  const search = $('#nt-search');
  if (search) {
    let timer;
    search.oninput = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        state.nt.query = search.value;
        const data = await call('get_notetaker', state.nt.query);
        state.nt.notes = data.notes || [];
        $('#nt-list').innerHTML = notesList();
      }, 200);
    };
  }
  applyReading();
  setNavRecording();
}

function refreshNotetakerParts() {
  if (state.page !== 'notetaker' || !$('#nt-list')) return;
  $('#nt-start-slot').innerHTML = startButton();
  $('#nt-live').innerHTML = liveView();
  $('#nt-list').innerHTML = state.nt.tab === 'notes' ? notesList() : contactsList();
  $('#nt-detail').innerHTML = detailView();
  applyReading();
  setNavRecording();
}

function setNavRecording() {
  const dot = $('#nav-rec');
  if (dot) dot.hidden = !state.nt.live;
}

// ---------- header, live meeting and calendar ----------
function startButton() {
  const live = state.nt.live;
  if (live?.stopping) return `<button class="btn" disabled><span class="chip-spinner dark"></span>Finishing…</button>`;
  if (live) return `<button class="btn nt-stop" data-nt="stop"><span class="dot rec"></span>Stop Notetaker</button>`;
  return `<button class="btn nt-start" data-nt="start">${icon('record')}Start Notetaker</button>`;
}

function meter(level) {
  return `<span class="meter"><span style="width:${Math.round(Math.min(1, level || 0) * 100)}%"></span></span>`;
}

function liveView() {
  const live = state.nt.live;
  if (!live) return '';
  const sources = [];
  if (live.devices.me) sources.push(`<span class="hero-chip">${icon('mic')}<span>${esc(state.nt.me)} · ${esc(live.devices.me)}</span>${meter(live.levels.me)}</span>`);
  else sources.push(`<span class="hero-chip"><span class="warn-text">No microphone found: only the call is recorded</span></span>`);
  if (live.devices.others) sources.push(`<span class="hero-chip">${icon('speaker')}<span>Others · ${esc(live.devices.others)}</span>${meter(live.levels.others)}</span>`);
  else sources.push(`<span class="hero-chip"><span class="warn-text">Speakers could not be recorded: only you are heard</span></span>`);
  const lines = live.lines.slice(-3).map((l) => `<div class="live-line"><span class="live-who">${esc(speakerName(l.speaker))}</span>${esc(l.text)}</div>`).join('');
  const status = live.stopping
    ? `Finishing the transcript${live.pending ? ` (${live.pending} left)` : ''}…`
    : live.error || (live.pending > 1 ? `Transcribing… ${live.pending} waiting` : 'Listening to you and the call');
  return `
    <section class="nt-live ${live.stopping ? 'stopping' : ''}">
      <div class="nt-live-head">
        <div class="eyebrow"><span class="dot rec"></span>Recording · ${clock(live.elapsed)}</div>
        <span class="nt-live-status ${live.error ? 'warn-text' : ''}">${esc(status)}</span>
      </div>
      <div class="hero-chips">${sources.join('')}</div>
      <div class="live-lines">${lines || '<div class="live-line faint-dark">What people say shows up here a few seconds after they pause.</div>'}</div>
      ${live.stopping ? '' : `<div class="hero-actions"><button class="btn light" data-nt="stop">${icon('stop')}Stop and summarize</button></div>`}
    </section>`;
}

// Today's meetings from Google Calendar (Settings > Connectors). The current or next one gets the big card.
function whenLabel(m) {
  const now = Date.now();
  const start = new Date(m.start).getTime();
  if (now >= new Date(m.end).getTime()) return { text: 'Ended', past: true };
  if (now >= start) return { text: 'Now', now: true };
  const minutes = Math.round((start - now) / 60000);
  return { text: minutes < 60 ? `In ${Math.max(1, minutes)} min` : `At ${timeOf(start / 1000)}` };
}

function todayView() {
  if (!state.nt.today) return '<div class="eyebrow">Today</div><div class="nt-today-done">Checking your calendar…</div>';
  const today = state.nt.today;
  const meetings = today.meetings || [];
  if (!today.connected) {
    return `<div class="eyebrow">Today</div><div class="nt-today-empty">${icon('calendar')}<div>No meetings found</div>
      <button class="btn primary" data-settings="connectors">Connect calendar</button></div>`;
  }
  const busy = state.nt.live ? 'disabled' : '';
  const nextIndex = meetings.findIndex((m) => !whenLabel(m).past);
  const next = meetings[nextIndex];
  let html = '<div class="eyebrow">Today</div>';
  if (today.error) html += `<div class="nt-banner warn">${esc(today.error)}</div>`;
  if (next) {
    const when = whenLabel(next);
    const people = next.attendees?.length ? ` · ${plural(next.attendees.length, 'person', 'people')}` : '';
    html += `
      <div class="nt-next">
        <span class="nt-next-icon">${icon('video')}</span>
        <div class="nt-next-main">
          <div class="nt-next-title">${esc(next.title)}</div>
          <div class="nt-next-sub"><span class="dot ${when.now ? 'rec' : 'on'}"></span>${esc(when.text)} · ${timeOf(new Date(next.start).getTime() / 1000)}${esc(people)}</div>
        </div>
        <button class="nt-join" data-nt-join="${nextIndex}" ${busy}>
          <span class="nt-join-logo">${icon('record')}</span>
          <span><strong>${next.join_url ? 'Join meeting' : 'Start Notetaker'}</strong><span>${next.join_url ? '&amp; start notetaker' : 'for this meeting'}</span></span>
        </button>
      </div>`;
  } else if (!meetings.length) {
    html += `<div class="nt-today-empty">${icon('calendar')}<div>No meetings today</div></div>`;
  } else {
    html += '<div class="nt-today-done">No more meetings today.</div>';
  }
  html += meetings.map((m, i) => {
    if (i === nextIndex) return '';
    const when = whenLabel(m);
    return `
      <div class="nt-meeting ${when.past ? 'past' : ''}">
        <span class="nt-meeting-time">${timeOf(new Date(m.start).getTime() / 1000)}</span>
        <div class="nt-row-main"><div class="nt-row-title">${esc(m.title)}</div></div>
        ${when.past ? '<span class="nt-row-sub">Ended</span>' : `<button class="btn small" data-nt-join="${i}" ${busy}>${m.join_url ? 'Join and start' : 'Start'}</button>`}
      </div>`;
  }).join('');
  return html;
}

// ---------- lists ----------
function notesList() {
  const notes = state.nt.notes;
  if (!notes.length) {
    return `<div class="empty nt-empty">${state.nt.query ? 'No notes match.' : 'No meetings yet. Press Start Notetaker when a call begins: Utter records your microphone and the call audio, then writes the notes.'}</div>`;
  }
  let html = '';
  let day = '';
  for (const n of notes) {
    const label = dayOf(n.started_at);
    if (label !== day) { day = label; html += `<div class="nt-day">${esc(label)}</div>`; }
    const badge = { recording: '<span class="chip warn"><span class="dot rec"></span>Recording</span>', summarizing: '<span class="chip off">Summarizing…</span>',
                    failed: '<span class="chip warn">No summary</span>', empty: '<span class="chip off">Nothing heard</span>' }[n.status] || '';
    html += `
      <div class="nt-row ${state.nt.selected === n.id ? 'active' : ''}" data-note="${n.id}">
        <span class="nt-row-icon">${icon('doc')}</span>
        <div class="nt-row-main"><div class="nt-row-title">${esc(n.title)}</div><div class="nt-row-sub">${timeOf(n.started_at)}${n.ended_at ? ` · ${length(n.ended_at - n.started_at)}` : ''}</div></div>
        ${badge}
      </div>`;
  }
  return html;
}

function contactsList() {
  const contacts = state.nt.contacts;
  if (!contacts.length) return '<div class="empty nt-empty">No contacts yet. Click a name in a meeting summary to save that person, or add one here.</div>';
  return contacts.map((c) => `
    <div class="nt-row" data-contact="${c.id}">
      <span class="avatar">${esc((c.name || '?').trim()[0].toUpperCase())}</span>
      <div class="nt-row-main"><div class="nt-row-title">${esc(c.name)}</div><div class="nt-row-sub">${esc([c.company, c.email].filter(Boolean).join(' · ') || 'No details yet')}</div></div>
      <span class="nt-row-sub">${c.meetings ? `${plural(c.meetings, 'meeting')} · last ${esc(dayOf(c.last_met))}` : 'No meetings linked'}</span>
    </div>`).join('');
}

// ---------- note detail ----------
function detailView() {
  const note = state.nt.note;
  const live = state.nt.live;
  if (!note) return '<div class="nt-detail-empty">Select a meeting to see its notes.</div>';
  const isLive = live && live.note_id === note.id;
  const lines = isLive ? live.lines : note.lines;
  const when = `${new Date(note.started_at * 1000).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })} · ${timeOf(note.started_at)}`;
  const s = note.summary;
  // An open meeting fills the page, on its summary; the bar on top switches to the transcript.
  const view = isLive ? 'transcript' : state.nt.view;
  const tabs = `
    <div class="nt-viewbar">
      <button class="icon-btn" data-nt="back" title="Back to your meetings (Esc)">${icon('left')}</button>
      ${isLive ? '<span class="chip warn"><span class="dot rec"></span>Recording</span>' : `
      <div class="segmented nt-switch">
        <button class="${view === 'summary' ? 'active' : ''}" data-nt-view="summary">Summary</button>
        <button class="${view === 'transcript' ? 'active' : ''}" data-nt-view="transcript">Transcript <span class="faint">${lines.length}</span></button>
      </div>`}
    </div>`;
  let body = '';
  if (isLive) {
    body = '<div class="nt-banner"><span class="dot rec"></span>Recording. The notes are written when you stop.</div>';
  } else if (note.status === 'summarizing') {
    const backend = state.nt.writingWith?.[note.id] || state.nt.prefs.summarizer;
    body = `<div class="nt-banner"><span class="chip-spinner dark"></span>Writing the notes with ${esc(SUMMARIZERS[backend] || 'AI')}…</div>`;
  } else if (note.status === 'failed') {
    const other = state.nt.prefs.summarizer === 'codex' ? 'local' : 'codex';
    body = `<div class="nt-banner warn">${esc(note.error || 'The notes could not be written.')}</div>
      <div class="nt-banner-actions">
        <button class="btn" data-summarize="">${icon('refresh')}Try again</button>
        ${other === 'local' || state.nt.codex ? `<button class="btn" data-summarize="${other}" title="${other === 'codex' ? 'Sends the transcript to OpenAI with your ChatGPT login' : 'Runs on this PC'}">Use ${SUMMARIZERS[other]}</button>` : ''}
      </div>`;
  } else if (note.status === 'empty') {
    body = '<div class="nt-banner">No speech was heard in this meeting.</div>';
  }
  if (s) {
    body += `
      ${s.warning ? `<div class="nt-banner warn">${esc(s.warning)}</div>` : ''}
      <div class="nt-section"><div class="eyebrow">Overview</div><p class="nt-overview">${withMentions(s.overview)}</p></div>
      ${s.key_points?.length ? `<div class="nt-section"><div class="eyebrow">Key points</div><ul>${s.key_points.map((p) => `<li>${withMentions(p)}</li>`).join('')}</ul></div>` : ''}
      ${s.action_items?.length ? `<div class="nt-section"><div class="eyebrow">Action items</div><ul class="nt-actions">${s.action_items.map((a) => `<li>${a.owner ? `<strong>${withMentions(a.owner)}</strong> ` : ''}${withMentions(a.task)}</li>`).join('')}</ul></div>` : ''}`;
  }
  const transcript = lines.length
    ? `<div class="nt-transcript full">${lines.map((l) => `
        <div class="nt-line ${l.speaker}"><span class="nt-line-meta">${esc(speakerName(l.speaker))} · ${clock(l.at)}</span><span class="nt-line-text">${esc(l.text)}</span></div>`).join('')}</div>`
    : `<div class="nt-detail-empty">${isLive ? 'What people say shows up here a few seconds after they pause.' : 'Nothing was transcribed.'}</div>`;
  if (view === 'transcript') {
    // Keep only the status line from the summary side (recording, writing, failed) above the words.
    body = (isLive || note.status === 'summarizing' ? body : '') + transcript;
  } else if (!s && !body) {
    body = '<div class="nt-detail-empty">No summary yet.</div>';
  }
  const footer = isLive ? '' : `
    <div class="nt-detail-foot">
      ${s ? `<span class="faint">Written by ${esc(SUMMARIZERS[note.summarizer] || note.summarizer)}</span>
        ${note.status === 'summarizing' ? '' : '<button class="link" data-summarize="">Rewrite</button>'}` : ''}
      <span class="strip-spacer"></span>
      ${lines.length ? '<button class="icon-btn" data-nt="copy" title="Copy notes and transcript">' + icon('doc') + '</button>' : ''}
      <button class="icon-btn" data-nt="delete" title="Delete this meeting">${icon('trash')}</button>
    </div>`;
  return `
    ${tabs}
    <div class="nt-detail-head">
      <h2 class="nt-title">${esc(note.title)}</h2>
      ${isLive ? '' : `<button class="icon-btn" data-nt="rename" title="Rename">${icon('pencil')}</button>`}
    </div>
    <div class="nt-when">${esc(when)}${note.ended_at ? ` · ${length(note.ended_at - note.started_at)}` : ''}</div>
    <div class="nt-detail-body">${body}</div>
    ${footer}`;
}

// The page shows either the list of meetings or one open meeting, never both.
function applyReading() {
  const page = $('.nt');
  if (page) page.classList.toggle('reading', state.nt.open && !!state.nt.note);
}

function showView(view) {
  state.nt.view = view;
  closePopover();
  $('#nt-detail').innerHTML = detailView();
  applyReading();
  $('#panel').scrollTop = 0;
}

function closeNote() {
  state.nt.open = false;
  closePopover();
  applyReading();
  $('#nt-list').innerHTML = state.nt.tab === 'notes' ? notesList() : contactsList();
  $('#panel').scrollTop = 0;
}

function noteAsText(note) {
  const s = note.summary;
  const plain = (t) => String(t || '').replace(/\[\[([^\]]+)\]\]/g, '$1');
  const parts = [note.title, ''];
  if (s) {
    parts.push(plain(s.overview), '');
    if (s.key_points?.length) parts.push('Key points', ...s.key_points.map((p) => `- ${plain(p)}`), '');
    if (s.action_items?.length) parts.push('Action items', ...s.action_items.map((a) => `- ${a.owner ? plain(a.owner) + ': ' : ''}${plain(a.task)}`), '');
  }
  parts.push('Transcript', ...note.lines.map((l) => `[${clock(l.at)}] ${speakerName(l.speaker)}: ${l.text}`));
  return parts.join('\n');
}

// ---------- actions ----------
async function startNotetaker(title, attendees) {
  toast('Starting the notetaker…');
  const result = await call('start_notetaker', title || null, attendees || null);
  if (result.error) {
    return result.engine_off ? toast(result.error, 'Start dictation', () => engineAction('start')) : toast(result.error);
  }
  state.nt.live = result.live;
  state.nt.selected = result.note_id;
  toast('Recording. Utter hears you and the call.');
  await renderNotetaker();
}

async function stopNotetaker() {
  const result = await call('stop_notetaker');
  if (result.error) return toast(result.error);
  if (state.nt.live) state.nt.live.stopping = true;
  refreshNotetakerParts();
}

async function selectNote(id) {
  state.nt.selected = id;
  state.nt.view = 'summary';          // a meeting always opens on its summary, filling the page
  state.nt.open = true;
  closePopover();
  await loadNote();
  refreshNotetakerParts();
}

async function summarizeAgain(backend) {
  const note = state.nt.note;
  if (!note) return;
  const result = await call('summarize_note', note.id, backend || null);
  if (result.error) return toast(result.error);
  state.nt.writingWith = { ...state.nt.writingWith, [note.id]: backend || state.nt.prefs.summarizer };
  await loadNote();
  const listed = state.nt.notes.find((n) => n.id === note.id);
  if (listed) listed.status = 'summarizing';
  refreshNotetakerParts();
}

function renameNote() {
  const note = state.nt.note;
  if (!note) return;
  openFormModal('Rename meeting', '', [['title', 'Title', note.title]], async (values) => {
    const result = await call('rename_note', note.id, values.title);
    if (result.error) return result.error;
    await loadNotetaker();
    refreshNotetakerParts();
  });
}

function deleteNote() {
  const note = state.nt.note;
  if (!note) return;
  const backdrop = $('#backdrop');
  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-label="Delete meeting">
      <h2>Delete this meeting?</h2>
      <p>"${esc(note.title)}": its notes and transcript are removed for good. Contacts stay.</p>
      <div class="modal-actions"><button class="btn" data-close>Cancel</button><button class="btn danger" id="nt-delete-yes">Delete</button></div>
    </div>`;
  backdrop.classList.add('open');
  $('#nt-delete-yes').onclick = async () => {
    const result = await call('delete_note', note.id);
    closeModal(false);
    if (result.error) return toast(result.error);
    state.nt.selected = null;
    state.nt.open = false;
    toast('Meeting deleted.');
    await renderNotetaker();
  };
}

// A small form in the shared modal. submit(values) returns an error message, or nothing when done.
function openFormModal(title, text, fields, submit, extra = '') {
  const backdrop = $('#backdrop');
  backdrop.innerHTML = `
    <div class="modal" role="dialog" aria-label="${esc(title)}">
      <h2>${esc(title)}</h2>
      ${text ? `<p>${text}</p>` : ''}
      ${fields.map(([key, label, value, kind]) => `<div class="field"><label for="ff-${key}">${esc(label)}</label>${kind === 'area'
        ? `<textarea id="ff-${key}" rows="3">${esc(value || '')}</textarea>`
        : `<input id="ff-${key}" value="${esc(value || '')}" autocomplete="off">`}</div>`).join('')}
      ${extra}
      <div class="form-error" id="ff-error"></div>
      <div class="modal-actions"><button class="btn" data-close>Cancel</button><button class="btn primary" id="ff-submit">Save</button></div>
    </div>`;
  backdrop.classList.add('open');
  const first = $('input, textarea', backdrop);
  first.focus();
  first.select?.();
  const go = async () => {
    const values = Object.fromEntries(fields.map(([key]) => [key, $(`#ff-${key}`).value]));
    const error = await submit(values);
    if (error) { $('#ff-error').textContent = error; return; }
    closeModal(false);
  };
  $('#ff-submit').onclick = go;
  $$('input', backdrop).forEach((input) => input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') go(); }));
}

// ---------- contacts ----------
async function openContact(id, prefill = {}, link = null) {
  const contact = id ? await call('get_contact', id) : { ...prefill, notes_met: [] };
  if (contact.error) return toast(contact.error);
  const met = (contact.notes_met || []).map((n) => `<button class="nt-met" data-open-note="${n.id}">${esc(n.title)} <span class="faint">· ${esc(dayOf(n.started_at))}</span></button>`).join('');
  const extra = id ? `
    <div class="field"><label>Meetings</label>${met || '<span class="faint">Not linked to a meeting yet.</span>'}</div>
    <button class="link danger-text" id="contact-delete">Delete contact</button>` : '';
  openFormModal(id ? 'Contact' : 'New contact', '', [
    ['name', 'Name', contact.name], ['email', 'Email', contact.email], ['company', 'Company', contact.company],
    ['notes', 'Notes', contact.notes, 'area'],
  ], async (values) => {
    const result = await call('save_contact', { ...values, id: id || null }, link?.note_id ?? null, link?.mention ?? null);
    if (result.error) return result.error;
    toast(id ? 'Contact saved.' : `${values.name.trim()} saved to contacts.`);
    await refreshAfterContactChange();
  }, extra);
  const remove = $('#contact-delete');
  if (remove) {
    remove.onclick = async () => {
      const result = await call('delete_contact', id);
      if (result.error) return toast(result.error);
      closeModal(false);
      toast(`Deleted ${contact.name}. Their names in notes are unlinked.`);
      await refreshAfterContactChange();
    };
  }
}

async function refreshAfterContactChange() {
  if (state.nt.tab === 'contacts') state.nt.contacts = (await call('get_contacts')).contacts || [];
  await loadNote();
  refreshNotetakerParts();
}

// ---------- mention popover: "Which Jordan Lee is this?" ----------
async function openMention(button) {
  const note = state.nt.note;
  const name = button.dataset.mention;
  const linked = note?.links?.[name];
  const pop = $('#popover');
  if (linked) {
    pop.innerHTML = `
      <div class="pop-contact">
        <span class="avatar">${esc(linked.name[0].toUpperCase())}</span>
        <div><div class="nt-row-title">${esc(linked.name)}</div><div class="nt-row-sub">${esc([linked.company, linked.email].filter(Boolean).join(' · ') || 'Saved contact')}</div></div>
      </div>
      <div class="pop-actions">
        <button class="pop-item" data-pop-open="${linked.id}">${icon('user')}Open contact</button>
        <button class="pop-item" data-pop-unlink="${esc(name)}">${icon('x')}Not this person</button>
      </div>`;
  } else {
    if (!state.nt.contacts.length || state.nt.tab !== 'contacts') state.nt.contacts = (await call('get_contacts')).contacts || [];
    pop.innerHTML = `
      <div class="pop-title">Which ${esc(name)} is this?</div>
      <input class="pop-search" id="pop-search" value="${esc(name)}" autocomplete="off">
      <div id="pop-results"></div>`;
    const input = $('#pop-search');
    const results = () => {
      const q = input.value.trim().toLowerCase();
      const words = q.split(/\s+/).filter(Boolean);
      const matches = state.nt.contacts.filter((c) => words.some((w) => c.name.toLowerCase().includes(w))).slice(0, 5);
      const label = input.value.trim() || name;
      $('#pop-results').innerHTML = matches.map((c) => `
        <button class="pop-item" data-pop-link="${c.id}"><span class="avatar small">${esc(c.name[0].toUpperCase())}</span>
          <span>${esc(c.name)}${c.company ? ` <span class="faint">· ${esc(c.company)}</span>` : ''}</span></button>`).join('')
        + `<button class="pop-item add" data-pop-add="${esc(label)}"><span class="avatar small plus">${icon('plus')}</span>Add new contact "${esc(label)}"</button>`;
    };
    input.oninput = results;
    input.onkeydown = (ev) => { if (ev.key === 'Enter') $('#pop-results .pop-item')?.click(); };
    results();
  }
  pop.dataset.mention = name;
  pop.hidden = false;
  const r = button.getBoundingClientRect();
  const width = 320;
  pop.style.left = `${Math.max(12, Math.min(window.innerWidth - width - 12, r.left + r.width / 2 - width / 2))}px`;
  const below = r.bottom + 8;
  pop.style.top = `${below + pop.offsetHeight > window.innerHeight - 12 ? Math.max(12, r.top - pop.offsetHeight - 8) : below}px`;
  $('#pop-search')?.focus();
  $('#pop-search')?.select();
}

function closePopover() {
  const pop = $('#popover');
  if (pop) { pop.hidden = true; pop.innerHTML = ''; }
}

async function popoverAction(t) {
  const note = state.nt.note;
  const name = $('#popover').dataset.mention;
  if (t.dataset.popLink) {
    const result = await call('link_mention', note.id, name, +t.dataset.popLink);
    closePopover();
    if (result.error) return toast(result.error);
    toast(`Linked ${name}.`);
  } else if (t.dataset.popAdd !== undefined) {
    const label = t.dataset.popAdd;
    const result = await call('save_contact', { name: label }, note.id, name);
    closePopover();
    if (result.error) return toast(result.error);
    toast(`${label} saved to contacts.`, 'Add details', () => openContact(result.id));
  } else if (t.dataset.popUnlink !== undefined) {
    await call('unlink_mention', note.id, name);
    closePopover();
  } else if (t.dataset.popOpen) {
    closePopover();
    return openContact(+t.dataset.popOpen);
  }
  await refreshAfterContactChange();
}

// ---------- polling (from app.js, every second) ----------
let ntPolls = 0;
async function notetakerPoll() {
  ntPolls += 1;
  const recording = !!state.nt.live;
  if (state.page !== 'notetaker') {
    // Keep the sidebar dot right while recording from another page.
    if (recording && ntPolls % 3 === 0) { state.nt.live = (await call('get_live')).live; setNavRecording(); }
    return;
  }
  // "In 5 min" counts down; the calendar itself is read again at most once a minute (cached in Python).
  if (!(ntPolls % 30) && $('#nt-today')) {
    const today = await call('get_today_meetings');
    if (!today.error || today.connected !== undefined) state.nt.today = today;
    $('#nt-today').innerHTML = todayView();
  }
  const waiting = state.nt.notes.some((n) => n.status === 'summarizing' || n.status === 'recording');
  if (!recording && !waiting && ntPolls % 10) return;
  const live = (await call('get_live')).live;
  const ended = recording && !live;
  state.nt.live = live;
  if (ended || (waiting && ntPolls % 2 === 0) || !(ntPolls % 10)) {
    const data = await call('get_notetaker', state.nt.query);
    if (!data.error) state.nt.notes = data.notes;
    await loadNote();
    refreshNotetakerParts();
    return;
  }
  // While recording only the live card, the button and a live detail change.
  if ($('#nt-live')) {
    $('#nt-live').innerHTML = liveView();
    $('#nt-start-slot').innerHTML = startButton();
    if (live && state.nt.note?.id === live.note_id) {
      // Follow new lines unless you scrolled up to read (the open meeting scrolls with the page).
      const panel = $('#panel');
      const stick = !state.nt.open || panel.scrollHeight - panel.scrollTop - panel.clientHeight < 40;
      $('#nt-detail').innerHTML = detailView();
      if (stick && state.nt.open) panel.scrollTop = panel.scrollHeight;
    }
  }
  setNavRecording();
}

// ---------- events ----------
document.addEventListener('click', async (ev) => {
  const pop = $('#popover');
  if (pop && !pop.hidden && !pop.contains(ev.target) && !ev.target.closest('[data-mention]')) closePopover();
  const t = ev.target.closest('button, .nt-row');
  if (!t) return;
  if (t.dataset.page) return showPage(t.dataset.page);
  if (t.dataset.mention) return openMention(t);
  if (t.closest('#popover')) return popoverAction(t);
  if (t.dataset.note) return selectNote(+t.dataset.note);
  if (t.dataset.contact) return openContact(+t.dataset.contact);
  if (t.dataset.contactNew !== undefined) return openContact(null);
  if (t.dataset.openNote) {
    closeModal(false);
    state.nt.tab = 'notes';
    state.nt.selected = +t.dataset.openNote;
    state.nt.view = 'summary';
    state.nt.open = true;
    return renderNotetaker();
  }
  if (t.dataset.ntTab) {
    state.nt.tab = t.dataset.ntTab;
    return renderNotetaker();
  }
  if (t.dataset.ntJoin !== undefined) {
    const meeting = state.nt.today.meetings[+t.dataset.ntJoin];
    if (meeting?.join_url) call('open_url', meeting.join_url);
    return startNotetaker(meeting?.title, meeting?.attendees);
  }
  if (t.dataset.summarize !== undefined) return summarizeAgain(t.dataset.summarize);
  if (t.dataset.ntView) return showView(t.dataset.ntView);
  switch (t.dataset.nt) {
    case 'back': return closeNote();
    case 'start': return startNotetaker();
    case 'stop': return stopNotetaker();
    case 'rename': return renameNote();
    case 'delete': return deleteNote();
    case 'copy': {
      const result = await call('copy_text', noteAsText(state.nt.note));
      return toast(result.error || 'Copied the notes and transcript.');
    }
    default:
  }
});

document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  if (!$('#popover').hidden) closePopover();
  else if (state.page === 'notetaker' && state.nt.open && !$('#backdrop').classList.contains('open')) closeNote();
});
