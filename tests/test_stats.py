import unittest
from datetime import date
from pathlib import Path

from utter import stats


def _row(day, raw, duration=10.0, app=None, title=None, fixes=None, output=None):
    return {'started_at': f'{day}T10:00:00+00:00', 'raw_text': raw, 'output_text': output or raw,
            'duration': duration, 'app_process': app, 'app_title': title, 'fixes': fixes or [],
            'day': date.fromisoformat(day), 'words': len((output or raw).split()), 'spoken_words': len(raw.split())}


class InsightsTests(unittest.TestCase):
    def test_streaks_wpm_and_month_change(self):
        rows = [
            _row('2026-09-28', 'one two three four five', duration=6),
            _row('2026-10-21', 'a b c', duration=3),
            _row('2026-10-22', 'a b c d', duration=6),
            _row('2026-10-23', 'a b c d e f', duration=6),
        ]
        result = stats.insights(rows, [], today=date(2026, 10, 24))
        self.assertEqual(result['streak'], {'current': 3, 'longest': 3})
        self.assertEqual(result['wpm'], round(18 / (21 / 60)))
        self.assertEqual(result['words_this_month'], 13)
        self.assertEqual(result['month_change_percent'], 160)
        self.assertEqual(result['today']['dictations'], 0)

    def test_streak_breaks_after_a_missed_day(self):
        rows = [_row('2026-10-20', 'x'), _row('2026-10-21', 'x')]
        self.assertEqual(stats.insights(rows, [], today=date(2026, 10, 24))['streak'], {'current': 0, 'longest': 2})

    def test_categories_apps_and_fixes(self):
        rows = [
            _row('2026-10-24', 'ask claude', app='chrome.exe', title='Claude - Google Chrome',
                 fixes=[{'kind': 'dictionary', 'from': 'cloud', 'to': 'Claude'}]),
            _row('2026-10-24', 'hi team', app='slack.exe', title='Slack',
                 fixes=[{'kind': 'rule', 'from': 'Cud', 'to': 'Claude'}, {'kind': 'ai', 'words': 4}]),
            _row('2026-10-24', 'old row'),
        ]
        result = stats.insights(rows, [{'learned_at': 'x', 'heard': 'a', 'corrected': 'b'}], today=date(2026, 10, 24))
        counts = {c['key']: c['count'] for c in result['categories']}
        self.assertEqual((counts['ai'], counts['messages'], counts['other']), (1, 1, 1))
        self.assertEqual(result['fixes'], {'dictionary': 1, 'rules': 1, 'ai_words': 4, 'learned': 1, 'total': 6})
        self.assertEqual(result['total_apps'], 2)
        words, rules = stats.fix_counts(rows)
        self.assertEqual(words['Claude'], 1)
        self.assertEqual(rules[('Cud', 'Claude')], 1)

    def test_time_saved_against_typing_speed(self):
        rows = [_row('2026-10-24', ' '.join(['w'] * 120), duration=60)]
        self.assertEqual(stats.insights(rows, [], typing_wpm=60)['time_saved']['minutes'], 1.0)
        self.assertEqual(stats.insights(rows, [], typing_wpm=240)['time_saved']['minutes'], -0.5)

    def test_cleanup_ratio_by_app(self):
        rows = [
            _row('2026-10-24', 'um so fix the bug', app='code.exe', output='Fix the bug.'),
            _row('2026-10-24', 'run the tests', app='code.exe'),
            _row('2026-10-24', 'hello there', app='slack.exe'),
        ]
        cleanup = {a['name']: a for a in stats.insights(rows, [])['cleanup']}
        # "um", "so" dropped and "bug" -> "bug." changed: 3 of 8 spoken words.
        self.assertEqual((cleanup['VS Code']['changed_words'], cleanup['VS Code']['percent']), (3, 38))
        self.assertEqual(cleanup['Slack']['percent'], 0)

    def test_learning_curve_from_learned_corrections(self):
        def at(day, hour):
            return f'{day}T{hour:02d}:00:00+00:00'
        rows = [
            _row('2026-10-23', 'open codecs now', output='Open codecs now.'),
            _row('2026-10-24', 'ask codecs and the MCPP', output='Ask Codex and the MCP.'),
            _row('2026-10-24', 'press Control twice', output='press control twice'),
        ]
        rows[1]['started_at'] = at('2026-10-24', 12)
        rows[2]['started_at'] = at('2026-10-24', 12)
        learned = [
            {'learned_at': at('2026-10-23', 11), 'heard': 'codecs', 'corrected': 'Codex', 'kind': 'word'},
            {'learned_at': at('2026-10-23', 11), 'heard': 'codecs', 'corrected': 'Codex', 'kind': 'rule'},
            {'learned_at': at('2026-10-24', 11), 'heard': 'MCPP', 'corrected': 'MCP', 'kind': 'word'},
            {'learned_at': at('2026-10-24', 11), 'heard': 'Control', 'corrected': 'control', 'kind': 'word'},
        ]
        result = stats.insights(rows, learned, today=date(2026, 10, 24))['learning']
        self.assertEqual(result['learned_corrections'], 3)
        # codecs first heard 10-23 (before it was learned) and missed; the 10-24 hits come after and are caught.
        self.assertEqual(result['before_learned'], {'seen': 1, 'caught': 0, 'percent': 0})
        self.assertEqual(result['after_learned'], {'seen': 3, 'caught': 3, 'percent': 100})
        by_day = {d['day']: d for d in result['days']}
        self.assertEqual((by_day['2026-10-23']['new_mishearings'], by_day['2026-10-23']['new_per_1k']), (1, 333.3))
        self.assertEqual(by_day['2026-10-24']['new_mishearings'], 2)
        self.assertEqual((by_day['2026-10-24']['known_seen'], by_day['2026-10-24']['known_caught']), (3, 3))

    def test_empty_archive(self):
        result = stats.insights([], [], today=date(2026, 10, 24))
        self.assertIsNone(result['wpm'])
        self.assertEqual(result['total_words'], 0)
        self.assertEqual(stats.load_rows(Path('does-not-exist.sqlite3')), ([], []))


if __name__ == '__main__':
    unittest.main()
