"""Read-only presentation of learning receipts. Owns the learning-file contract."""
import json
from datetime import datetime, timezone
from pathlib import Path


def _read(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Receipt is outside the learning folder')
    if not path.exists():
        return None
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Receipt is too large')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Receipt must be an object')
    return value


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def _text(value, fallback):
    return value.strip()[:900] if isinstance(value, str) and value.strip() else fallback


def report_pending(receipt) -> bool:
    """The review finished and only its written report is missing. Older runs recorded that as a
    failure after the code result was committed (2026-10-29: the report hit Claude's usage limit)."""
    receipt = receipt or {}
    if receipt.get('status') == 'completed' and receipt.get('report_pending'):
        return True
    return (receipt.get('status') == 'failed' and bool(receipt.get('commit'))
            and isinstance(receipt.get('analysis'), dict) and 'build_report.py' in str(receipt.get('error', '')))


def _review(receipt, key):
    analysis = receipt.get('analysis')
    analysis = analysis if isinstance(analysis, dict) else {}
    tests = analysis.get('tests')
    tests = tests if isinstance(tests, dict) else {}
    pending_report = report_pending(receipt)
    state = 'completed' if pending_report else receipt.get('status')
    result = analysis.get('status')
    changed = bool(receipt.get('changed_files'))
    label = {'started': 'Review in progress', 'failed': 'Review needs attention',
             'idle': 'No new evidence', 'inspected': 'Evidence checked'}.get(state, 'Review completed')
    if state == 'completed' and result == 'no_change':
        label = 'Reviewed · no change justified'
    elif state == 'completed' and changed:
        label = 'Change prepared · benefit pending'
    action = 'No software change was made.'
    if state == 'started':
        action = 'Reviewing recent dictations and runtime evidence.'
    elif state == 'failed':
        action = 'The review did not finish. Its result needs investigation.'
    elif changed:
        action = 'A code change was recorded; its effect on everyday use still needs verification.'
        if receipt.get('runtime_restart_exit') == 0:
            action = 'The change was loaded by the dictation client; everyday results still need verification.'
        elif receipt.get('runtime_restart_exit') is not None:
            action = 'A code change was recorded, but the client reload was not confirmed.'
    if pending_report:
        action += ' The written report could not be built yet; the next daily review retries it.'
    verification = 'No user-experience improvement has been verified.'
    if type(tests.get('exit_code')) is int and tests['exit_code'] == 0:
        verification = 'Code tests passed. Real-use improvement has not been verified.'
    return dict(id=key, at=receipt.get('finished_at') or receipt.get('started_at'), label=label,
                changed=changed, finding=_text(analysis.get('problem'), 'No new finding was recorded.'),
                action=action, verification=verification, state=state)


def snapshot(root, *, now=None, scheduler=None):
    """No raw dictations, evidence packets, window content, commands or paths returned."""
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    scheduler = scheduler or {}
    base = dict(state='empty', label='Waiting for the first review', checked_at=None,
                finding='No completed review is available yet.',
                action='Your next daily review will appear here.',
                verification='No improvement has been verified.',
                schedule='No automatic daily review is configured in this public build.', items=[])
    issues = []

    def read(name):
        try:
            return _read(root, name)
        except (OSError, ValueError):
            issues.append(name)
            return None

    latest = read('last-run.json')
    inspection = read('last-inspection.json')
    host = read('logs/last-scheduler.json')
    items = []
    if latest:
        items.append(_review(latest, 'latest-review'))
    runs = root / 'runs'
    if runs.is_dir():
        for run in sorted(runs.iterdir(), key=lambda p: p.name, reverse=True)[:20]:
            if not run.is_dir():
                continue
            relative = run.relative_to(root)
            receipt = read(relative / 'receipt.json')
            if receipt and receipt.get('status') != 'inspected':
                entry = _review(receipt, run.name)
                if not any(e['at'] == entry['at'] and e['label'] == entry['label'] for e in items):
                    items.append(entry)
    items.sort(key=lambda e: _date(e['at']) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    base['items'] = [{k: v for k, v in e.items() if k not in ('state', 'changed')} for e in items[:8]]
    if items:
        item = items[0]
        base.update({k: item[k] for k in ('label', 'finding', 'action', 'verification')})
        base['checked_at'] = item['at']
        base['state'] = {'started': 'running', 'failed': 'failed'}.get(item['state'], 'ok')
    elif inspection:
        base.update(state='ok', label='Evidence collected · review pending',
                    checked_at=inspection.get('started_at'),
                    finding='An evidence-only check completed; it did not judge or fix the software.',
                    action='Waiting for the daily software review.')

    # A more recent failure or stuck run must remain visible even if old results exist.
    if latest and latest.get('status') in ('started', 'failed') and not report_pending(latest):
        item = _review(latest, 'latest-review')
        base.update({k: item[k] for k in ('label', 'finding', 'action', 'verification')})
        base.update(checked_at=item['at'], state='running' if latest['status'] == 'started' else 'failed')
    reviewed_at = _date((latest or {}).get('finished_at') or (latest or {}).get('started_at'))
    if base['state'] == 'running' and reviewed_at and (now - reviewed_at).total_seconds() > 3 * 3600:
        base.update(state='overdue', label='Review taking longer than expected', action='The last review has no completion result. It needs investigation.')
    elif (base['state'] in ('ok', 'empty') and scheduler.get('enabled') is True
          and reviewed_at and (now - reviewed_at).total_seconds() > 26 * 3600):
        base.update(state='overdue', label='Daily review overdue', action='No recent daily review is recorded. Check that this PC was awake and signed in.')
    # The scheduler's failed exit belongs to that run's missing report, not to a failed review.
    if host and host.get('inspect_only') is False and host.get('exit_code') not in (None, 0) and not report_pending(latest):
        host_at = _date(host.get('finished_at'))
        if host_at and (not reviewed_at or host_at > reviewed_at):
            base.update(state='failed', label='Daily review failed', action='The scheduled review failed. Its last successful findings remain in history.')
    if issues:
        base.update(state='unavailable', label='Some review records could not be read',
                    error='Review data is incomplete. Try again; previously readable results remain in history.')
    if scheduler.get('enabled') is False:
        base.update(state='disabled', label='Daily review is disabled', action='Automatic reviews are paused in Windows Task Scheduler.')
    elif scheduler.get('available') is False:
        base['schedule'] += ' Schedule status could not be checked.'
    base['notification'] = None
    if base['state'] in ('failed', 'overdue', 'disabled'):
        base['notification'] = dict(id=base['state'] + ':' + str(base['checked_at']), text=base['label'])
    elif items and items[0].get('changed') and items[0]['state'] == 'completed':
        base['notification'] = dict(id='change:' + str(items[0]['at']), text='Utter recorded a software change. Check its verification in Utter improvements.')
    return base
