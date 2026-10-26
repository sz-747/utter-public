# coding: utf-8
import re
import json
from pathlib import Path
from typing import Dict, Any

from config_client import ClientConfig as Config
from util.tools import srt_from_txt
from . import logger

class ResultHandler:
    """Result handler: formats the text and saves the files."""

    @staticmethod
    def smart_split(text: str) -> str:
        """
        Split text into subtitle lines
        1. Keeps the punctuation while splitting
        2. Avoids splitting very short pieces at commas
        3. Only splits at punctuation followed by whitespace or the end (so 3.14 stays whole)
        """
        # The capture group keeps the punctuation; it must be followed by whitespace or the end
        parts = re.split(r'([.,?!](?:\s+|$))', text)
        lines = []
        buffer = ""

        # Strong punctuation always ends a line
        strong_punct = {'.', '?', '!'}
        punct_chars = set(r',.?!')

        for part in parts:
            clean_part = part.strip()
            # A single punctuation character
            if clean_part and clean_part in punct_chars and len(clean_part) == 1:
                buffer += part
                is_strong = clean_part in strong_punct
                # End the line at strong punctuation, or once the buffer is long enough
                if is_strong or len(buffer) > 15:
                    lines.append(buffer)
                    buffer = ""
            else:
                # Text
                buffer += part

        if buffer:
            lines.append(buffer)

        # Strip trailing punctuation from each line
        final_lines = []
        for line in lines:
            line = line.strip()
            while line and line[-1] in punct_chars:
                line = line[:-1].strip()
            if line:
                final_lines.append(line)

        return "\n".join(final_lines)

    @classmethod
    def save_results(cls, file: Path, message: Dict[str, Any]) -> str:
        """
        Save the transcription result to files.

        Returns:
            The text to display
        """
        text_display = message['text']
        text_accu = message.get('text_accu', message['text'])
        text_split = cls.smart_split(text_accu)
        timestamps = message['timestamps']
        tokens = message['tokens']

        # File names
        json_filename = file.with_suffix('.json')
        txt_filename = file.with_suffix('.txt')
        merge_filename = file.with_suffix('.merge.txt')

        # 1. Save merge.txt
        if Config.file_save_merge:
            with open(merge_filename, 'w', encoding='utf-8') as f:
                f.write(text_accu)
            logger.debug(f"Saved merged text: {merge_filename}")

        # 2. Save the txt
        if Config.file_save_txt:
            with open(txt_filename, 'w', encoding='utf-8') as f:
                f.write(text_split)
            logger.debug(f"Saved split text: {txt_filename}")

        # 3. Save the json
        if Config.file_save_json:
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump({'timestamps': timestamps, 'tokens': tokens}, f, ensure_ascii=False)
            logger.debug(f"Saved JSON result: {json_filename}")

        # 4. Generate the srt
        if Config.file_save_srt:
            # Build the word timings directly (no need for the json file)
            words = [{'word': token.replace('@', ''), 'start': timestamp, 'end': timestamp + 0.2}
                     for (timestamp, token) in zip(timestamps, tokens)]
            for i in range(len(words) - 1):
                words[i]['end'] = min(words[i]['end'], words[i+1]['start'])

            text_lines = text_split.splitlines()
            srt_filename = file.with_suffix('.srt')

            srt_from_txt.generate_srt_file(words, text_lines, srt_filename)

        # 5. Remove the intermediate txt
        if not Config.file_save_txt and txt_filename.exists():
            try:
                txt_filename.unlink()
                logger.debug(f"Removed intermediate TXT file: {txt_filename}")
            except Exception as e:
                logger.warning(f"Could not remove intermediate TXT file: {e}")

        return text_display
