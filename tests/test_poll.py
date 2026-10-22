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


def _all_toward_stops():
    nodes = {r["node_id"] for cfg in DIRECTIONS.values() for r in cfg["registrations"]}
    nodes |= {"A", "B", "C", "CGB2479", "GMB2479"}
    stops = [(i, n, "정류장") for i, n in enumerate(sorted(nodes))]
    return stops + [(999, "END", "학명리 동명")]


def all_toward(service_key, city_code, route_id):
    return _all_toward_stops()


def _run(key, directions, now, data, **kw):
    kw.setdefault("sleep", FakeSleep())
    kw.setdefault("fetch_stops", all_toward)
    return run_poll(key, directions, now, data, **kw)


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
    _run("key", DIRECTIONS, dt(2026, 10, 21, 5, 0), data, sleep=FakeSleep(), fetch_stops=boom)
    assert not data.exists()


def test_run_poll_merges_all_registrations_for_a_direction(tmp_path, monkeypatch):
    def fake(service_key, city_code, node_id):
        if city_code == "37050":
            return [ArrivalObservation("GMB885-10", "885", 12.0)]
        return []

    monkeypatch.setattr("collector.poll.get_arrivals", fake)
    data = tmp_path / "data"
    _run("key", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
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
    _run("key", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
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
    _run("key", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["hakmyeong"]["observations"] == [
        {"routeid": "R1", "routeno": "885", "eta_min": 4.0}
    ]


def test_retry_backoff_and_error_recorded_siblings_kept(tmp_path, monkeypatch):
    bad = {"city_code": "37390", "node_id": "CGB2479"}
    directions = {
        "dongmyeong": {
            "label": "x", "destination_keywords": ["학명"],
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
    _run(KEY, directions, dt(2026, 10, 21, 13, 0), data, sleep=sleep)

    assert calls == ["CGB2479"] * 3 + ["GMB2479"]
    # backoff 2s, 4s; then the 1.2s spacing before the sibling's call
    assert sleep.calls[:2] == [2, 4]
    # 1.2s before the sibling's arrival call, then 1.2s before its route lookup
    assert sleep.calls[2:] == [pytest.approx(1.2)] * 2
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
    directions = {"d": {"label": "x", "destination_keywords": ["학명"], "registrations": [{"city_code": "1", "node_id": "A"}]}}
    state = {"n": 0}

    def flaky(service_key, city_code, node_id):
        state["n"] += 1
        if state["n"] == 1:
            raise requests.ConnectionError("net")
        return [ArrivalObservation("R", "1", 3.0)]

    monkeypatch.setattr("collector.poll.get_arrivals", flaky)
    sleep = FakeSleep()
    _run("k", directions, dt(2026, 10, 21, 13, 0), tmp_path / "data", sleep=sleep)
    # backoff 2s after the failure, then 1.2s spacing before the route lookup
    assert sleep.calls == [2, pytest.approx(1.2)]
    latest = json.loads((tmp_path / "data" / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["errors"] == [] and len(latest["d"]["observations"]) == 1

    def bug(*a, **k):
        raise KeyError("bug")

    monkeypatch.setattr("collector.poll.get_arrivals", bug)
    with pytest.raises(KeyError):
        _run("k", directions, dt(2026, 10, 21, 13, 5), tmp_path / "data", sleep=FakeSleep())


def test_spacing_between_calls_without_failures(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", lambda *a, **k: [])
    sleep = FakeSleep()
    directions = {"d": {"label": "x", "destination_keywords": ["학명"], "registrations": [
        {"city_code": "1", "node_id": "A"}, {"city_code": "1", "node_id": "B"},
        {"city_code": "1", "node_id": "C"}]}}
    _run("k", directions, dt(2026, 10, 21, 13, 0), tmp_path / "data", sleep=sleep)
    assert sleep.calls == [pytest.approx(1.2)] * 2


def test_run_poll_appends_and_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", lambda *a, **k: [])
    data = tmp_path / "data"
    _run("k", DIRECTIONS, dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    _run("k", DIRECTIONS, dt(2026, 10, 21, 13, 5), data, sleep=FakeSleep())
    assert len(_lines(data / "observations" / "hakmyeong" / "2026-10-21.jsonl")) == 2
    assert (data / "arrivals.json").exists() and (data / "stats.json").exists()


# --- route filter (Task 6b) -------------------------------------------------

TOWARD = [(1, "N1", "우체국"), (2, "N2", "학명리")]
AWAY = [(1, "N1", "우체국"), (2, "N2", "동명교통")]


def _one_dir(*regs):
    return {"d": {"label": "x", "destination_keywords": ["학명"],
                  "registrations": [{"city_code": "22", "node_id": n} for n in regs]}}


def _arrivals_by_node(table):
    def fake(service_key, city_code, node_id):
        return table.get(node_id, [])
    return fake


def test_non_toward_routes_kept_in_jsonl_but_excluded_from_latest(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("GOOD", "93", 5.0), ArrivalObservation("BAD", "3", 2.0)]}))
    routes = {"GOOD": TOWARD, "BAD": AWAY}
    data = tmp_path / "data"
    _run("k", _one_dir("N1"), dt(2026, 10, 21, 13, 0), data,
         fetch_stops=lambda key, city, route: routes[route])
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["observations"] == [{"routeid": "GOOD", "routeno": "93", "eta_min": 5.0}]
    rec = _lines(data / "observations" / "d" / "2026-10-21.jsonl")[0]
    by_id = {o["routeid"]: o for o in rec["observations"]}
    assert by_id["GOOD"] == {"routeid": "GOOD", "routeno": "93", "eta_min": 5.0,
                             "city_code": "22", "node_id": "N1", "toward": True}
    assert by_id["BAD"]["toward"] is False and by_id["BAD"]["node_id"] == "N1"


def test_dedupe_only_among_toward_and_after_annotation(tmp_path, monkeypatch):
    # Same route seen at N1 (toward, eta 9) and N2 (not toward from there, eta 1).
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("R", "93", 9.0)],
        "N2": [ArrivalObservation("R", "93", 1.0)]}))
    stops = [(1, "N2", "x"), (2, "Z", "y"), (3, "N1", "x"), (4, "H", "학명리")]
    # from N2 the route reaches 학명 too -> both toward; smallest eta wins
    data = tmp_path / "data"
    _run("k", _one_dir("N1", "N2"), dt(2026, 10, 21, 13, 0), data, fetch_stops=lambda *a: stops)
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["observations"] == [{"routeid": "R", "routeno": "93", "eta_min": 1.0}]
    # now N2 is after the destination: the eta-1 observation must not win
    stops2 = [(1, "N1", "x"), (2, "H", "학명리"), (3, "N2", "x")]
    data2 = tmp_path / "data2"
    _run("k", _one_dir("N1", "N2"), dt(2026, 10, 21, 13, 0), data2, fetch_stops=lambda *a: stops2)
    latest2 = json.loads((data2 / "latest.json").read_text(encoding="utf-8"))
    assert latest2["d"]["observations"] == [{"routeid": "R", "routeno": "93", "eta_min": 9.0}]
    rec = _lines(data2 / "observations" / "d" / "2026-10-21.jsonl")[0]
    assert sorted(o["toward"] for o in rec["observations"]) == [False, True]


def test_route_lookups_use_spacing_and_retry_policy(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("R", "93", 5.0)]}))
    n = {"c": 0}

    def flaky(key, city, route):
        n["c"] += 1
        if n["c"] < 3:
            raise TagoApiError("transient")
        return TOWARD

    sleep = FakeSleep()
    data = tmp_path / "data"
    _run("k", _one_dir("N1"), dt(2026, 10, 21, 13, 0), data, sleep=sleep, fetch_stops=flaky)
    assert n["c"] == 3
    # spacing before 1st lookup, then backoff 2s / 4s between lookup attempts
    assert sleep.calls == [pytest.approx(1.2), 2, 4]
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["errors"] == [] and len(latest["d"]["observations"]) == 1


