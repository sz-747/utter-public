# coding: utf-8
"""
Diary subpackage.

Writes the dictation diary.
"""

from .. import logger
from util.client.diary.diary_writer import DiaryWriter

__all__ = [
    'logger',
    'DiaryWriter',
]
