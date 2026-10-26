# coding: utf-8
"""
Rule corrector

Exact replacements with regular expressions, for fixed formats (units, symbols, layouts).

Example:
```python
corrector = RuleCorrector()
corrector.update_rules('''
milliamp hours = mAh
(\\w+)\\s+at\\s+(\\w+)\\s+dot\\s+com = \\1@\\2.com
''')

corrector.substitute('a 5000 milliamp hours battery')  # 'a 5000 mAh battery'
corrector.substitute('mail sam at example dot com')    # 'mail sam@example.com'
```
"""

import re
from threading import Lock
from typing import Dict


class RuleCorrector:
    """Rule corrector: exact regular-expression replacements"""

    def __init__(self):
        self.patterns: Dict[str, str] = {}
        self._lock = Lock()

    def update_rules(self, rule_text: str) -> int:
        """
        Replace the rules (thread-safe)

        Args:
            rule_text: one rule per line, "pattern = replacement"

        Returns:
            the number of rules loaded
        """
        new_patterns = {}

        for line in rule_text.splitlines():
            if not line or line.startswith('#'):
                continue

            # "pattern =" with nothing after it deletes the match (editors often trim the trailing space)
            if line.rstrip().endswith(' =') and line.count(' = ') == 0:
                line = line.rstrip() + ' '
            parts = line.split(' = ')
            if len(parts) == 2:
                pattern = parts[0].strip()
                replacement = parts[1].strip()
                new_patterns[pattern] = replacement

        with self._lock:
            self.patterns = new_patterns

        return len(new_patterns)

    def substitute(self, text: str) -> str:
        """
        Apply the rules

        Args:
            text: original text

        Returns:
            the text after replacement
        """
        if not text or not self.patterns:
            return text

        result = text

        with self._lock:
            patterns = self.patterns.copy()

        for pattern, replacement in patterns.items():
            try:
                result = re.sub(pattern, replacement, result)
            except Exception:
                # skip invalid regular expressions
                pass

        return result

    def substitute_with_log(self, text: str):
        """
        Apply the rules and record each replacement that changed something

        Returns:
            (text after replacement, [(original fragment, replacement), ...])
        """
        if not text or not self.patterns:
            return text, []

        result = text
        log = []

        with self._lock:
            patterns = self.patterns.copy()

        for pattern, replacement in patterns.items():
            def _replace(match, replacement=replacement):
                new = match.expand(replacement)
                if new != match.group(0):
                    log.append((match.group(0), new))
                return new
            try:
                result = re.sub(pattern, _replace, result)
            except Exception:
                # skip invalid regular expressions
                pass

        return result, log
