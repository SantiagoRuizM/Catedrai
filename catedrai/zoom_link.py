from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlparse, parse_qs


@dataclass
class ZoomMeeting:
    confno: str
    pwd: Optional[str]
    domain: str


def parse_zoom_link(url: str) -> ZoomMeeting:
    """Parses a standard Zoom join link, e.g.
    https://universidad.zoom.us/j/93948155904?pwd=abc123
    """
    parsed = urlparse(url.strip())
    match = re.search(r"/j/(\d+)", parsed.path)
    if not match:
        raise ValueError(f"Could not find a meeting number (/j/<id>) in: {url}")

    query = parse_qs(parsed.query)
    pwd = query.get("pwd", [None])[0]
    domain = parsed.netloc or "zoom.us"

    return ZoomMeeting(confno=match.group(1), pwd=pwd, domain=domain)


def build_join_uri(meeting: ZoomMeeting, display_name: str) -> str:
    """Builds the zoommtg:// deep link that launches the Zoom desktop client
    straight into the join flow, bypassing the browser landing page."""
    params = [f"action=join", f"confno={meeting.confno}"]
    if meeting.pwd:
        params.append(f"pwd={meeting.pwd}")
    params.append(f"uname={quote(display_name)}")
    return f"zoommtg://{meeting.domain}/join?{'&'.join(params)}"
