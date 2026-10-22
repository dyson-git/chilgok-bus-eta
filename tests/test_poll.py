import json
from datetime import datetime, timedelta, timezone

import pytest
from urllib.parse import quote, quote_plus
import requests

from collector.config import DIRECTIONS
from collector.models import ArrivalObservation
from collector.poll import is_within_collection_window, run_poll
from collector.tago_client import TagoApiError

KST = timezone(timedelta(hours=9))


def dt(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=KST)


KEY = "ab+c/d=e+f=="


class FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def _lines(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_is_within_collection_window_boundaries():
    assert is_within_collection_window(dt(2026, 10, 21, 5, 59)) is False
    assert is_within_collection_window(dt(2026, 10, 21, 6, 0)) is True
    assert is_within_collection_window(dt(2026, 10, 21, 21, 30)) is True
    assert is_within_collection_window(dt(2026, 10, 21, 21, 31)) is False


def test_run_poll_outside_window_does_nothing(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not be called")

    monkeypatch.setattr("collector.poll.get_arrivals", boom)
    data = tmp_path / "data"
    run_poll("key", DIRECTIONS, dt(2026, 10, 21, 5, 0), data, sleep=FakeSleep())
    assert not data.exists()


def test_run_poll_merges_all_registrations_for_a_direction(tmp_path, monkeypatch):
    def fake(service_key, city_code, node_id):
        if city_code == "37050":
            return [ArrivalObservation("GMB885-10", "885", 12.0)]
        return []

    monkeypatch.setattr("collector.poll.get_arrivals", fake)
    data = tmp_path / "data"
    run_poll("key", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["hakmyeong"]["observations"] == [
        {"routeid": "GMB885-10", "routeno": "885", "eta_min": 12.0}
    ]
    assert latest["hakmyeong"]["errors"] == []
    assert latest["hakmyeong"]["polled_at"] == "2026-10-21T13:00:00+09:00"
    line = _lines(data / "observations" / "hakmyeong" / "2026-10-21.jsonl")
    assert len(line) == 1 and line[0]["errors"] == []


def test_run_poll_records_empty_observations_without_fabricating(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", lambda *a, **k: [])
    data = tmp_path / "data"
    run_poll("key", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["hakmyeong"]["observations"] == []
    assert latest["hakmyeong"]["errors"] == []


def test_dedupes_by_routeid_keeping_smallest_eta(tmp_path, monkeypatch):
    etas = {"CGB2142": 9.0, "GMB2142": 4.0}

    def fake(service_key, city_code, node_id):
        if node_id in etas:
            return [ArrivalObservation("R1", "885", etas[node_id])]
        return []

    monkeypatch.setattr("collector.poll.get_arrivals", fake)
    data = tmp_path / "data"
    run_poll("key", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["hakmyeong"]["observations"] == [
        {"routeid": "R1", "routeno": "885", "eta_min": 4.0}
    ]


def test_retry_backoff_and_error_recorded_siblings_kept(tmp_path, monkeypatch):
    bad = {"city_code": "37390", "node_id": "CGB2479"}
    directions = {
        "dongmyeong": {
            "label": "x",
            "registrations": [
                bad,
                {"city_code": "37050", "node_id": "GMB2479"},
            ],
        }
    }
    calls = []

    def fake(service_key, city_code, node_id):
        calls.append(node_id)
        if node_id == "CGB2479":
            raise TagoApiError(f"boom {KEY} / {quote(KEY, safe='')} / {quote_plus(KEY)}")
        return [ArrivalObservation("R2", "36", 7.0)]

    monkeypatch.setattr("collector.poll.get_arrivals", fake)
    sleep = FakeSleep()
    data = tmp_path / "data"
    run_poll(KEY, directions, dt(2026, 10, 21, 13, 0), data, sleep=sleep)

    assert calls == ["CGB2479"] * 3 + ["GMB2479"]
    # backoff 2s, 4s; then the 1.2s spacing before the sibling's call
    assert sleep.calls[:2] == [2, 4]
    assert sleep.calls[2:] == [pytest.approx(1.2)]
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    d = latest["dongmyeong"]
    assert d["observations"] == [{"routeid": "R2", "routeno": "36", "eta_min": 7.0}]
    assert d["errors"] == [{"city_code": "37390", "node_id": "CGB2479", "error": "TagoApiError: boom *** / *** / ***"}]
    # recorded line carries the errors too
    line = _lines(data / "observations" / "dongmyeong" / "2026-10-21.jsonl")[0]
    assert line["errors"] == d["errors"]
    for path in (data / "latest.json", data / "observations" / "dongmyeong" / "2026-10-21.jsonl"):
        text = path.read_text(encoding="utf-8")
        for form in (KEY, quote(KEY, safe=""), quote_plus(KEY)):
            assert form not in text


def test_retry_succeeds_on_second_attempt_and_other_exceptions_propagate(tmp_path, monkeypatch):
    directions = {"d": {"label": "x", "registrations": [{"city_code": "1", "node_id": "A"}]}}
    state = {"n": 0}

    def flaky(service_key, city_code, node_id):
        state["n"] += 1
        if state["n"] == 1:
            raise requests.ConnectionError("net")
        return [ArrivalObservation("R", "1", 3.0)]

    monkeypatch.setattr("collector.poll.get_arrivals", flaky)
    sleep = FakeSleep()
    run_poll("k", directions, dt(2026, 10, 21, 13, 0), tmp_path / "data", sleep=sleep)
    assert sleep.calls == [2]
    latest = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["errors"] == [] and len(latest["d"]["observations"]) == 1

    def bug(*a, **k):
        raise KeyError("bug")

    monkeypatch.setattr("collector.poll.get_arrivals", bug)
    with pytest.raises(KeyError):
        run_poll("k", directions, dt(2026, 10, 21, 13, 5), tmp_path / "data", sleep=FakeSleep())


def test_spacing_between_calls_without_failures(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", lambda *a, **k: [])
    sleep = FakeSleep()
    directions = {"d": {"label": "x", "registrations": [
        {"city_code": "1", "node_id": "A"}, {"city_code": "1", "node_id": "B"},
        {"city_code": "1", "node_id": "C"}]}}
    run_poll("k", directions, dt(2026, 10, 21, 13, 0), tmp_path / "data", sleep=sleep)
    assert sleep.calls == [pytest.approx(1.2)] * 2


def test_run_poll_appends_and_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", lambda *a, **k: [])
    data = tmp_path / "data"
    run_poll("k", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    run_poll("k", DIRECTIONS, dt(2026, 10, 21, 13, 5), data, sleep=FakeSleep())
    assert len(_lines(data / "observations" / "hakmyeong" / "2026-10-21.jsonl")) == 2
    assert (data / "arrivals.json").exists() and (data / "stats.json").exists()
