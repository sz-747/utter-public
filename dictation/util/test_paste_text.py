import asyncio
import importlib
import unittest
from unittest import mock

clipboard = importlib.import_module('util.client.clipboard.clipboard')


class PasteTextTests(unittest.TestCase):
    def setUp(self):
        self.copies = []
        patches = [
            mock.patch.object(clipboard.pyclip, 'copy', side_effect=self.copies.append),
            mock.patch.object(clipboard, 'safe_paste', return_value='what was there before'),
            mock.patch.object(clipboard.keyboard, 'Controller'),
            mock.patch.object(clipboard, 'RESTORE_DELAY', 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def paste(self, keep_output, restore=True):
        with mock.patch.object(clipboard, 'should_keep_output_clipboard', return_value=keep_output):
            asyncio.run(clipboard.paste_text('dictated text', restore_clipboard=restore))

    def test_kept_output_is_written_once_before_ctrl_v(self):
        # A second write right after Ctrl+V collided with the app reading the clipboard.
        self.paste(keep_output=True)
        self.assertEqual(self.copies, ['dictated text'])

    def test_old_clipboard_comes_back_when_output_is_not_kept(self):
        self.paste(keep_output=False)
        self.assertEqual(self.copies, ['dictated text', 'what was there before'])

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