def test_route_lookup_failure_records_scrubbed_error_not_silent_false(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("R", "93", 5.0)]}))

    def down(key, city, route):
        raise TagoApiError(f"boom {KEY} / {quote(KEY, safe='')} / {quote_plus(KEY)}")

    data = tmp_path / "data"
    _run(KEY, _one_dir("N1"), dt(2026, 10, 21, 13, 0), data, fetch_stops=down)
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["errors"] == [{"city_code": "22", "node_id": "N1", "route_id": "R",
                                      "error": "TagoApiError: boom *** / *** / ***"}]
    assert latest["d"]["observations"] == []
    rec = _lines(data / "observations" / "d" / "2026-10-21.jsonl")[0]
    assert all(o.get("toward") is not False for o in rec["observations"])
    for path in data.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for form in (KEY, quote(KEY, safe=""), quote_plus(KEY)):
                assert form not in text


def test_route_cache_written_once_without_key(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("R", "93", 5.0)], "N2": [ArrivalObservation("R", "93", 6.0)]}))
    calls = []

    def fetch(key, city, route):
        calls.append(route)
        return TOWARD

    data = tmp_path / "data"
    _run(KEY, _one_dir("N1", "N2"), dt(2026, 10, 21, 13, 0), data, fetch_stops=fetch)
    assert calls == ["R"]  # second sighting served from the cache
    text = (data / "route_cache.json").read_text(encoding="utf-8")
    assert "22:R" in json.loads(text) and "학명리" in text
    for form in (KEY, quote(KEY, safe=""), quote_plus(KEY)):
        assert form not in text


