# Decision surfaces

Product choices Utter has made. Reopen one only with new evidence or a changed scope.

## DS-001 Home is status and recent dictations; Insights, Dictionary and Notetaker are their own pages
- **Question:** What does Home show, and what gets a page of its own?
- **Why it matters:** Home is what you check to see whether dictation works and to recover something that went to the wrong place; statistics and a long word list would push that down.
- **Current behavior:** Home has the greeting, a large dictation banner (state, microphone, shortcuts, Stop/Restart) with the Utter logo animating as a wave, and the latest dictations for copy-paste recovery. AI polish shows in the banner only when its model server is not answering. On Start/Restart the banner stays in place: a headset with a spinner until the client is ready, then the microphone's name. Each sidebar item (Home, Insights, Dictionary, Notetaker) opens its own page; the Dictionary page shows its word list straight away. No full transcript history or search page.
- **Reopen trigger:** A history or search view is needed.

## DS-002 One repo; the dictation client owns the file formats
- **Question:** Where do the window and the dictation client live, and who owns the shared files?
- **Why it matters:** Two owners of the archive, settings, status and dictionary formats drift apart, and a change that touches both the window and the client should land in one commit.
- **Current behavior:** One repo. `dictation/` is the client (forked from CapsWriter-Offline) and `utter/` is the window. Utter imports the client's own modules (`config_client`, `util.app_settings`, `util.dictionary_files`, `util.text_metrics`, the archive) through `utter/dictation.py` instead of copying them. Client-side behavior (status heartbeat, live settings, learning, sounds) stays in `dictation/` because it runs inside the client. `tests/test_client_formats.py` checks every format Utter reads or writes against the client's real code.
- **Reopen trigger:** The client needs to ship without the window, or the window with another engine.

## DS-003 Google Calendar feeds the Utter MCP and the Notetaker's Today card
- **Question:** What does a connected Google Calendar do in Utter?
- **Why it matters:** Feeding attendee names into the dictionary would change dictation behavior everywhere, not just in meetings.
- **Current behavior:** Read-only (`calendar.readonly`). The MCP's `list_meetings` adds the dictations made during each timed event. The Notetaker page reads today's timed events (cached a minute): the current or next one gets a "Join meeting & start notetaker" card that opens its Meet/Zoom/Teams link and starts recording with the event's title. Invited names go to the speech model and the summary for that meeting only, never into the dictation dictionary. Sign-in uses your own Google Cloud OAuth client (Desktop app); the refresh token lives in Windows Credential Manager.
- **Reopen trigger:** Names from meetings should be spelled right while dictating too.

## DS-004 The Utter MCP is read-only
- **Question:** What may an AI read or change through the Utter MCP?
- **Why it matters:** Everything a tool returns goes to that AI's provider; write tools would let a model change your dictionary unseen.
- **Current behavior:** Four read-only tools: `search_dictations`, `get_insights`, `get_dictionary`, `list_meetings`. No write tools. Clients start `python -m utter.mcp_server` on this PC over stdio; nothing listens on the network.
- **Reopen trigger:** An AI should add dictionary words, or reach Utter from another device.

## DS-005 LM Studio gets the same MCP locally, through its own mcp.json
- **Question:** How does a local model use the Utter MCP?
- **Why it matters:** A local model keeps dictations on the PC, but LM Studio's API can only call mcp.json servers with "Require Authentication" on, which would break AI polish (the client calls LM Studio without a token).
- **Current behavior:** "Add to LM Studio" writes one `utter` entry into `~/.lmstudio/mcp.json` (other servers untouched; invalid JSON is left alone). LM Studio starts `python -m utter.mcp_server` itself over stdio, so there's no tunnel or key. Use it from LM Studio chats with `mcp/utter` switched on. Each app's last use is tracked separately (`UTTER_MCP_CLIENT`). LM Studio picks the model per chat, so Utter shows the loaded model (`lms ps`, asked only while LM Studio runs) and records which model was loaded at each call; it warns under 16K context.
- **Reopen trigger:** Scripts or agents should reach Utter through LM Studio's API.

## DS-006 Coding agents are how a cloud model reads dictations
- **Question:** How does a cloud model read your dictations without a public server?
- **Why it matters:** A public endpoint would expose the dictation archive to the internet; coding agents run on this PC and can start the MCP over stdio with logins you already have.
- **Current behavior:** Codex, Claude Code and Pi each list an `utter` server in their own MCP config (see INSTALL.md); `UTTER_MCP_CLIENT` in that entry's environment makes each app's last use show separately. Utter's MCP page shows a read-only "Coding agents" card (it never writes their configs) and the LM Studio card. What an agent reads goes to its model's provider.
- **Reopen trigger:** Access from a phone or the web is needed.

