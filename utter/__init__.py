"""Utter: a desktop window over the dictation client in ../dictation."""
__version__ = '0.2.0'

from . import dictation  # noqa: E402

# Importing any Utter module needs the client's modules on the path.
dictation.attach()
