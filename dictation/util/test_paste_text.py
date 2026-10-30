import asyncio
import importlib
import threading
import unittest
from unittest import mock

clipboard = importlib.import_module('util.client.clipboard.clipboard')


class PasteTextTests(unittest.TestCase):
    def setUp(self):
        self.clip = ['what was there before']        # the clipboard's history; last is current
        patches = [
            mock.patch.object(clipboard.pyclip, 'copy', side_effect=self.clip.append),
            mock.patch.object(clipboard, 'safe_paste', side_effect=lambda: self.clip[-1]),
            mock.patch.object(clipboard.keyboard, 'Controller'),
            mock.patch.object(clipboard, 'RESTORE_DELAY', 0),
            mock.patch.object(clipboard, '_LANDING_POLL', 0),
            mock.patch.object(clipboard, '_field_reader', return_value=None),
            mock.patch.dict(clipboard._restore, {'generation': 0, 'original': ''}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def paste(self, keep_output, restore=True, text='dictated text'):
        with mock.patch.object(clipboard, 'should_keep_output_clipboard', return_value=keep_output):
            asyncio.run(clipboard.paste_text(text, restore_clipboard=restore))

    def wait_for_restores(self):
        for thread in threading.enumerate():
            if thread.name == 'clipboard-restore':
                thread.join(5)

    def field(self, reads):
        """A readable input field: the text before Ctrl+V, then what each later read sees."""
        reads = iter(reads)
        return mock.patch.object(clipboard, '_field_reader', return_value=lambda: next(reads))

    def test_kept_output_is_written_once_before_ctrl_v(self):
        # A second write right after Ctrl+V collided with the app reading the clipboard.
        self.paste(keep_output=True)
        self.assertEqual(self.clip[1:], ['dictated text'])

    def test_old_clipboard_comes_back_when_output_is_not_kept(self):
        self.paste(keep_output=False)
        self.wait_for_restores()
        self.assertEqual(self.clip[1:], ['dictated text', 'what was there before'])

    def test_old_clipboard_waits_until_the_dictation_is_in_the_field(self):
        # A busy app can read the clipboard seconds after Ctrl+V.
        reads = ['Hi '] + ['Hi '] * 5 + ['Hi dictated text']
        with self.field(reads):
            self.paste(keep_output=False)
            self.wait_for_restores()
        self.assertEqual(self.clip[-1], 'what was there before')

    def test_a_dictation_that_never_shows_up_stays_on_the_clipboard(self):
        with self.field(['Hi '] * 10_000), mock.patch.object(clipboard, 'LANDING_TIMEOUT', 0.05):
            self.paste(keep_output=False)
            self.wait_for_restores()
        self.assertEqual(self.clip[-1], 'dictated text')

    def test_something_copied_meanwhile_is_not_overwritten(self):
        def reads():
            yield 'Hi '
            self.clip.append('https://example.com/link')   # the user copies a link
            while True:
                yield 'Hi dictated text'
        gen = reads()
        with mock.patch.object(clipboard, '_field_reader', return_value=lambda: next(gen)):
            self.paste(keep_output=False)
            self.wait_for_restores()
        self.assertEqual(self.clip[-1], 'https://example.com/link')

    def test_back_to_back_dictations_give_back_what_was_copied_first(self):
        hold = threading.Event()

        def slow_reads():
            yield ''
            hold.wait(5)
            while True:
                yield ''                                # the first one never shows up before the second
        gen = slow_reads()
        with mock.patch.object(clipboard, '_field_reader', return_value=lambda: next(gen)):
            self.paste(keep_output=False, text='first')
        with self.field(['', 'second']):
            self.paste(keep_output=False, text='second')
            hold.set()
            self.wait_for_restores()
        self.assertEqual(self.clip[-1], 'what was there before')

    def test_landing_ignores_line_breaks_and_text_already_there(self):
        self.assertTrue(clipboard._landed('', 'one\r\ntwo', 'one\ntwo'))
        self.assertFalse(clipboard._landed('dictated text', 'dictated text', 'dictated text'))
        self.assertTrue(clipboard._landed('dictated text', 'dictated text dictated text', 'dictated text'))

    def test_a_busy_clipboard_is_retried(self):
        attempts = []

        def busy_once(text):
            attempts.append(text)
            if len(attempts) == 1:
                raise OSError((1418, 'EmptyClipboard', 'Thread does not have a clipboard open.'))

        with mock.patch.object(clipboard.pyclip, 'copy', side_effect=busy_once), \
                mock.patch.object(clipboard, 'should_keep_output_clipboard', return_value=True), \
                mock.patch.object(clipboard.asyncio, 'sleep', new=mock.AsyncMock()):
            asyncio.run(clipboard.paste_text('dictated text'))
        self.assertEqual(attempts, ['dictated text', 'dictated text'])
        clipboard.keyboard.Controller.return_value.tap.assert_called_once_with('v')


if __name__ == '__main__':
    unittest.main()
