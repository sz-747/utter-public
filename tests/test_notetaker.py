import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from utter import meeting, notes, summary
from utter.api import Api


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'notes.sqlite3'
        self.store = notes.Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_note_lifecycle_search_and_titles(self):
        auto = self.store.create_note(None, 1000)
        named = self.store.create_note('Priya & Sam 1:1', 2000)
        self.store.add_line(auto, 'others', 3.2, 'the launch moved to Friday')
        self.store.add_line(auto, 'me', 1.0, 'hi Jordan')
        self.assertEqual([l['text'] for l in self.store.lines(auto)], ['hi Jordan', 'the launch moved to Friday'])

        self.store.set_summary(auto, {'title': 'Quarterly Planning', 'overview': 'x'}, 'codex')
        self.store.set_summary(named, {'title': 'Something else', 'overview': 'y'}, 'local')
        self.assertEqual(self.store.get_note(auto)['title'], 'Quarterly Planning')   # generated title replaces the default
        self.assertEqual(self.store.get_note(named)['title'], 'Priya & Sam 1:1')  # a calendar title is kept
        self.assertEqual([n['id'] for n in self.store.list_notes()], [named, auto])
        self.assertEqual([n['id'] for n in self.store.list_notes('launch moved')], [auto])

        self.assertTrue(self.store.delete_note(auto))
        self.assertEqual(self.store.lines(auto), [])

    def test_open_notes_are_closed_after_a_restart(self):
        note = self.store.create_note(None, 1000)
        reopened = notes.Store(self.path)
        self.assertEqual(reopened.get_note(note)['status'], 'failed')

    def test_contacts_and_links(self):
        note = self.store.create_note(None, 1000)
        jordan = self.store.save_contact({'name': ' Jordan Lee ', 'company': 'Brightloop'})
        with self.assertRaises(ValueError):
            self.store.save_contact({'name': ''})
        self.store.link(note, 'Jordan', jordan)
        self.assertEqual(self.store.get_note(note)['links']['Jordan']['name'], 'Jordan Lee')
        listed = self.store.list_contacts()[0]
        self.assertEqual((listed['name'], listed['meetings']), ('Jordan Lee', 1))
        self.assertEqual([n['id'] for n in self.store.get_contact(jordan)['notes_met']], [note])

        self.store.save_contact({'id': jordan, 'name': 'Jordan Lee', 'email': 'jordan@example.com'})
        self.assertEqual(self.store.get_contact(jordan)['email'], 'jordan@example.com')
        self.assertTrue(self.store.delete_contact(jordan))
        self.assertEqual(self.store.get_note(note)['links'], {})   # deleting a contact unlinks its names

    def test_prefs_default_and_validate(self):
        self.assertEqual(self.store.prefs(), {'summarizer': 'codex', 'call_popup': 'on'})
        self.store.set_pref('summarizer', 'local')
        self.assertEqual(self.store.prefs()['summarizer'], 'local')
        with self.assertRaises(ValueError):
            self.store.set_pref('summarizer', 'gpt')


