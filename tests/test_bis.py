"""칠곡 버스정보시스템(bus.chilgok.go.kr) 정류장 팝업 파서와 "학명리 가는 노선" 판별 (2026-10-23).

fixtures 는 실제 응답을 그대로 저장한 것이다(2141 = 동명면우체국: 527 이 7정거장전/10분후, 2479 = 학명리 건너2: 도착 없음)."""
import json
import re
from pathlib import Path

from bis.parse import parse_stop_popup, routes_toward, stops_between

FIX = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_popup_lists_every_route_serving_the_stop_with_its_id_and_number():
    rows = parse_stop_popup(_read("bis_stop_2141.html"))
    assert len(rows) == 19
    ids = {r["route_id"] for r in rows}
    assert {"52710", "30020", "88520", "칠곡330", "칠곡337", "9-310"} <= ids
    r527 = next(r for r in rows if r["route_id"] == "52710")
    assert r527["route_no"] == "527"
    assert "연화리2" in r527["ends"] and "동명교통" in r527["ends"]


def test_popup_row_id_has_a_text_prefix_for_some_routes_but_the_route_api_wants_digits_only():
    rows = {r["route_id"]: r["api_id"] for r in parse_stop_popup(_read("bis_stop_2141.html"))}
    assert rows["칠곡330"] == "330" and rows["급행310"] == "310"     # 앞의 글자(노선 종류)를 뗀다
    assert rows["52710"] == "52710" and rows["9-310"] == "9-310" and rows["335"] == "335"


def test_popup_reads_stops_away_and_minutes_for_a_bus_that_is_coming():
    r527 = next(r for r in parse_stop_popup(_read("bis_stop_2141.html")) if r["route_id"] == "52710")
    assert (r527["stops_away"], r527["minutes"]) == (7, 10)


def test_popup_marks_routes_without_a_bus_as_none_not_zero():
    rows = parse_stop_popup(_read("bis_stop_2141.html"))
    none = [r for r in rows if r["route_id"] != "52710"]
    assert len(none) == 18
    assert all(r["stops_away"] is None and r["minutes"] is None for r in none)


def test_popup_for_the_dongmyeong_stop_has_all_its_routes_and_no_arrivals_now():
    rows = parse_stop_popup(_read("bis_stop_2479.html"))
    assert [r["route_no"] for r in rows].count("칠곡3") == 4
    assert {"300", "34", "34-1", "36", "36-1", "885"} <= {r["route_no"] for r in rows}
    assert all(r["minutes"] is None for r in rows)


def test_unknown_arrival_wording_is_kept_as_text_never_turned_into_a_time():
    html = ('<tr id="1_1"><th><span>9</span><p>가_나 <sub>( 가↔&nbsp;나)</sub></p></th>'
            '<td>운행종료</td><td>-</td></tr>')
    r = parse_stop_popup(html)[0]
    assert (r["stops_away"], r["minutes"], r["text"]) == (None, None, "운행종료 -")


def _stops(*pairs):
    return [{"WAYPOINT_ORD": o, "STOP_KNAME": n, "STOP_SERVICEID": s} for o, n, s in pairs]


def test_route_goes_toward_hakmyeong_only_when_a_hakmyeong_stop_comes_after_boarding():
    after = _stops((10, "동명면우체국", 12141), (11, "학명동", 12481))
    before = _stops((3, "학명리", 12483), (10, "동명면우체국", 12141))
    none = _stops((1, "동명면우체국", 12141), (2, "왜관북부", 99999))
    assert routes_toward(after, {"12141"}, "학명") is True
    assert routes_toward(before, {"12141"}, "학명") is False     # 학명리를 지나서 온 버스
    assert routes_toward(none, {"12141"}, "학명") is False
    assert routes_toward(after, {"55555"}, "학명") is False      # 이 노선은 그 정류장을 안 지난다


def test_looping_route_counts_if_any_boarding_pass_precedes_a_hakmyeong_stop():
    loop = _stops((5, "동명교통", 24870), (9, "학명리", 12483), (20, "동명교통", 24870))
    assert routes_toward(loop, {"24870"}, "학명") is True


# ---- 학명리행: 학명리 정류소(12483) 시간에서 빼서 동명 기준으로 보여준다(사용자 지시 2026-10-24) ----
REF = ["12142", "24871", "12141", "24870"]   # 동명면행정복지센터 먼저(사용자가 말한 기준), 없으면 동명교통/우체국


def test_stops_between_counts_from_the_preferred_dongmyeong_stop_to_the_hakmyeong_stop():
    route = _stops((28, "동명면우체국", 12141), (29, "동명면행정복지센터", 12142), (30, "동명교통", 24871), (38, "학명리", 12483))
    assert stops_between(route, REF, "12483") == (9, "동명면행정복지센터")


def test_stops_between_falls_back_to_another_dongmyeong_stop_when_the_route_skips_the_preferred_one():
    route = _stops((1, "동명교통", 24871), (9, "학명리", 12483))
    assert stops_between(route, REF, "12483") == (8, "동명교통")


def test_stops_between_uses_the_pass_just_before_hakmyeong_on_a_looping_route():
    loop = _stops((1, "동명교통", 24870), (48, "동명면행정복지센터", 12142), (56, "학명리", 12483), (111, "동명교통", 24870))
    assert stops_between(loop, REF, "12483") == (8, "동명면행정복지센터")


def test_stops_between_is_none_when_no_dongmyeong_stop_comes_before_or_the_stop_is_not_on_the_route():
    assert stops_between(_stops((3, "학명리", 12483), (10, "동명면우체국", 12141)), REF, "12483") is None
    assert stops_between(_stops((1, "동명면우체국", 12141), (2, "왜관북부", 99999)), REF, "12483") is None


def test_relay_allows_the_hakmyeong_stops_used_by_the_page():
    js = (Path(__file__).resolve().parents[1] / "worker" / "relay.js").read_text(encoding="utf-8")
    allowed = re.search(r"ALLOWED_BIS_STOPS = new Set\(\[([^\]]*)\]", js).group(1)
    for sid in ("2479", "2483", "2485"):
        assert '"%s"' % sid in allowed


def test_routes_json_uses_gonneo2_for_dongmyeong_and_the_hakmyeong_stop_for_hakmyeong():
    cfg = json.loads((Path(__file__).resolve().parents[1] / "bis" / "routes.json").read_text(encoding="utf-8"))
    by_dir = {}
    for sid, st in cfg["stops"].items():
        by_dir.setdefault(st["direction"], []).append(sid)
    assert by_dir["dongmyeong"] == ["2479"]                 # 학명리 건너2 = 동명행
    assert "2483" in by_dir["hakmyeong"] and "2479" not in by_dir["hakmyeong"]   # 학명리 정류소 = 학명리행, 건너2 와 다르다
    st = cfg["stops"]["2483"]
    assert st["offset_min"] == 10
    assert st["route_ids"] and all(st["gaps"][r]["stops"] > 0 and st["gaps"][r]["board"] for r in st["route_ids"])
