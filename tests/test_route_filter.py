import json
from datetime import date
from urllib.parse import quote, quote_plus

import pytest
import requests

from collector.route_filter import RouteCache, fetch_route_stops, route_goes_toward
from collector.tago_client import TagoApiError

KEY = "ab+c/d=e+f=="
BOARD = "DGB3690003750"

R93 = [
    (1011, "DGB3690003750", "동명면우체국"),
    (1013, "DGB3690003060", "학명동"),
    (1014, "DGB3690003090", "학명리(등골마을입구)"),
    (2030, "DGB7181074200", "학명리(등골마을건너)"),
    (2031, "DGB7181001900", "학명리 건너2"),
    (2033, "DGB7181001100", "동명면우체국건너"),
]
R3 = [
    (1028, "DGB3690003750", "동명면우체국"),
    (1029, "DGB7181007000", "동명교통"),
    (2001, "DGB7181007000", "동명교통"),
    (2002, "DGB7181001100", "동명면우체국건너"),
]
R527 = [
    (1070, "DGB7181000800", "동명파출소"),
    (1071, "DGB3690003750", "동명면우체국"),
    (1072, "DGB7181007000", "동명교통"),
    (2001, "DGB7181007000", "동명교통"),
    (2002, "DGB7181001100", "동명면우체국건너"),
]


def test_real_routes_toward_hakmyeong():
    assert route_goes_toward(R93, BOARD, ["학명"]) is True
    assert route_goes_toward(R3, BOARD, ["학명"]) is False
    assert route_goes_toward(R527, BOARD, ["학명"]) is False


def test_destination_only_before_boarding_is_false():
    stops = [(1, "D1", "학명리"), (2, BOARD, "동명면우체국"), (3, "D3", "종점")]
    assert route_goes_toward(stops, BOARD, ["학명"]) is False


def test_boarding_not_on_route_is_false():
    assert route_goes_toward(R93, "NOPE", ["학명"]) is False


def test_loop_boarding_twice_true_if_any_occurrence_followed_by_destination():
    stops = [(1, BOARD, "우체국"), (2, "X", "중간"), (3, BOARD, "우체국"), (4, "H", "학명리")]
    assert route_goes_toward(stops, BOARD, ["학명"]) is True
    stops2 = [(1, BOARD, "우체국"), (2, "H", "학명리"), (3, BOARD, "우체국")]
    assert route_goes_toward(stops2, BOARD, ["학명"]) is True  # first occurrence qualifies


def test_unsorted_input_is_ordered_by_nodeord():
    assert route_goes_toward(list(reversed(R93)), BOARD, ["학명"]) is True


class FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def _page(items, total):
    return {"response": {"header": {"resultCode": "00"},
                         "body": {"items": {"item": items}, "totalCount": total}}}


def test_fetch_route_stops_paginates_and_sorts(monkeypatch):
    calls = []
    pages = {
        1: _page([{"nodeord": 3, "nodeid": "C", "nodenm": "c"},
                  {"nodeord": 1, "nodeid": "A", "nodenm": "a"}], 3),
        2: _page({"nodeord": 2, "nodeid": "B", "nodenm": "b"}, 3),  # single dict
    }

    def fake_get(url, params, timeout):
        calls.append((url, dict(params), timeout))
        return FakeResp(pages[params["pageNo"]])

    monkeypatch.setattr("collector.route_filter.requests.get", fake_get)
    stops = fetch_route_stops("k", "22", "R1")
    assert stops == [(1, "A", "a"), (2, "B", "b"), (3, "C", "c")]
    assert len(calls) == 2
    url, params, timeout = calls[0]
    assert url.endswith("/BusRouteInfoInqireService/getRouteAcctoThrghSttnList")
    assert params["serviceKey"] == "k" and params["cityCode"] == "22"
    assert params["routeId"] == "R1" and params["numOfRows"] == 300 and params["_type"] == "json"
    assert timeout == 15


