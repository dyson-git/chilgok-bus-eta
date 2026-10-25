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
        if st.get("source") != "daegu":        # 칠곡 시스템 정류장만 (대구 정류장은 아래 대구 테스트에서 본다)
            by_dir.setdefault(st["direction"], []).append(sid)
    assert by_dir["dongmyeong"] == ["2479"]                 # 학명리 건너2 = 동명행
    assert "2483" in by_dir["hakmyeong"] and "2479" not in by_dir["hakmyeong"]   # 학명리 정류소 = 학명리행, 건너2 와 다르다
    st = cfg["stops"]["2483"]
    assert st["offset_min"] == 10
    assert st["route_ids"] and all(st["gaps"][r]["stops"] > 0 and st["gaps"][r]["board"] for r in st["route_ids"])


# ---- 칠곡3·급행9-3 은 대구 시스템 버스라 칠곡 버스정보시스템에 실시간이 없다(2026-10-24 12:59 확인: 칠곡 0대, 대구 3대).
#      칠곡 시스템을 기본으로 쓰고 이 두 노선만 대구 버스정보시스템에서 받는다 ----
ROOT = Path(__file__).resolve().parents[1]


def test_relay_passes_daegu_arrivals_only_for_allowed_stops():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    allowed = re.search(r"ALLOWED_DGB_STOPS = new Set\(\[([^\]]*)\]", js).group(1)
    for bs in ("7181001900", "3690003070", "3690003090"):
        assert '"%s"' % bs in allowed
    assert "businfo.daegu.go.kr:8095/dbms_web_api/realtime/arr/" in js
    assert 'url.pathname === "/dgb"' in js


def test_routes_json_takes_only_chilgok3_and_express_9_3_from_daegu():
    stops = json.loads((ROOT / "bis" / "routes.json").read_text(encoding="utf-8"))["stops"]
    gonneo2 = stops["dgb:7181001900"]
    assert (gonneo2["source"], gonneo2["direction"], gonneo2["route_nos"]) == ("daegu", "dongmyeong", ["칠곡3", "급행9-3"])
    hak = stops["dgb:3690003070"]   # 대구 시스템의 학명리 정류소(학명리 방향) - 시간 -10분
    assert (hak["source"], hak["direction"], hak["offset_min"]) == ("daegu", "hakmyeong", 10)
    assert (hak["gaps"]["dgb:4090003014"]["stops"], hak["gaps"]["dgb:4090003014"]["board"]) == (8, "동명면행정복지센터")
    assert "dgb:4090003021" not in hak["route_ids"]          # 학명리에 안 가는 칠곡3
    express = stops["dgb:3690003090"]                         # 급행9-3 은 학명리 정류소에 안 서고 등골마을입구에 선다
    assert express["route_ids"] == ["dgb:1000009300"] and express["gaps"]["dgb:1000009300"]["stops"] == 3


def test_timetable_is_below_the_bus_cards_in_both_apps():
    for page in ("index.html", "bis/index.html"):
        html = (ROOT / page).read_text(encoding="utf-8")
        assert html.index('id="times"') > html.index('id="card-hakmyeong"'), page
        assert html.index('id="times"') > html.index('id="checked"'), page


# ---- 학명리행: 버스가 동명면행정복지센터를 이미 지났어도 아직 동명교통 앞이면 동명교통에서 탈 수 있다(2026-10-24 13:43 실측:
#      칠곡3 이 동명교통에 있는데(학명리까지 7정거장/9분) 기준 8정거장보다 가까워 "지금 오는 버스 없음"이 떴다) ----
from bis.parse import boarding_options


def test_boarding_options_lists_every_dongmyeong_stop_before_hakmyeong_farthest_first():
    loop = _stops((1, "동명교통", 24871), (47, "동명면우체국", 12141), (48, "동명면행정복지센터", 12142),
                  (49, "동명교통", 24871), (56, "학명리", 12483), (111, "동명교통", 24871))
    assert boarding_options(loop, REF, "12483") == [(9, "동명면우체국"), (8, "동명면행정복지센터"), (7, "동명교통")]
    assert boarding_options(_stops((3, "학명리", 12483)), REF, "12483") == []


def test_routes_json_keeps_closer_dongmyeong_stops_as_fallbacks():
    stops = json.loads((ROOT / "bis" / "routes.json").read_text(encoding="utf-8"))["stops"]
    g = stops["dgb:3690003070"]["gaps"]["dgb:4090003014"]
    assert (g["stops"], g["board"]) == (8, "동명면행정복지센터")
    assert g["alts"] == [{"stops": 7, "board": "동명교통"}]


def test_second_app_installs_separately_from_the_first():
    man = json.loads((ROOT / "bis" / "manifest.json").read_text(encoding="utf-8"))
    first = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert man["start_url"] == "./" and man["scope"] == "./" and man["id"] == "./"
    assert man["short_name"] != first["short_name"]
    assert all(i["src"].startswith("../icons/") for i in man["icons"])
    assert '<link rel="manifest" href="manifest.json">' in (ROOT / "bis" / "index.html").read_text(encoding="utf-8")


def test_stops_to_end_counts_from_a_stop_to_the_last_stop_of_the_route():
    from bis.parse import stops_to_end
    sl = [{"WAYPOINT_ORD": i, "STOP_SERVICEID": str(1000 + i), "STOP_KNAME": "s%d" % i} for i in range(1, 64)]
    sl[56]["STOP_SERVICEID"] = "12479"                                  # 57번째 = 학명리 건너2
    assert stops_to_end(sl, "12479") == (6, "s63")
    assert stops_to_end(sl, "99999") is None


def test_routes_json_shows_the_885_heading_to_dongmyeong_in_the_hakmyeong_card():
    # 사용자(2026-10-24): "동명방향으로 885 도착해가면 그게 곧 학명리 방향 버스야" - 885 는 동명 종점에서 바로 돌아 학명리로 간다
    cfg = json.loads((Path(__file__).resolve().parents[1] / "bis" / "routes.json").read_text(encoding="utf-8"))
    (t,) = cfg["turnaround"]
    assert (t["direction"], t["station"], t["route_id"], t["route_no"]) == ("hakmyeong", "2479", "88510", "885")
    assert 1 <= t["extra_stops"] <= 15 and t["terminal"]


def test_first_app_loads_the_bis_module_before_app_js_to_fill_missing_times():
    html = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    assert '<script src="bis/bis.js"></script>' in html
    assert html.index("bis/bis.js") < html.index('src="app.js"')
