"""
Playback of Twilio voice message recordings through the console.

Recordings are protected by HTTP auth at Twilio, so the browser can't load them
directly. The console fetches them with the account credentials and serves them
to signed-in staff only.
"""
import logging
import re
from urllib.parse import urlparse

import requests

from config import Config
from jobs_queue import get_redis

logger = logging.getLogger(__name__)

RECORDING_PATH = re.compile(r"^/2010-04-01/Accounts/(AC[0-9a-f]{32})/Recordings/(RE[0-9a-f]{32})$")
CACHE_TTL = 600  # seconds; seeking sends several range requests
TIMEOUT = (3, 15)


class RecordingUnavailable(Exception):
    pass


def parse_recording_url(url):
    """(account_sid, recording_sid) for a Twilio recording URL, else None (no SSRF)"""
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.hostname != "api.twilio.com":
        return None
    match = RECORDING_PATH.match(parsed.path)
    return match.groups() if match else None


def fetch_recording(url):
    """MP3 bytes of a Twilio recording (cached briefly in Redis)"""
    parsed = parse_recording_url(url)
    if not parsed:
        raise RecordingUnavailable("Not a Twilio recording URL")
    account_sid, recording_sid = parsed
    cache_key = f"recording:{recording_sid}"

    try:
        cached = get_redis().get(cache_key)
        if cached:
            return cached
    except Exception as e:
        logger.warning(f"Recording cache unavailable: {e}")

    if not Config.TWILIO_AUTH_TOKEN:
        raise RecordingUnavailable("TWILIO_AUTH_TOKEN is not set")
    try:
        response = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording_sid}.mp3",
            auth=(account_sid, Config.TWILIO_AUTH_TOKEN),
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        raise RecordingUnavailable(f"Twilio unreachable: {e}") from e
    if response.status_code != 200:
        raise RecordingUnavailable(f"Twilio answered {response.status_code}")

    try:
        get_redis().setex(cache_key, CACHE_TTL, response.content)
    except Exception as e:
        logger.warning(f"Recording cache unavailable: {e}")
    return response.content


def console_audio_url(message_id):
    """Link for emails: opens the recording in the console (sign-in required)"""
    return f"{Config.WEBSITE_URL.rstrip('/')}/voice-messages/{message_id}/audio"
