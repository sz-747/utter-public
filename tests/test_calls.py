import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from utter import api as api_module, meeting, meeting_detect
from utter.api import Api
from tests.test_notetaker import FakeRecorder

EDGE_MEET = ('msedge.exe', 'Meet - abc-defg-hij and 6 more pages - Personal - Microsoft​ Edge')


class FindCallTests(unittest.TestCase):
    def test_google_meet_in_a_browser_using_the_microphone(self):
        call = meeting_detect.find_call({'msedge.exe', 'pythonw.exe'}, [EDGE_MEET, ('code.exe', 'Meet - notes.md - Visual Studio Code')])
        self.assertEqual(call, {'key': 'meet:abc-defg-hij', 'app': 'Google Meet', 'name': 'abc-defg-hij', 'code': 'abc-defg-hij'})
        named = meeting_detect.find_call({'chrome.exe'}, [('chrome.exe', 'Meet – Weekly sync - Google Chrome')])
        self.assertEqual((named['name'], named['code']), ('Weekly sync', None))

    def test_no_call_without_the_microphone_or_the_meet_window(self):
        self.assertIsNone(meeting_detect.find_call({'pythonw.exe'}, [EDGE_MEET]))              # Meet open, mic not in use
        self.assertIsNone(meeting_detect.find_call({'msedge.exe'}, [('msedge.exe', 'YouTube - Microsoft Edge')]))
        self.assertIsNone(meeting_detect.find_call({'code.exe'}, [('code.exe', 'Meet - x - Visual Studio Code')]))

    def test_zoom_and_teams_apps(self):
        self.assertEqual(meeting_detect.find_call({'zoom.exe'}, [])['app'], 'Zoom')
        self.assertEqual(meeting_detect.find_call({'MSTeams_8wekyb3d8bbwe'}, [])['app'], 'Microsoft Teams')

    def test_a_meet_tab_behind_another_tab(self):
        tabs = [('msedge.exe', 'YouTube'), ('msedge.exe', 'Meet - abc-defg-hij - Camera or microphone recording')]
        windows = [('msedge.exe', 'YouTube - Personal - Microsoft Edge')]
        self.assertEqual(meeting_detect.find_call({'msedge.exe'}, windows, tabs)['key'], 'meet:abc-defg-hij')  # same key as the title
        self.assertIsNone(meeting_detect.find_call({'pythonw.exe'}, windows, tabs))                            # the browser is not on the mic
        self.assertIsNone(meeting_detect.find_call({'msedge.exe'}, windows, [('msedge.exe', 'Google Meet')]))  # Meet's home page

    def test_tabs_are_read_only_while_a_browser_uses_the_microphone(self):
        with mock.patch.object(meeting_detect, 'apps_using_microphone', return_value={'pythonw.exe': 1}), \
                mock.patch.object(meeting_detect, 'visible_windows', return_value=[]), \
                mock.patch.object(meeting_detect, 'browser_tabs') as tabs:
            self.assertIsNone(meeting_detect.current_call())
        tabs.assert_not_called()

    def test_telegram_counts_only_after_a_voice_message_would_have_ended(self):
        started_at = 1_800_000_000
        start = (started_at + meeting_detect._FILETIME_UNIX_START) * 10_000_000
        mic = {'telegram.exe': start, 'zoom.exe': start}
        self.assertEqual(meeting_detect.without_short_use(mic, started_at + 3), {'zoom.exe'})
        self.assertEqual(meeting_detect.without_short_use(mic, started_at + 10), {'telegram.exe', 'zoom.exe'})
        self.assertEqual(meeting_detect.find_call({'telegram.exe'}, [])['app'], 'Telegram')
        packaged = 'TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm'
        self.assertEqual(meeting_detect.find_call({packaged}, [])['app'], 'Telegram')
        self.assertEqual(meeting_detect.without_short_use({packaged: start}, started_at + 3), set())


class ZoomTests(unittest.TestCase):
    def test_zoom_is_clamped_remembered_and_applied(self):
        from utter import local_state
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(local_state, 'STATE_DIR', Path(tmp)):
            api = Api(notes_path=Path(tmp) / 'n.sqlite3')
            self.assertEqual(api.get_zoom(), 1.0)
            applied = []
            api._apply_zoom = applied.append
            self.assertEqual(api.set_zoom(1.25)['zoom'], 1.25)
            self.assertEqual(api.set_zoom(9)['zoom'], 2.5)
            self.assertEqual(applied, [1.25, 2.5])
            self.assertEqual(Api(notes_path=Path(tmp) / 'n.sqlite3').get_zoom(), 2.5)   # remembered after a restart


class PopupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = Api(notes_path=Path(self.tmp.name) / 'n.sqlite3')
        self.shown = []
        self.api._popup = {'show': lambda: self.shown.append(True), 'hide': lambda: self.shown.append(False),
                           'open_main': mock.Mock(), 'shown': False}
        self.call = meeting_detect.find_call({'msedge.exe'}, [EDGE_MEET])
        self.calendar = mock.patch.object(Api, 'get_today_meetings', return_value={'meetings': []})
        self.calendar.start()

    def tearDown(self):
        self.calendar.stop()
        self.tmp.cleanup()

    def test_offer_then_hide_when_the_call_ends(self):
        self.assertTrue(self.api._check_call(self.call))
        self.assertEqual(self.api.get_call_popup()['mode'], 'offer')
        self.assertEqual(self.api.get_call_popup()['call']['title'], 'Google Meet')
        self.api._check_call(False)                                       # briefly gone: tab switch
        self.assertEqual(self.shown, [True])
        with mock.patch.object(api_module.time, 'time', return_value=time.time() + api_module.CALL_GONE_SECONDS + 1):
            self.assertFalse(self.api._check_call(False))
        self.assertEqual(self.shown, [True, False])

    def test_dismiss_does_not_offer_the_same_call_again(self):
        self.api._check_call(self.call)
        self.api.dismiss_call()
        self.assertFalse(self.api._check_call(self.call))
        self.assertEqual(self.shown, [True, False])

    def test_a_closed_telegram_offer_does_not_silence_the_next_call(self):
        call = meeting_detect.find_call({'telegram.exe'}, [])
        self.api._check_call(call)
        self.api.dismiss_call()
        self.assertFalse(self.api._check_call(call))                     # the same call
        with mock.patch.object(api_module.time, 'time', return_value=time.time() + api_module.CALL_GONE_SECONDS + 1):
            self.api._check_call(False)                                  # it ended
        self.assertTrue(self.api._check_call(call))                      # the next one is offered

    def test_a_telegram_call_does_not_take_the_name_of_an_event_happening_now(self):
        now = datetime.now().astimezone()
        event = {'title': 'Week-long hackathon', 'start': (now - timedelta(days=1)).isoformat(),
                 'end': (now + timedelta(days=1)).isoformat(), 'join_url': '', 'attendees': ['Someone Else']}
        self.calendar.stop()
        self.calendar = mock.patch.object(Api, 'get_today_meetings', return_value={'meetings': [event]})
        self.calendar.start()
        self.api._check_call(meeting_detect.find_call({'telegram.exe'}, []))
        self.assertEqual((self.api._call['title'], self.api._call['attendees']), ('Telegram', []))

    def test_turned_off_in_settings(self):
        self.api.set_notetaker_pref('call_popup', 'off')
        self.assertFalse(self.api._check_call(self.call))
        self.assertEqual(self.shown, [])

    def test_calendar_event_names_the_call_and_recording_keeps_the_popup(self):
        now = datetime.now().astimezone()
        event = {'title': 'Priya & Sam 1:1', 'start': (now - timedelta(minutes=1)).isoformat(),
                 'end': (now + timedelta(minutes=29)).isoformat(),
                 'join_url': 'https://meet.google.com/abc-defg-hij', 'attendees': ['Priya Nair']}
        self.calendar.stop()
        self.calendar = mock.patch.object(Api, 'get_today_meetings', return_value={'meetings': [event]})
        self.calendar.start()
        self.api._check_call(self.call)
        self.assertEqual(self.api._call['title'], 'Priya & Sam 1:1')

        real_session = meeting.Session
        with mock.patch('utter.engine.server_status', return_value={'listening': True, 'address': '127.0.0.1:1'}), \
             mock.patch('utter.engine.client_status', return_value={'running': False}), \
             mock.patch.object(meeting, 'Session', side_effect=lambda *a, **k: real_session(*a, **k, recorder_factory=FakeRecorder)):
            started = self.api.start_call_notes()
        self.assertTrue(started['ok'], started)
        note = self.api.get_note(started['note_id'])
        self.assertEqual((note['title'], note['attendees']), ('Priya & Sam 1:1', ['Priya Nair']))
        self.assertEqual(self.api.get_call_popup()['mode'], 'recording')
        self.assertTrue(self.api._check_call(self.call))                 # stays up while it records
        self.api._session.stop()
        self.api._session = None
        self.assertFalse(self.api._check_call(self.call))                # and goes once it stops, without offering again


if __name__ == '__main__':
    unittest.main()
