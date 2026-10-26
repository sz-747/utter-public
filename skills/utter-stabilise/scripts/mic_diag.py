"""Diagnose Utter's dictation microphone problems (the dictation client in ../dictation).

Kind: diagnostic helper, run by hand or by an agent following SKILL.md; no automatic trigger.

    python mic_diag.py report [--client <dictation folder>] [--days 3] [--device AirPods]
    python mic_diag.py live [--device AirPods] [--seconds 6]     # needs sounddevice (in the repo venv)

Without --client, the folder is this repo's dictation/. `report` is read-only and offline: it reads
the client's logs and capture reports, and on Windows the Audio/Operational event log (event 65)
through wevtutil. `live` opens the microphone for a few seconds, measures what arrives, and saves nothing.
Exit codes: 0 report printed, 2 bad arguments or missing client folder, 3 live test could not open the mic.
"""
from __future__ import annotations

import argparse
import array
import json
import re
import subprocess
import sys
import time
import wave
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SILENT_PEAK = 0.02          # int16 peak / 32768 below this: the mic sent silence, not speech
BURST = timedelta(seconds=60)
EVENT_NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}

_TIME = r'^(\d{2}:\d{2}:\d{2}\.\d+) '
# The client's own log lines (util/client/shortcut/task.py, audio/capture_log.py, output/result_processor.py)
START = re.compile(_TIME + r'.*Pressed: recording started')
STOP = re.compile(_TIME + r'.*Released: recording finished')
LOSS = re.compile(_TIME + r'.*Audio lost: held ([\d.]+)s, mic delivered ([\d.]+)s.*?s: (.*?)(?:;|$)')
RESULT = re.compile(_TIME + r'.*Final result: (.*?), delay')
SKIPPED = re.compile(_TIME + r'.*Skipping empty recording task')

CLASSES = {
    'ok': 'text came back',
    'partial_audio': 'Bluetooth link starved: mic delivered only part of the audio',
    'no_audio': 'mic delivered no audio at all (unplugged, asleep or still connecting)',
    'silent_mic': 'mic delivered full-length audio that was silence, so no words came back',
    'client_bug': 'audio arrived but did not reach recognition (dictation client bug)',
    'empty_result': 'no words came back; audio not captured, cause unknown (quiet or very short speech?)',
}


@dataclass
class Recording:
    start: datetime
    stop: datetime | None = None
    held: float | None = None
    delivered: float | None = None
    verdict: str = ''
    text: str | None = None
    skipped: bool = False
    peak: float | None = None
    kind: str = 'ok'
    minutes_after_connect: float | None = None
    mic_active: bool | None = None
    notes: list = field(default_factory=list)


# ---------- log parsing ----------

def parse_logs(log_dir: Path, since: date) -> list[Recording]:
    """Recordings from client_YYYYMMDD.log files. A file keeps logging past midnight, so the
    date advances whenever the clock goes backwards."""
    recordings: list[Recording] = []
    for log in sorted(log_dir.glob('client_*.log')):
        try:
            day = datetime.strptime(log.stem.split('_')[1], '%Y%m%d').date()
        except (IndexError, ValueError):
            continue
        if day < since - timedelta(days=1):
            continue
        previous = None
        current: Recording | None = None
        for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
            m = re.match(_TIME, line)
            if not m:
                continue
            clock = datetime.strptime(m.group(1), '%H:%M:%S.%f').time()
            if previous and clock < previous and (previous.hour - clock.hour) >= 12:
                day += timedelta(days=1)
            previous = clock
            at = datetime.combine(day, clock)
            if START.match(line):
                current = Recording(start=at)
                recordings.append(current)
            elif current is None:
                continue
            elif STOP.match(line):
                current.stop = at
            elif (loss := LOSS.match(line)):
                current.held, current.delivered = float(loss.group(2)), float(loss.group(3))
                current.verdict = loss.group(4).strip()
            elif SKIPPED.match(line):
                current.skipped = True
            elif (result := RESULT.match(line)) and current.text is None:
                current.text = result.group(2)
    return [r for r in recordings if r.start.date() >= since]


# ---------- capture reports ----------

def wav_peak(path: Path) -> float | None:
    try:
        with wave.open(str(path)) as w:
            if w.getsampwidth() != 2:
                return None
            samples = array.array('h', w.readframes(w.getnframes()))
    except (OSError, EOFError, wave.Error):
        return None
    return max((abs(s) for s in samples), default=0) / 32768


