"""
Write LLM conversations to Markdown

Saves the user's input and the LLM's polished result to a Markdown file
"""
import time
from pathlib import Path
from os import makedirs

from util.llm.llm_role_config import RoleConfig


# Header of an LLM conversation log file
header_llm_md = r'''# LLM conversation log

'''


def create_llm_md(file_md: Path):
    """Create an LLM conversation log file"""
    with open(file_md, 'w', encoding="utf-8") as f:
        f.write(header_llm_md)


def write_llm_md(input_text: str, polished_text: str, role_name: str, time_start: float, file_audio: Path = None):
    """
    Append an LLM conversation to the Markdown file

    Args:
        input_text: the user's input (recognition result)
        polished_text: the text after LLM polish
        role_name: role name
        time_start: start timestamp
        file_audio: audio file path (optional)
    """
    # Format the time
    time_year = time.strftime('%Y', time.localtime(time_start))
    time_month = time.strftime('%m', time.localtime(time_start))
    time_day = time.strftime('%d', time.localtime(time_start))
    time_hms = time.strftime('%H:%M:%S', time.localtime(time_start))

    # Folder: year/month/ (the same place as the diary)
    folder_path = Path() / time_year / time_month
    makedirs(folder_path, exist_ok=True)

    # File name: day-role.md (the default role uses the default role name)
    role_name_for_file = role_name if role_name else RoleConfig.DEFAULT_ROLE_NAME
    file_md = folder_path / f'{time_day}-{role_name_for_file}.md'

    # Make sure the md file exists
    if not file_md.exists():
        create_llm_md(file_md)

    # Write the entry
    with open(file_md, 'a', encoding="utf-8") as f:
        # Heading: time + audio link (if any)
        if file_audio:
            audio_filename = file_audio.name
            f.write(f'#### [[{time_hms}]](({audio_filename})\n\n')
        else:
            f.write(f'#### [{time_hms}]\n\n')

        # User input
        f.write(f'**Input**: {input_text}\n\n')

        # LLM output
        f.write(f'**Output**: {polished_text}\n\n')

        # Divider
        f.write('---\n\n')