## DS-007 Notetaker is its own page, records without a bot, keeps text only
- **Question:** Where does the notetaker live, what does it record, and what does it keep?
- **Why it matters:** A meeting is longer and involves other people; a bot joining the call, saved audio or a Home section would each change privacy and layout.
- **Current behavior:** A Notetaker page in the sidebar (DS-001) with two columns. On the left: Start notes, today's calendar meetings (the next one can be joined from its row), and your notes, with People (contacts) as a second tab. On the right: the open note, the newest one until you pick another, on its summary, with Summary and Transcript tabs under the title. It records the microphone dictation uses as "me" and WASAPI loopback of the default speakers as "Others", cuts at pauses, and transcribes on the local speech server. Audio is never written to disk; transcript lines are saved as they arrive. Devices are chosen when recording starts. Utter owns this one store (`%APPDATA%\Utter\notetaker.sqlite3`), outside the client's formats (DS-002).
- **Reopen trigger:** Saved audio, names for each person on the other side, or devices that switch mid-meeting.

## DS-008 Notetaker AI: the local model or the Codex app server only
- **Question:** Which AI writes meeting notes, and may meeting text leave the PC?
- **Why it matters:** Transcripts include other people's words. A local model keeps them on the PC; Codex is stronger but sends the text to OpenAI.
- **Current behavior:** Two backends only. Default is Codex: gpt-6-luna at medium effort, pinned in `utter/summary.py`, through `codex app-server` (ephemeral read-only thread, approvals declined, JSON schema enforced). The other is the AI polish model on this PC (`dictation/LLM/default.py`; long meetings are summarized in parts; LM Studio's server is started when it is off), chosen in Settings > Notetaker or per note from "Use Local AI" when Codex fails. Settings and Data and privacy label Codex Online. Codex runs on whatever ChatGPT account the Codex CLI is signed in to; Settings > Notetaker shows only that email and a Switch account button, which runs the app server's ChatGPT sign-in in the browser and replaces the CLI login only when sign-in finishes. In testing, a 9B local model got meeting facts wrong where Codex did not, which is why Codex is the default.
- **Reopen trigger:** Another backend is requested, gpt-6-luna is retired, or meetings should stay on this PC by default.

## DS-009 Contacts link to names per meeting, by your choice
- **Question:** How does a name in the notes become a saved contact?
- **Why it matters:** Matching by name alone would silently merge two people with the same first name; asking every time is noise.
- **Current behavior:** The AI lists the people it named and Utter marks them. Unlinked names are orange dotted; clicking one asks "Which X is this?" with matching contacts and "Add new contact". A link is stored per meeting and name and survives rewriting the notes. Linked names are purple; clicking shows the contact and "Not this person". Contact names and dictionary words go to the speech model as context, which helps it spell names right.
- **Reopen trigger:** Contacts should link automatically, or match calendar attendees.

## DS-010 Offer to take notes when a call starts (call detection, not the calendar)
- **Question:** When should Utter offer to start the notetaker without being opened?
- **Why it matters:** A popup that fires on calendar times alone misses unscheduled calls and nags for events with no call; one that fires on any microphone use would interrupt dictation.
- **Current behavior:** Every 3 s Utter checks which apps are using the microphone (Windows privacy consent store) and the window titles. A browser using the mic with a window titled "Meet - ..." is a Google Meet; Zoom or Teams using the mic is a call. A small always-on-top window (bottom-right, draggable) offers "Start Notetaker"; X dismisses it for that call. If today's calendar has the same Meet code (or a Zoom/Teams event happening now), the note gets that event's title and invited names. While recording it shows a timer with Stop and Open. It goes away 20 s after the call disappears. Settings > Notetaker can turn it off. A calendar-time reminder was not built.
- **Reopen trigger:** A reminder before calendar events, Meet tabs behind other tabs detected, or the notetaker stopping by itself when the call ends.

## DS-011 English only
- **Question:** Which languages does dictation support?
- **Why it matters:** The upstream client carries Chinese-specific processing (pinyin restoration, simplified/traditional conversion, Chinese numbers and punctuation); each language needs its own tuning and tests.
- **Current behavior:** English only. The speech model is told the speaker speaks English, AI polish and the AI reviewer are prompted for English, and the dictionary matcher works on English letters and digits. There is no language setting.
- **Reopen trigger:** Someone tunes and tests another language end to end.
