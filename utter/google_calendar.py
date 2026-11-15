"""Google Calendar connector: sign in once in the browser, then read events for the Utter MCP
and the Notetaker's Today card.

Read-only (calendar.readonly). Google needs an OAuth client of type "Desktop app" from your
own Google Cloud project; Utter keeps that file in state/ and the refresh token in Windows
Credential Manager. Sign-in uses a loopback redirect on 127.0.0.1 with PKCE.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from . import local_state

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
API = 'https://www.googleapis.com/calendar/v3'
CLIENT_FILE = 'google-client.json'
ACCOUNT_FILE = 'google-calendar.json'
SECRET = 'Utter/google-calendar'
SIGN_IN_TIMEOUT = 300

_flow = {'pending': False, 'error': None}


class SignInExpired(RuntimeError):
    """Google no longer accepts the saved sign-in (invalid_grant); Utter has forgotten it."""


def client_config() -> dict | None:
    return local_state.read_json(CLIENT_FILE) or None


def set_client_file(path) -> None:
    """Keep the OAuth client JSON downloaded from Google Cloud (Desktop app type)."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('That file is not a Google OAuth client JSON file.')
    if 'installed' not in data:
        kind = 'a web app client' if 'web' in data else 'not an OAuth client file'
        raise ValueError(f'That file is {kind}. Create an OAuth client of type "Desktop app" and download its JSON.')
    local_state.write_json(CLIENT_FILE, data)


def status() -> dict:
    account = local_state.read_json(ACCOUNT_FILE)
    connected = bool(account) and local_state.secret_get(SECRET) is not None
    expired = not connected and bool(account.get('expired_at'))
    return {'has_client': client_config() is not None, 'connected': connected,
            'email': account.get('email') if connected or expired else None,
            'expired': expired, 'pending': _flow['pending'], 'error': _flow['error']}


def connect() -> None:
    """Open Google sign-in in the browser; finishes in the background (watch status())."""
    if _flow['pending']:
        return
    if not client_config():
        raise ValueError('Choose your Google OAuth client file first.')
    _flow.update(pending=True, error=None)
    threading.Thread(target=_sign_in, daemon=True).start()


def _sign_in() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_config(client_config(), SCOPES)
        creds = flow.run_local_server(
            host='127.0.0.1', port=0, open_browser=True, timeout_seconds=SIGN_IN_TIMEOUT,
            authorization_prompt_message=None, access_type='offline', prompt='consent',
            success_message='Utter is connected to Google Calendar. You can close this tab.')
        if not creds.refresh_token:
            raise RuntimeError('Google did not return a refresh token. Try again.')
        local_state.secret_set(SECRET, creds.refresh_token)
        email = _session().get(f'{API}/calendars/primary').json().get('id')
        local_state.write_json(ACCOUNT_FILE, {'email': email, 'connected_at': datetime.now().astimezone().isoformat()})
    except Exception as e:  # shown on the Connectors page
        name = type(e).__name__
        _flow['error'] = ('Sign-in timed out. Press Connect to try again.' if 'Timeout' in name
                          else f'{name}: {e}')
    finally:
        _flow['pending'] = False


def disconnect() -> None:
    token = local_state.secret_get(SECRET)
    if token:
        try:
            import requests
            requests.post('https://oauth2.googleapis.com/revoke', data={'token': token}, timeout=10)
        except Exception:
            pass  # forgetting the token locally is what matters
    local_state.secret_delete(SECRET)
    local_state.remove(ACCOUNT_FILE)
    _flow['error'] = None


def _session(token: str | None = None):
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.credentials import Credentials
    token = token or local_state.secret_get(SECRET)
    config = (client_config() or {}).get('installed', {})
    if not token or not config:
        raise RuntimeError('Google Calendar is not connected. Connect it in Utter: Settings > Connectors.')
    creds = Credentials(None, refresh_token=token, token_uri=config.get('token_uri', 'https://oauth2.googleapis.com/token'),
                        client_id=config['client_id'], client_secret=config.get('client_secret'), scopes=SCOPES)
    return AuthorizedSession(creds)


def _expire(rejected: str) -> None:
    """Forget a refresh token Google has rejected, but remember whose it was so the page can say "reconnect".
    A read that started before you signed in again must not delete the new token."""
    if local_state.secret_get(SECRET) != rejected:
        return
    account = local_state.read_json(ACCOUNT_FILE)
    if account:
        local_state.write_json(ACCOUNT_FILE, dict(account, expired_at=datetime.now().astimezone().isoformat()))
    local_state.secret_delete(SECRET)


def _rejected(error) -> bool:
    """invalid_grant: Google revokes the refresh token 7 days after sign-in while the consent screen is
    in Testing, and when Utter's access is removed or the OAuth client changes. Retrying cannot work."""
    details = error.args[1] if len(error.args) > 1 and isinstance(error.args[1], dict) else {}
    return details.get('error') == 'invalid_grant' or 'invalid_grant' in str(error.args[0] if error.args else '')


def events(start: datetime, end: datetime) -> list[dict]:
    """Events from every calendar shown in Google Calendar, between two aware datetimes, by start time."""
    from google.auth.exceptions import RefreshError
    token = local_state.secret_get(SECRET)
    try:
        return _events(start, end, token)
    except RefreshError as e:
        if not _rejected(e):
            raise
        _expire(token)
        raise SignInExpired('Google Calendar sign-in expired. Reconnect it in Utter: Settings > Connectors.') from e


def _events(start: datetime, end: datetime, token: str | None = None) -> list[dict]:
    session = _session(token)
    response = session.get(f'{API}/users/me/calendarList', params={'minAccessRole': 'reader'}, timeout=20)
    response.raise_for_status()
    found = []
    for calendar in response.json().get('items', []):
        if not (calendar.get('selected') or calendar.get('primary')):
            continue
        result = session.get(f"{API}/calendars/{calendar['id']}/events", timeout=20, params={
            'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'singleEvents': 'true',
            'orderBy': 'startTime', 'maxResults': 250})
        result.raise_for_status()
        name = calendar.get('summaryOverride') or calendar.get('summary') or calendar['id']
        found += [simplify_event(item, name) for item in result.json().get('items', [])
                  if item.get('status') != 'cancelled']
    return sorted(found, key=lambda e: e['start'])


_JOIN_LINK = re.compile(r'https://(?:[\w-]+\.)*(?:zoom\.us|meet\.google\.com|teams\.microsoft\.com|teams\.live\.com|webex\.com)/[^\s<>"\')]+')


def join_link(event: dict) -> str | None:
    """The video-call link of a simplified event: Google Meet, or a Zoom/Teams/Webex link in its location or notes."""
    if event.get('meeting_link'):
        return event['meeting_link']
    match = _JOIN_LINK.search(f"{event.get('location') or ''} {event.get('description') or ''}")
    return match.group(0) if match else None


def simplify_event(item: dict, calendar: str) -> dict:
    start, end = item.get('start', {}), item.get('end', {})
    attendees = [a.get('displayName') or a.get('email') for a in item.get('attendees', [])
                 if not a.get('resource') and (a.get('displayName') or a.get('email'))]
    return {
        'title': item.get('summary') or '(no title)',
        'start': start.get('dateTime') or start.get('date'),
        'end': end.get('dateTime') or end.get('date'),
        'all_day': 'dateTime' not in start,
        'calendar': calendar,
        'location': item.get('location'),
        'organizer': (item.get('organizer') or {}).get('displayName') or (item.get('organizer') or {}).get('email'),
        'attendees': attendees,
        'description': (item.get('description') or '')[:1000] or None,
        'meeting_link': item.get('hangoutLink'),
    }
