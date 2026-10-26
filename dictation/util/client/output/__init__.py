# coding: utf-8
"""
Output subpackage.

Handles delivering recognition results.
"""

from .. import logger
from util.client.output.result_processor import ResultProcessor
from util.client.output.text_output import TextOutput

__all__ = [
    'logger',
    'ResultProcessor',
    'TextOutput',
]
