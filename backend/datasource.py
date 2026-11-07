"""Loading dialogues from the organizers' API or a JSON file, and resolving call recordings."""
import html
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import http_util, settings

_CLOCK = re.compile(r"^(\d{1,3}):(\d{2})(?::(\d{2}))?$")
PAUSE_RE = re.compile(r"приостановлен|paused|тоқтатыл", re.I)
RESUME_RE = re.compile(r"возобновлен|resumed|жалғастырыл|қайта жалғас", re.I)


def parse_ts(ts) -> float | None:
    """'MM:SS' (chats) -> seconds; ISO 8601 (calls) -> unix seconds."""
    if ts is None:
        return None
    s = str(ts).strip()
    m = _CLOCK.match(s)
    if m:
        a, b, c = m.groups()
        return int(a) * 60 + int(b) if c is None else int(a) * 3600 + int(b) * 60 + int(c)
    s = re.sub(r"(\.\d{6})\d+", r"\1", s).replace("Z", "+00:00")  # Python accepts max 6 fraction digits
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def normalize(record: dict) -> dict:
    """Adds to each message: id (index), offset_sec (from the first message), audio_sec (position in the
    recording; recording pauses are skipped because they are not in the audio). Original fields untouched."""
    tr = record.get("transcript") or []
    secs = [parse_ts(t.get("timestamp")) for t in tr]
    t0 = next((s for s in secs if s is not None), None)
    paused_at, paused_total = None, 0.0
    out = []
    for i, (t, s) in enumerate(zip(tr, secs)):
        off = round(s - t0, 1) if s is not None and t0 is not None else None
        audio = None
        if off is not None:
            text, is_sys = t.get("text") or "", t.get("speaker") == "system"
            if settings.AUDIO_SKIP_PAUSES and is_sys and paused_at is None and PAUSE_RE.search(text):
                paused_at = off
                audio = off - paused_total
            elif settings.AUDIO_SKIP_PAUSES and is_sys and paused_at is not None and RESUME_RE.search(text):
                paused_total += off - paused_at
                paused_at = None
                audio = off - paused_total
            elif paused_at is not None:
                audio = paused_at - paused_total
            else:
                audio = off - paused_total
            audio = round(max(0.0, audio), 1)
        out.append({**t, "id": i, "offset_sec": off, "audio_sec": audio})
    is_call = bool(record.get("audio_url")) or "call" in str(record.get("channel", "")).lower()
    return {**record, "transcript": out, "is_call": is_call}


def parse_payload(payload) -> list[dict]:
    if isinstance(payload, dict) and payload.get("isSuccess") is False:
        raise ValueError(payload.get("error") or "API вернул isSuccess=false")
    if isinstance(payload, list):
        recs = payload
    elif isinstance(payload, dict):
        recs = (payload.get("data") or {}).get("records") if isinstance(payload.get("data"), dict) else None
        recs = recs or payload.get("records")
    else:
        recs = None
    if not recs:
        raise ValueError("В данных нет списка диалогов (ожидается data.records)")
    bad = [r for r in recs if not isinstance(r, dict) or "conversation_id" not in r or "transcript" not in r]
    if bad:
        raise ValueError(f"{len(bad)} записей без conversation_id или transcript")
    return [normalize(r) for r in recs]


def group_url(group_id: str) -> str:
    if not settings.DATA_API_URL:
        raise ValueError("В .env не задан DATA_API_URL (ссылка GET от организаторов)")
    parts = urlsplit(settings.DATA_API_URL)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "group_id"]
    query.append(("group_id", group_id))
    return urlunsplit(parts._replace(query=urlencode(query)))


def fetch_group(group_id: str) -> list[dict]:
    try:
        payload = http_util.get_json(group_url(group_id), timeout=90)
    except http_util.HttpError as e:
        raise ValueError(f"API организаторов: {e}") from None
    records = parse_payload(payload)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (settings.DATA_DIR / f"{group_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return records


# ---- call recordings ----
# audio_url returns a small HTML player page; the real mp3 link inside it is signed and expires (~1 h),
# so we extract it on demand and cache it for a while.
_audio_cache: dict[str, tuple[float, str]] = {}
AUDIO_CACHE_SEC = 40 * 60


def resolve_audio(audio_url: str) -> str:
    hit = _audio_cache.get(audio_url)
    if hit and time.time() - hit[0] < AUDIO_CACHE_SEC:
        return hit[1]
    try:
        _, headers, body = http_util.request(audio_url, timeout=30, max_bytes=200_000)
    except http_util.HttpError as e:
        raise ValueError(f"Запись недоступна: {e}") from None
    ctype = headers.get("content-type", "").lower()
    if ctype.startswith("audio/") or "octet-stream" in ctype:
        src = audio_url
    else:
        text = body.decode("utf-8", "replace")
        m = re.search(r'<source[^>]+src="([^"]+)"', text) or re.search(r'<audio[^>]+src="([^"]+)"', text)
        if not m:
            raise ValueError("Не удалось найти ссылку на аудио в ответе")
        src = html.unescape(m.group(1))
    _audio_cache[audio_url] = (time.time(), src)
    return src
