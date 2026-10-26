import os
import unittest
from unittest import mock

from util.client.output import focus
from util.logger import Logger


class TypingTargetTests(unittest.TestCase):
    def test_target_in_front_types_as_usual(self):
        self.assertEqual(focus.decide(100, 100, 7, 1), 'ok')

    def test_unknown_target_types_as_usual(self):
        self.assertEqual(focus.decide(0, 200, 7, 1), 'ok')

    def test_own_overlay_in_front_gives_focus_back(self):
        self.assertEqual(focus.decide(100, 200, 1, 1), 'restore')

    def test_nothing_in_front_gives_focus_back(self):
        self.assertEqual(focus.decide(100, 0, 0, 1), 'restore')

    def test_another_app_in_front_is_only_logged(self):
        self.assertEqual(focus.decide(100, 200, 7, 1), 'moved')

    def test_before_typing_never_raises(self):
        focus.remember({'hwnd': 123, 'process_name': 'x.exe'})
        self.addCleanup(focus.remember, None)
        with mock.patch.object(focus, 'logger'), mock.patch('win32gui.GetForegroundWindow', side_effect=OSError('no desktop')):
            focus.before_typing()


class TestLogLocationTests(unittest.TestCase):
    def test_test_runs_do_not_write_the_client_log(self):
        logger = Logger.setup('test-run-logger-location')
        paths = [h.baseFilename for h in logger.handlers if hasattr(h, 'baseFilename')]
        self.assertTrue(paths)
        self.assertTrue(all('utter-test-logs' in p for p in paths), paths)
        self.assertFalse(any(os.sep + 'logs' + os.sep + 'client_' in p for p in paths))


if __name__ == '__main__':
    unittest.main()
