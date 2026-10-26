import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from util.client.audio.file_manager import AudioFileManager, _NO_WINDOW


class AudioFileManagerTests(unittest.TestCase):
    def test_ffmpeg_is_created_without_a_windows_console(self):
        process = Mock()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                with patch("util.client.audio.file_manager.shutil.which", return_value="ffmpeg"), patch(
                    "util.client.audio.file_manager.Popen", return_value=process
                ) as popen:
                    manager = AudioFileManager()
                    manager.create(channels=1, time_start=0)
            finally:
                os.chdir(previous)

        self.assertEqual(popen.call_args.kwargs["creationflags"], _NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