def attach_captures(recordings: list[Recording], capture_dir: Path) -> None:
    """Capture files are named by recording start; take held/delivered from them when the log had none."""
    if not capture_dir.is_dir():
        return
    for report in capture_dir.glob('*.json'):
        try:
            at = datetime.strptime(report.stem, '%Y%m%d-%H%M%S')
            data = json.loads(report.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        match = min(recordings, key=lambda r: abs((r.start - at).total_seconds()), default=None)
        if not match or abs((match.start - at).total_seconds()) > 3:
            continue
        match.held = match.held if match.held is not None else data.get('held')
        match.delivered = match.delivered if match.delivered is not None else data.get('delivered')
        match.verdict = match.verdict or ('' if data.get('verdict') == 'ok' else data.get('verdict', ''))
        audio = report.with_suffix('.wav')
        if audio.exists():
            match.peak = wav_peak(audio)


# ---------- Windows audio endpoint events ----------

def read_endpoint_events() -> list[dict] | None:
    """Audio/Operational event 65 (endpoint state changes) as dicts, oldest first; None off Windows
    or when wevtutil fails."""
    try:
        out = subprocess.run(['wevtutil', 'qe', 'Microsoft-Windows-Audio/Operational',
                              '/q:*[System[(EventID=65)]]', '/f:xml', '/e:Events'],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return parse_endpoint_events(out.stdout.decode('utf-8', errors='replace'))


def parse_endpoint_events(xml_text: str) -> list[dict]:
    events = []
    for event in ET.fromstring(xml_text).findall('e:Event', EVENT_NS):
        created = event.find('e:System/e:TimeCreated', EVENT_NS)
        # Field names vary in case between Windows builds ('Flow' vs 'flow').
        data = {(d.get('Name') or '').lower(): (d.text or '') for d in event.findall('e:EventData/e:Data', EVENT_NS)}
        if created is None:
            continue
        stamp = created.get('SystemTime', '').rstrip('Z')
        stamp = re.sub(r'(\.\d{6})\d+', r'\1', stamp)          # Windows writes 7 fractional digits
        when = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        events.append({'time': when, 'device': data.get('devicename', ''),
                       'flow': data.get('flow', ''), 'state': data.get('newstate', '')})
    return sorted(events, key=lambda e: e['time'])


def mic_connects(events: list[dict], device: str) -> list[datetime]:
    """Times the device's input endpoint became active; a burst within a minute is one connect."""
    connects: list[datetime] = []
    for e in events:
        if device.lower() in e['device'].lower() and e['flow'] == '1' and e['state'] == '1':
            if connects and e['time'] - connects[-1] < BURST:
                connects[-1] = e['time']
            else:
                connects.append(e['time'])
    return connects


def mic_active_at(events: list[dict], device: str, at: datetime) -> bool | None:
    """Whether the input endpoint was up at `at`. Windows logs bursts of 8/1 within a second, so a
    burst counts as up when it contains a '1'."""
    mine = [e for e in events if device.lower() in e['device'].lower() and e['flow'] == '1' and e['time'] <= at]
    if not mine:
        return None
    last = mine[-1]['time']
    return any(e['state'] == '1' for e in mine if (last - e['time']).total_seconds() < 2)


# ---------- classification and report ----------

def classify(r: Recording) -> str:
    verdict = r.verdict.lower()
    if 'client bug' in verdict:
        return 'client_bug'
    if r.skipped or (r.delivered is not None and r.delivered < 0.1):
        return 'no_audio'
    if 'bluetooth' in verdict or 'device' in verdict:
        return 'partial_audio'
    if r.text is not None and not r.text.strip() or r.text is None:
        if r.peak is not None and r.peak < SILENT_PEAK:
            return 'silent_mic'
        return 'empty_result'
    return 'ok'


def settle_table(recordings: list[Recording]) -> list[tuple[str, int, int]]:
    bins = [(0, 2), (2, 5), (5, 10), (10, 15), (15, 30), (30, 60), (60, None)]
    rows = []
    for lo, hi in bins:
        group = [r for r in recordings if r.minutes_after_connect is not None and r.mic_active is not False
                 and r.minutes_after_connect >= lo and (hi is None or r.minutes_after_connect < hi)]
        if group:
            bad = sum(r.kind in ('partial_audio', 'no_audio', 'silent_mic') for r in group)
            rows.append((f'{lo}-{hi}' if hi else f'{lo}+', len(group), bad))
    return rows


def report(client: Path, days: int, device: str) -> int:
    log_dir, capture_dir = client / 'logs', client / 'appdata' / 'captures'
    if not log_dir.is_dir():
        print(f'BLOCKED: no client log folder at {log_dir}', file=sys.stderr)
        return 2
    since = date.today() - timedelta(days=days - 1)
    recordings = parse_logs(log_dir, since)
    attach_captures(recordings, capture_dir)
    events = read_endpoint_events()
    connects = mic_connects(events, device) if events else []
    for r in recordings:
        r.kind = classify(r)
        before = [c for c in connects if c <= r.start]
        if before:
            r.minutes_after_connect = (r.start - before[-1]).total_seconds() / 60
        if events:
            r.mic_active = mic_active_at(events, device, r.start)

    print(f'Dictation mic report: {since} to today, device filter "{device or "any"}"')
    print(f'Sources: {len(recordings)} recordings from client logs; captures {"found" if capture_dir.is_dir() else "missing"}; '
          + ('endpoint events read' if events is not None else 'endpoint events UNAVAILABLE (not Windows, or wevtutil failed)'))
    print('\nRecordings by outcome:')
    for kind, meaning in CLASSES.items():
        count = sum(r.kind == kind for r in recordings)
        if count:
            print(f'  {kind:<13} {count:>4}  {meaning}')

    failures = [r for r in recordings if r.kind != 'ok'][-15:]
    if failures:
        print('\nLatest failures (newest last):')
        for r in failures:
            facts = []
            if r.held is not None and r.delivered is not None:
                facts.append(f'held {r.held:.1f}s, mic sent {r.delivered:.1f}s')
            elif r.stop:
                facts.append(f'held {(r.stop - r.start).total_seconds():.1f}s (no capture)')
            if r.peak is not None:
                facts.append(f'peak {r.peak:.3f}')
            if r.minutes_after_connect is not None:
                facts.append(f'{r.minutes_after_connect:.1f} min after mic connect')
            if r.mic_active is False:
                facts.append('mic endpoint was unplugged')
            print(f'  {r.start:%m-%d %H:%M:%S}  {r.kind:<13} {"; ".join(facts)}')

    if connects:
        print(f'\n{device or "Mic"} connects in the event log: {len(connects)}; latest {connects[-1]:%m-%d %H:%M:%S}')
        print('Minutes after connect | recordings | lost or silent audio')
        for label, n, bad in settle_table(recordings):
            print(f'  {label:<20}| {n:>10} | {bad:>3} ({bad / n:.0%})')
    elif events is not None:
        print(f'\nNo "{device}" mic connects in the event log; use --device to match the endpoint name.')
    return 0


# ---------- live test ----------

def live(device: str, seconds: float) -> int:
    try:
        import sounddevice as sd
    except ImportError:
        print("BLOCKED: sounddevice is not installed; run with the repo's .venv Python.", file=sys.stderr)
        return 3
    candidates = [i for i, d in enumerate(sd.query_devices()) if device.lower() in d['name'].lower()
                  and d['max_input_channels'] > 0 and sd.query_hostapis(d['hostapi'])['name'] == 'MME']
    if not candidates:
        print(f'BLOCKED: no MME input device matching "{device}". Inputs: '
              + ', '.join(sorted({d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0})), file=sys.stderr)
        return 3
    block = 2400
    times, peaks = [], []

    def callback(data, frames, when, status):
        times.append(time.perf_counter())
        peaks.append(float(abs(data).max()))

    try:
        with sd.InputStream(device=candidates[0], samplerate=48000, blocksize=block, channels=1,
                            dtype='float32', callback=callback):
            time.sleep(seconds)
    except Exception as e:  # PortAudio raises its own error types
        print(f'BLOCKED: could not open the mic: {e}', file=sys.stderr)
        return 3
    got = len(times) * block / 48000
    gaps = [round(b - a, 2) for a, b in zip(times, times[1:]) if b - a > 0.2]
    healthy = got >= seconds * 0.95 and not gaps
    print(f'{sd.query_devices(candidates[0])["name"]}: audio {got:.2f}s of {seconds:g}s; gaps over 0.2s: {gaps or "none"}; '
          f'peak {max(peaks, default=0):.3f}')
    print('HEALTHY: the link delivers continuous audio.' if healthy else
          'STARVED: the Bluetooth link is dropping audio; see SKILL.md for what to try.')
    return 0


# This script lives in skills/utter-stabilise/scripts/; the client is the repo's dictation/ folder.
CLIENT_ROOT = Path(__file__).resolve().parents[3] / 'dictation'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    rep = sub.add_parser('report', help='offline diagnosis from logs, captures and endpoint events')
    rep.add_argument('--client', type=Path, default=CLIENT_ROOT, help="the dictation client's folder (default: this repo's dictation/)")
    rep.add_argument('--days', type=int, default=3)
    rep.add_argument('--device', default='', help='substring of the mic endpoint name (default: any mic)')
    lv = sub.add_parser('live', help='record a few seconds and measure what arrives')
    lv.add_argument('--device', default='', help='substring of the mic endpoint name (default: the first mic)')
    lv.add_argument('--seconds', type=float, default=6)
    args = parser.parse_args(argv)
    if args.command == 'report':
        if not args.client.is_dir():
            print(f'BLOCKED: client folder not found: {args.client}', file=sys.stderr)
            return 2
        return report(args.client, args.days, args.device)
    return live(args.device, args.seconds)


if __name__ == '__main__':
    sys.exit(main())