def test_fetch_route_stops_errors(monkeypatch):
    envelope = {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "bad", "returnReasonCode": "30"}}}
    monkeypatch.setattr("collector.route_filter.requests.get", lambda *a, **k: FakeResp(envelope))
    with pytest.raises(TagoApiError):
        fetch_route_stops("k", "22", "R1")
    bad = {"response": {"header": {"resultCode": "99", "resultMessage": "nope"}, "body": {}}}
    monkeypatch.setattr("collector.route_filter.requests.get", lambda *a, **k: FakeResp(bad))
    with pytest.raises(TagoApiError):
        fetch_route_stops("k", "22", "R1")


def test_fetch_route_stops_empty_items(monkeypatch):
    empty = {"response": {"header": {"resultCode": "00"}, "body": {"items": "", "totalCount": 0}}}
    monkeypatch.setattr("collector.route_filter.requests.get", lambda *a, **k: FakeResp(empty))
    assert fetch_route_stops("k", "22", "R1") == []


T0 = date(2026, 10, 21)


def test_cache_miss_fetches_and_save_roundtrips(tmp_path):
    path = tmp_path / "data" / "route_cache.json"
    cache = RouteCache(path, today=T0)
    n = []

    def fetch(key, city, route):
        n.append(route)
        return R3

    assert cache.get_stops("k", "22", "R3", fetch=fetch) == R3
    assert cache.get_stops("k", "22", "R3", fetch=fetch) == R3
    assert n == ["R3"]
    cache.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["22:R3"]["fetched"] == "2026-10-21"
    assert raw["22:R3"]["stops"][0] == [1028, "DGB3690003750", "동명면우체국"]
    assert "동명면우체국" in path.read_text(encoding="utf-8")  # ensure_ascii=False
    assert not list(path.parent.glob("*.tmp"))
    # new instance: fresh hit, no fetch
    c2 = RouteCache(path, today=date(2026, 10, 28))
    assert c2.get_stops("k", "22", "R3", fetch=lambda *a: pytest.fail("fetched")) == R3


def test_cache_stale_refetches_and_failure_falls_back_to_stale(tmp_path):
    path = tmp_path / "route_cache.json"
    c1 = RouteCache(path, today=date(2026, 10, 1))
    c1.get_stops("k", "22", "R3", fetch=lambda *a: R3)
    c1.save()
    c2 = RouteCache(path, today=T0)  # 20 days old
    assert c2.get_stops("k", "22", "R3", fetch=lambda *a: R93) == R93

    c3 = RouteCache(path, today=T0)

    def boom(*a):
        raise TagoApiError("down")

    assert c3.get_stops("k", "22", "R3", fetch=boom) == R3  # stale fallback
    for exc in (requests.ConnectionError("x"), ValueError("y")):
        c4 = RouteCache(path, today=T0)
        assert c4.get_stops("k", "22", "R3", fetch=lambda *a, e=exc: (_ for _ in ()).throw(e)) == R3


def test_cache_failure_without_cache_reraises(tmp_path):
    cache = RouteCache(tmp_path / "c.json", today=T0)

    def boom(*a):
        raise TagoApiError("down")

    with pytest.raises(TagoApiError):
        cache.get_stops("k", "22", "R9", fetch=boom)
    cache.save()  # nothing cached: must not write bogus entries
    raw = json.loads((tmp_path / "c.json").read_text(encoding="utf-8")) if (tmp_path / "c.json").exists() else {}
    assert "22:R9" not in raw


def test_empty_stop_list_is_cached_not_treated_as_failure(tmp_path):
    path = tmp_path / "c.json"
    c1 = RouteCache(path, today=T0)
    assert c1.get_stops("k", "22", "R", fetch=lambda *a: []) == []
    c1.save()
    c2 = RouteCache(path, today=date(2026, 10, 25))
    assert c2.get_stops("k", "22", "R", fetch=lambda *a: pytest.fail("fetched")) == []
    c3 = RouteCache(path, today=date(2026, 11, 5))  # past max age: re-checked
    assert c3.get_stops("k", "22", "R", fetch=lambda *a: R3) == R3
