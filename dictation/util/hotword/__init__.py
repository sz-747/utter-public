# coding: utf-8
"""
Dictionary

Dictionary replacement and correction:
- PhonemeCorrector: phoneme-based corrector
- RuleCorrector: regular-expression rules
- RectificationRAG: correction history search
- HotwordManager: dictionary manager (singleton)
"""

from util import get_logger
logger = get_logger('client')


from .hot_phoneme import PhonemeCorrector, CorrectionResult
from .hot_rule import RuleCorrector
from .hot_rectification import RectificationRAG
from .manager import HotwordManager, get_hotword_manager

__all__ = [
    'PhonemeCorrector',
    'CorrectionResult',
    'RuleCorrector',
    'RectificationRAG',
    'HotwordManager',
    'get_hotword_manager',
]