class SummaryTests(unittest.TestCase):
    LINES = [{'speaker': 'me', 'at': 2, 'text': 'Hi Jordan.'},
             {'speaker': 'others', 'at': 65, 'text': 'Hi Alex, the launch moved to Friday.'}]

    def test_transcript_names_the_speakers(self):
        self.assertEqual(summary.transcript_text(self.LINES, 'Alex'),
                         '[00:02] Alex: Hi Jordan.\n[01:05] Others: Hi Alex, the launch moved to Friday.')

    def test_people_are_marked_by_code_not_by_the_model(self):
        reply = json.dumps({'title': 'Planning', 'overview': 'Alex met Jordan Lee of [[OpenAI]]. Jordan said no.',
                            'key_points': ['Alexander is someone else'], 'people': ['Jordan Lee', 'Jordan'],
                            'action_items': [{'owner': 'Alex', 'task': 'Send the slides to Jordan'}]})
        notes_ = summary.parse(f'Sure!\n```json\n{reply}\n```', me='Alex')
        self.assertEqual(notes_['overview'], '[[Alex]] met [[Jordan Lee]] of OpenAI. [[Jordan]] said no.')
        self.assertEqual(notes_['key_points'], ['Alexander is someone else'])
        self.assertEqual(notes_['action_items'], [{'owner': '[[Alex]]', 'task': 'Send the slides to [[Jordan]]'}])

    def test_non_people_from_small_models_are_not_marked(self):
        reply = json.dumps({'title': 't', 'overview': 'Alex met Jordan Lee, José and Søren of the Brightloop design team at MIT.',
                            'key_points': [], 'action_items': [],
                            'people': ['Others', 'The Others', 'Brightloop design team', 'MIT', 'OpenAI',
                                       'Jordan Lee', 'José', 'Søren', "Mary O'Brien", 'Ronald McDonald']})
        self.assertEqual(summary.parse(reply, me='Alex')['overview'],
                         '[[Alex]] met [[Jordan Lee]], [[José]] and [[Søren]] of the Brightloop design team at MIT.')
        self.assertTrue(summary.looks_like_person("Mary O'Brien") and summary.looks_like_person('Ronald McDonald'))

    def test_lm_studio_is_started_when_its_server_is_off(self):
        config = type('C', (), {'provider': 'openai', 'model': 'm', 'api_url': 'http://127.0.0.1:1234/v1', 'api_key': 'k'})
        ok = mock.Mock(**{'json.return_value': {'choices': [{'message': {'content': 'hi'}}]}})
        with mock.patch.object(summary.requests, 'post', side_effect=[summary.requests.ConnectionError(), ok]), \
             mock.patch.object(summary, '_local_ai_tried', 0.0), \
             mock.patch.object(summary.Path, 'exists', return_value=True), \
             mock.patch.object(summary.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(summary.ask_local('p', None, config), 'hi')
        self.assertEqual(run.call_args.args[0][1:], ['server', 'start'])

    def test_ollama_is_started_when_it_is_off(self):
        config = type('C', (), {'provider': 'ollama', 'model': 'm', 'api_url': ''})
        ok = mock.Mock(**{'json.return_value': {'message': {'content': 'hi'}}})
        with mock.patch.object(summary.requests, 'post', side_effect=[summary.requests.ConnectionError(), ok]), \
             mock.patch.object(summary, '_local_ai_tried', 0.0), \
             mock.patch.object(summary.shutil, 'which', return_value='ollama.exe'), \
             mock.patch.object(summary.socket, 'create_connection'), \
             mock.patch.object(summary.subprocess, 'Popen') as popen:
            self.assertEqual(summary.ask_local('p', None, config), 'hi')
        self.assertEqual(popen.call_args.args[0], ['ollama.exe', 'serve'])

    def test_bad_json_is_retried_once(self):
        good = json.dumps({'title': 't', 'overview': 'o', 'key_points': [], 'action_items': [], 'people': []})
        replies = iter(['{"title": "broken', good])
        result = summary.summarize(self.LINES, 'Alex', [], 'codex', ask=lambda prompt, schema=None: next(replies))
        self.assertEqual(result['title'], 't')

    def test_long_meetings_are_summarized_in_parts_for_local_models(self):
        lines = [{'speaker': 'others', 'at': i, 'text': 'word ' * 40} for i in range(200)]
        prompts = []

        def ask(prompt, schema=None):
            prompts.append((prompt, schema))
            return json.dumps({'title': 't', 'overview': 'o', 'key_points': [], 'action_items': [], 'people': []}) if schema else '- notes'

        summary.summarize(lines, 'Alex', [], 'local', ask=ask)
        self.assertGreater(len(prompts), 2)
        self.assertTrue(all(schema is None for _, schema in prompts[:-1]))
        self.assertIn('- notes', prompts[-1][0])
        self.assertLess(len(prompts[-1][0]), 4000)

    def test_nothing_said_is_an_error(self):
        with self.assertRaises(summary.SummaryError):
            summary.summarize([], 'Alex', [], ask=lambda *a: '')

    def test_local_openai_style_server_gets_the_schema(self):
        config = type('C', (), {'provider': 'openai', 'model': 'm', 'api_url': 'http://127.0.0.1:1234/v1', 'api_key': 'k',
                                'extra_options': {'extra_body': {'reasoning_effort': 'none'}}})
        response = mock.Mock(**{'json.return_value': {'choices': [{'message': {'content': 'hi'}}]}})
        with mock.patch.object(summary.requests, 'post', return_value=response) as post:
            self.assertEqual(summary.ask_local('p', summary.SCHEMA, config), 'hi')
        url, body = post.call_args.args[0], post.call_args.kwargs['json']
        self.assertEqual(url, 'http://127.0.0.1:1234/v1/chat/completions')
        self.assertEqual(body['response_format']['json_schema']['schema'], summary.SCHEMA)
        self.assertEqual(body['reasoning_effort'], 'none')


def tone(seconds, level=0.1):
    t = np.arange(int(seconds * meeting.RATE)) / meeting.RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class SegmenterTests(unittest.TestCase):
    def feed_all(self, audio, seg=None):
        seg = seg or meeting.Segmenter()
        out = []
        for i in range(0, len(audio), 1600):
            out += seg.feed(audio[i:i + 1600])
        return out + seg.flush()

    def test_cuts_at_pauses_and_drops_silence(self):
        quiet = np.zeros(int(1.0 * meeting.RATE), dtype=np.float32)
        audio = np.concatenate([quiet, tone(3), quiet, tone(4), quiet, quiet])
        cuts = self.feed_all(audio)
        self.assertEqual(len(cuts), 2)
        self.assertAlmostEqual(cuts[0][0], 1.0, places=1)    # starts where the speech starts
        self.assertAlmostEqual(cuts[1][0], 5.0, delta=0.1)

    def test_long_speech_is_cut_at_the_maximum(self):
        cuts = self.feed_all(tone(45))
        self.assertEqual(len(cuts), 3)
        self.assertTrue(all(len(samples) / meeting.RATE <= meeting.MAX_SECONDS + 0.05 for _, samples in cuts))

    def test_quiet_noise_is_not_sent(self):
        self.assertEqual(self.feed_all(tone(3, level=0.008)), [])

    def test_wall_clock_keeps_time_across_gaps(self):
        seg = meeting.Segmenter()
        seg.feed(tone(3), at=0.0)
        cuts = seg.flush() + seg.feed(tone(3), at=60.0) + seg.flush()
        self.assertAlmostEqual(cuts[1][0], 60.0, places=1)

    def test_resampling_to_mono_16k(self):
        stereo48 = np.repeat(tone(1), 3 * 2)    # 48 kHz, two channels
        self.assertEqual(len(meeting.to_mono_16k(stereo48, 2, 48000)), meeting.RATE)
        self.assertEqual(len(meeting.to_mono_16k(np.zeros(44100, np.float32), 1, 44100)), meeting.RATE)


class TranscriberTests(unittest.TestCase):
    """The speech-server protocol, against a fake server built with websockets."""

    def test_utterances_round_trip_through_the_server(self):
        from websockets.sync.server import serve

        received = []

        def handler(ws):
            for raw in ws:
                message = json.loads(raw)
                received.append(message)
                samples = len(message['data']) * 3 // 4 // 4
                ws.send(json.dumps({'task_id': 'other', 'is_final': True, 'text': 'not mine'}))
                ws.send(json.dumps({'task_id': message['task_id'], 'is_final': True, 'text': f' {samples} samples '}))

        with serve(handler, '127.0.0.1', 0) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            port = server.socket.getsockname()[1]
            got = []
            transcriber = meeting.Transcriber(f'127.0.0.1:{port}', lambda *a: got.append(a), context='Jordan Lee')
            transcriber.submit('me', 1.5, tone(1))
            transcriber.submit('others', 3.0, tone(2))
            self.assertTrue(transcriber.close(timeout=10))
            server.shutdown()
        self.assertEqual(got, [('me', 1.5, '16000 samples'), ('others', 3.0, '32000 samples')])
        self.assertTrue(all(m['is_final'] and m['context'] == 'Jordan Lee' for m in received))


class FakeRecorder:
    def __init__(self, transcriber, preferred_mic=None, started_at=None):
        self.transcriber = transcriber
        self.devices = {'me': 'Headset', 'others': 'Speakers'}
        self.errors = {}

    def start(self):
        pass

    def levels(self):
        return {'me': 0.0, 'others': 0.0}

    def stop(self):
        self.transcriber.on_text('others', 4.0, 'the launch moved to Friday')


class ApiNotetakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = Api(notes_path=Path(self.tmp.name) / 'notes.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_requires_the_speech_engine(self):
        with mock.patch('utter.engine.server_status', return_value={'listening': False}):
            result = self.api.start_notetaker()
        self.assertTrue(result.get('engine_off'))

    def test_record_stop_and_summarize(self):
        real_session = meeting.Session

        def fake_session(*args, **kwargs):
            return real_session(*args, **kwargs, recorder_factory=FakeRecorder)

        written = {'title': 'Planning', 'overview': '[[Alex]] asked.', 'key_points': [], 'action_items': []}
        with mock.patch('utter.engine.server_status', return_value={'listening': True, 'address': '0.0.0.0:1'}), \
             mock.patch('utter.engine.client_status', return_value={'running': False}), \
             mock.patch.object(meeting, 'Session', side_effect=fake_session), \
             mock.patch.object(summary, 'summarize', return_value=written) as summarize:
            started = self.api.start_notetaker('Priya & Sam 1:1')
            self.assertTrue(started['ok'], started)
            self.assertIn('error', self.api.start_notetaker())            # one meeting at a time
            self.assertIn('error', self.api.delete_note(started['note_id']))
            self.assertEqual(self.api.stop_notetaker()['note_id'], started['note_id'])
            for _ in range(100):
                note = self.api.get_note(started['note_id'])
                if note['status'] == 'done':
                    break
                time.sleep(0.05)
        self.assertEqual(note['status'], 'done', note)
        self.assertEqual(note['title'], 'Priya & Sam 1:1')
        self.assertEqual([l['text'] for l in note['lines']], ['the launch moved to Friday'])
        self.assertEqual(summarize.call_args.args[3], 'codex')            # the default summarizer
        self.assertIsNone(self.api.get_live()['live'])

    def test_today_meetings_come_from_google_calendar(self):
        from utter import google_calendar
        events = [
            {'title': 'Priya & Sam 1:1', 'start': '2026-10-25T10:00:00+00:00', 'end': '2026-10-25T10:30:00+00:00',
             'all_day': False, 'attendees': ['Priya Nair', 'sam@example.com'], 'meeting_link': None,
             'location': 'https://us02web.zoom.us/j/123?pwd=abc', 'description': None},
            {'title': 'Holiday', 'start': '2026-10-25', 'end': '2026-10-26', 'all_day': True, 'attendees': []},
        ]
        with mock.patch.object(google_calendar, 'status', return_value={'connected': False}):
            self.assertEqual(self.api.get_today_meetings(), {'connected': False, 'meetings': []})
        with mock.patch.object(google_calendar, 'status', return_value={'connected': True}), \
             mock.patch.object(google_calendar, 'events', return_value=events) as read:
            today = self.api.get_today_meetings()
            self.api.get_today_meetings()
        self.assertEqual(read.call_count, 1)                       # cached for a minute
        self.assertEqual([m['title'] for m in today['meetings']], ['Priya & Sam 1:1'])   # all-day events skipped
        self.assertEqual(today['meetings'][0]['join_url'], 'https://us02web.zoom.us/j/123?pwd=abc')
        with mock.patch.object(google_calendar, 'status', return_value={'connected': True}), \
             mock.patch.object(google_calendar, 'events', side_effect=OSError('offline')):
            self.assertIn('offline', self.api.get_today_meetings(refresh=True)['error'])

        # An old copy comes back at once (the page must not wait ~2 s for Google) and is read again behind it.
        self.api._today = (time.time() - 120, today)
        later = [dict(events[0], title='Moved meeting')]
        with mock.patch.object(google_calendar, 'status', return_value={'connected': True}), \
             mock.patch.object(google_calendar, 'events', return_value=later):
            self.assertEqual(self.api.get_today_meetings()['meetings'][0]['title'], 'Priya & Sam 1:1')
            for _ in range(100):
                if self.api._today[1]['meetings'][0]['title'] == 'Moved meeting':
                    break
                time.sleep(0.02)
            self.assertEqual(self.api.get_today_meetings()['meetings'][0]['title'], 'Moved meeting')

    def test_invited_people_reach_the_speech_model_and_the_summary(self):
        real_session = meeting.Session
        sessions = []

        def fake_session(*args, **kwargs):
            sessions.append(real_session(*args, **kwargs, recorder_factory=FakeRecorder))
            return sessions[-1]

        with mock.patch('utter.engine.server_status', return_value={'listening': True, 'address': '127.0.0.1:1'}), \
             mock.patch('utter.engine.client_status', return_value={'running': False}), \
             mock.patch.object(meeting, 'Session', side_effect=fake_session), \
             mock.patch.object(summary, 'summarize', return_value={'title': 't', 'overview': 'o', 'key_points': [],
                                                                     'action_items': []}) as summarize:
            started = self.api.start_notetaker('Priya & Sam 1:1', ['Priya Nair', 'sam@example.com'])
            self.assertTrue(sessions[0].transcriber.context.startswith('Priya Nair'))
            self.api.stop_notetaker()
            for _ in range(100):
                if self.api.get_note(started['note_id'])['status'] == 'done':
                    break
                time.sleep(0.05)
        self.assertEqual(self.api.get_note(started['note_id'])['attendees'], ['Priya Nair'])
        self.assertEqual(summarize.call_args.kwargs['invited'], ['Priya Nair'])

    def test_contact_from_a_mention(self):
        note = self.api._notes.create_note(None, 1000)
        saved = self.api.save_contact({'name': 'Jordan Lee'}, note, 'Jordan')
        self.assertEqual(self.api.get_note(note)['links']['Jordan']['id'], saved['id'])
        self.assertEqual(self.api.unlink_mention(note, 'Jordan'), {'ok': True})
        self.assertIn('error', self.api.save_contact({'name': ' '}))
        self.assertIn('error', self.api.summarize_note(note, 'gpt'))


if __name__ == '__main__':
    unittest.main()
