"""Data loading: timestamps, audio positions with recording pauses, recording link extraction."""
from backend import datasource


def test_parse_timestamps():
    assert datasource.parse_ts("02:38") == 158
    assert datasource.parse_ts("1:02:03") == 3723
    a = datasource.parse_ts("2026-11-03T13:10:00.6388245+00:00")
    b = datasource.parse_ts("2026-11-03T13:10:15.5558925+00:00")
    assert round(b - a, 2) == 14.92


def test_audio_positions_skip_pauses():
    conv = datasource.normalize({"conversation_id": "x", "channel": "voice call", "audio_url": "u", "transcript": [
        {"timestamp": "2026-11-03T13:10:00+00:00", "speaker": "system", "text": "Запись началась"},
        {"timestamp": "2026-11-03T13:10:50+00:00", "speaker": "system", "text": "Запись и транскрибирование приостановлены."},
        {"timestamp": "2026-11-03T13:11:00+00:00", "speaker": "system", "text": "Агент присоединился"},
        {"timestamp": "2026-11-03T13:11:10+00:00", "speaker": "system", "text": "Запись и транскрибирование возобновлены."},
        {"timestamp": "2026-11-03T13:11:20+00:00", "speaker": "operator", "text": "Здравствуйте"},
    ]})
    t = conv["transcript"]
    assert conv["is_call"] and [m["offset_sec"] for m in t] == [0, 50, 60, 70, 80]
    assert [m["audio_sec"] for m in t] == [0, 50, 50, 50, 60]  # 20 s pause is not in the recording


def test_resolve_audio_from_player_page(monkeypatch):
    page = ('<html><audio id="myAudio" controls><source src="https://x.dynamics.com/api/filedownload/1/a?sp=r&amp;'
            'sig=abc&rsct=audio%2Fmpeg" type="audio/mpeg"></audio></html>')
    monkeypatch.setattr(datasource.http_util, "request",
                        lambda *a, **k: (200, {"content-type": "text/html; charset=utf-8"}, page.encode()))
    datasource._audio_cache.clear()
    assert datasource.resolve_audio("https://player") == \
        "https://x.dynamics.com/api/filedownload/1/a?sp=r&sig=abc&rsct=audio%2Fmpeg"


def test_payload_formats():
    rec = {"conversation_id": "a", "transcript": [{"timestamp": "00:00", "speaker": "client", "text": "hi"}]}
    assert len(datasource.parse_payload({"isSuccess": True, "data": {"records": [rec]}})) == 1
    assert len(datasource.parse_payload([rec])) == 1
