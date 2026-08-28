from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from dateutil import parser as dateutil_parser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .analyze import ExtractedEvent
from .config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def get_calendar_service():
    creds: Optional[Credentials] = None
    if GOOGLE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GOOGLE_CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Missing Google OAuth client file at {GOOGLE_CREDENTIALS_PATH}. "
                    "In Google Cloud Console, enable the Calendar API, create an OAuth "
                    "client ID of type 'Desktop app', download it as credentials.json "
                    "into the project root, then run `catedrai calendar-auth`."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        GOOGLE_TOKEN_PATH.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _event_body(event: ExtractedEvent) -> Optional[dict]:
    if not event.date:
        return None
    try:
        parsed = dateutil_parser.parse(event.date)
    except (ValueError, OverflowError):
        return None

    has_time = "T" in event.date or ":" in event.date
    summary = f"[{event.type.title()}] {event.title}"

    if has_time:
        start = {"dateTime": parsed.isoformat()}
        end = {"dateTime": (parsed + timedelta(hours=1)).isoformat()}
    else:
        day = parsed.date()
        start = {"date": day.isoformat()}
        end = {"date": (day + timedelta(days=1)).isoformat()}

    return {"summary": summary, "description": event.description, "start": start, "end": end}


def sync_events(events: List[ExtractedEvent], calendar_id: str = "primary") -> List[str]:
    service = get_calendar_service()
    created_links = []
    for event in events:
        body = _event_body(event)
        if body is None:
            continue
        created = service.events().insert(calendarId=calendar_id, body=body).execute()
        created_links.append(created.get("htmlLink", created.get("id")))
    return created_links
