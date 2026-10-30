import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from utter.api import Api
from util import learning_status


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'appdata' / 'learning'
        self.folder.mkdir(parents=True)
        self.now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)

    def write(self, name, value):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def snapshot(self, **kwargs):
        return learning_status.snapshot(self.folder, now=self.now, **kwargs)

    def receipt(self, **kwargs):
        return dict(status='completed', started_at=self.now.isoformat(), finished_at=self.now.isoformat(),
                    analysis={'status': 'no_change', 'problem': 'No reproducible defect.',
                              'tests': {'exit_code': 0}}, **kwargs)

    def test_missing_data_is_waiting_not_success(self):
        self.assertEqual(self.snapshot()['state'], 'empty')

    def test_real_yhs_receipt_shape_exposes_tests_without_claiming_improvement(self):
        self.write('last-run.json', self.receipt())
        result = self.snapshot()
        self.assertEqual(result['state'], 'ok')
        self.assertIn('no change', result['label'])
        self.assertIn('not been verified', result['verification'])
        self.assertNotIn('analysis', result)

    def test_inspection_is_not_a_software_review(self):
        self.write('last-inspection.json', dict(status='inspected', started_at=self.now.isoformat()))
        result = self.snapshot()
        self.assertIn('review pending', result['label'])
        self.assertIn('did not judge', result['finding'])

    def test_running_stale_failure_and_disabled_are_visible(self):
        self.write('last-run.json', dict(status='started', started_at=self.now.isoformat()))
        self.assertEqual(self.snapshot()['state'], 'running')
        self.write('last-run.json', dict(status='started', started_at=(self.now-timedelta(hours=4)).isoformat()))
        self.assertEqual(self.snapshot(scheduler={'enabled': True})['state'], 'overdue')
        self.write('last-run.json', dict(status='failed', started_at=self.now.isoformat(), error='private path or stack'))
        result = self.snapshot()
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('private path', str(result))
        self.assertEqual(self.snapshot(scheduler={'enabled': False})['state'], 'disabled')

    def test_recent_inspection_does_not_hide_overdue_review(self):
        self.write('last-run.json', dict(status='completed', finished_at=(self.now-timedelta(days=2)).isoformat()))
        self.write('last-inspection.json', dict(status='inspected', started_at=self.now.isoformat()))
        self.assertEqual(self.snapshot(scheduler={'enabled': True})['state'], 'overdue')
        self.assertEqual(self.snapshot()['state'], 'ok')  # no public scheduler was configured

    def test_corrupt_receipt_reports_incomplete_without_loading_raw_evidence(self):
        (self.folder/'last-run.json').write_text('{broken', encoding='utf-8')
        self.write('runs/one/evidence.json', {'raw_text': 'PRIVATE DICTATION'})
        result = self.snapshot()
        self.assertEqual(result['state'], 'unavailable')
        self.assertNotIn('PRIVATE DICTATION', str(result))

    def test_changed_files_are_not_proof_of_reload_or_benefit(self):
        self.write('last-run.json', self.receipt(changed_files=['util/example.py']))
        result = self.snapshot()
        self.assertIn('still needs verification', result['action'])
        self.assertNotIn('loaded', result['action'])
        self.assertIsNotNone(result['notification'])

    def test_scheduler_failure_does_not_hide_prior_history(self):
        self.write('last-run.json', self.receipt())
        self.write('logs/last-scheduler.json', dict(exit_code=1, inspect_only=False,
                    finished_at=(self.now+timedelta(minutes=1)).isoformat()))
        result = self.snapshot()
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(len(result['items']), 1)

    def test_a_missing_report_is_not_a_failed_review(self):
        # 2026-10-29: the review finished, then its report hit Claude's usage limit; Home said "Daily review failed".
        host = dict(exit_code=1, inspect_only=False, finished_at=(self.now+timedelta(minutes=1)).isoformat())
        legacy = self.receipt(commit='abc', error="Command failed (1): ['python', 'maintenance/build_report.py', '--receipt']; usage_limit_reached")
        legacy['status'] = 'failed'
        for receipt in (legacy, self.receipt(commit='abc', report_pending=True, report_error='usage limit')):
            self.write('last-run.json', receipt)
            self.write('logs/last-scheduler.json', host)
            result = self.snapshot()
            self.assertEqual(result['state'], 'ok')
            self.assertIn('no change', result['label'])
            self.assertIn('report could not be built yet', result['action'])
            self.assertIsNone(result['notification'])
            self.assertNotIn('usage', str(result))

    def test_a_failure_after_the_code_result_that_is_not_the_report_stays_failed(self):
        receipt = self.receipt(commit='abc', error='Client restart failed; code committed, runtime unverified')
        receipt['status'] = 'failed'
        self.write('last-run.json', receipt)
        self.assertEqual(self.snapshot()['state'], 'failed')

    def test_api_returns_owner_view(self):
        result = Api(root=self.root).get_improvements()
        self.assertEqual(result['state'], 'empty')
        self.assertIn('No automatic daily review', result['schedule'])

    def test_history_bounded_and_duplicate_latest_receipt_removed(self):
        self.write('last-run.json', self.receipt())
        self.write('runs/000/receipt.json', self.receipt())
        for number in range(1, 12):
            self.write(f'runs/{number:03}/receipt.json', dict(status='idle', started_at=(self.now-timedelta(hours=number)).isoformat()))
        result = self.snapshot()
        self.assertEqual(len(result['items']), 8)
        self.assertEqual(sum(item['at'] == self.now.isoformat() for item in result['items']), 1)