def _empty_route_setup(monkeypatch, calls):
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("R", "93", 5.0)], "N2": [ArrivalObservation("R", "93", 4.0)]}))
    empty = {"response": {"header": {"resultCode": "00"}, "body": {"items": "", "totalCount": 0}}}

    class Resp:
        def json(self):
            return empty

    def fake_get(*a, **k):
        calls.append(1)
        return Resp()

    monkeypatch.setattr("collector.route_filter.requests.get", fake_get)


def test_empty_route_is_unknown_with_warning_and_snapshot_kept(tmp_path, monkeypatch):
    calls = []
    _empty_route_setup(monkeypatch, calls)
    data = tmp_path / "data"
    run_poll("k", _one_dir("N1", "N2"), dt(2026, 10, 21, 13, 0), data, sleep=FakeSleep())
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["errors"] == []
    # deduped per (city, route) within the run
    assert latest["d"]["warnings"] == [{"city_code": "22", "node_id": "N1", "route_id": "R",
                                        "routeno": "93", "warning": "empty route stop list"}]
    assert latest["d"]["observations"] == []
    rec = _lines(data / "observations" / "d" / "2026-10-21.jsonl")[0]
    assert rec["warnings"] == latest["d"]["warnings"]
    assert [o["toward"] for o in rec["observations"]] == [None, None]
    # empty result is cached: a second run within 7 days makes no API call
    assert len(calls) == 1
    run_poll("k", _one_dir("N1", "N2"), dt(2026, 10, 21, 13, 5), data, sleep=FakeSleep())
    assert len(calls) == 1
    # rebuild kept the snapshots and counted no arrival
    assert json.loads((data / "arrivals.json").read_text(encoding="utf-8"))["d"] == {}


def test_warnings_key_always_present(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", lambda *a, **k: [])
    data = tmp_path / "data"
    _run("k", _one_dir("N1"), dt(2026, 10, 21, 13, 0), data)
    assert json.loads((data / "latest.json").read_text(encoding="utf-8"))["d"]["warnings"] == []
    assert _lines(data / "observations" / "d" / "2026-10-21.jsonl")[0]["warnings"] == []


def test_route_override_wins_and_skips_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr("collector.poll.get_arrivals", _arrivals_by_node({
        "N1": [ArrivalObservation("YES", "1", 3.0), ArrivalObservation("NO", "2", 2.0)]}))

    def boom(*a):
        raise AssertionError("no lookup expected")

    cfg = _one_dir("N1")
    cfg["d"]["route_overrides"] = {"YES": True, "NO": False}
    data = tmp_path / "data"
    _run("k", cfg, dt(2026, 10, 21, 13, 0), data, fetch_stops=boom)
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["d"]["observations"] == [{"routeid": "YES", "routeno": "1", "eta_min": 3.0}]
    assert latest["d"]["warnings"] == [] and latest["d"]["errors"] == []
    rec = _lines(data / "observations" / "d" / "2026-10-21.jsonl")[0]
    assert {o["routeid"]: o["toward"] for o in rec["observations"]} == {"YES": True, "NO": False}
