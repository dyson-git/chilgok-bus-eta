"""칠곡 버스정보시스템에서 화면이 쓸 정류장·노선 설정을 만들어 bis/routes.json 에 쓴다.

실행: python -m bis.build_routes   (노선이 바뀌었을 때만. 약 25회 요청, 요청마다 0.25초 쉰다)
- 동명행 = 학명리 건너2(2479). 동명행 전용 정류장이라 노선을 거르지 않는다(route_ids = null).
- 학명리행 = 학명리 정류소(2483, 학명리 방향 버스가 서는 곳. 건너2 와 다른 정류장). 사용자 방식(2026-10-24):
  학명리 정류소 도착 시간에서 10분을 빼서 동명 기준으로 보여준다. 정거장 수는 노선 정류장 순서로 동명 정류장까지 실제 개수를 뺀다.
  동명 정류장을 먼저 지나는 노선만 남긴다. 9-3 은 학명리 정류소에 안 서고 등골마을입구(2485)에 서서 그 정류장으로 따로 받는다.
- 칠곡3·급행9-3 은 대구 시스템 버스라 칠곡 버스정보시스템에 실시간이 없다(2026-10-24 확인). 이 두 노선만 대구 버스정보시스템
  정류장(키 "dgb:<bsId>", source "daegu")으로 같은 방식으로 받는다: 동명행 = 대구 학명리 건너2, 학명리행 = 대구 학명리 -10분,
  급행9-3 은 대구 등골마을입구 -3분."""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bis.parse import boarding_options, parse_stop_popup, stops_between, stops_to_end

BASE = "https://bus.chilgok.go.kr"
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest", "Referer": BASE + "/map/BusMap.do",
           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
# direction -> station_id 목록, 앞쪽 정류장이 우선 (worker/relay.js ALLOWED_BIS_STOPS 안에 있어야 중계가 전달한다)
DIRECTIONS = {"dongmyeong": ["2479"], "hakmyeong": ["2483", "2485"]}
# 학명리행 정류장 시간에서 빼는 분. 2483 은 사용자가 정한 10분. 2485(9-3 전용)는 동명면우체국에서 3정거장이라
# 사용자 기준(약 9정거장 = 10분)으로 환산한 3분.
OFFSET_MIN = {"2483": 10, "2485": 3}
# 정거장 수를 셀 동명 정류장(서비스 번호), 앞쪽 우선: 동명면행정복지센터(사용자가 말한 기준) > 동명교통 > 동명면우체국 > 동명교통(반대편)
REF_IDS = ["12142", "24871", "12141", "24870"]
OUT = Path(__file__).with_name("routes.json")

DGB = "https://businfo.daegu.go.kr:8095/dbms_web_api/"
# 대구 bsId -> (방향, 받을 노선 번호, 빼는 분). worker/relay.js ALLOWED_DGB_STOPS 안에 있어야 중계가 전달한다.
DAEGU_STOPS = {
    "7181001900": ("dongmyeong", ["칠곡3", "급행9-3"], None),   # 학명리 건너2
    "3690003070": ("hakmyeong", ["칠곡3"], 10),                 # 학명리 (사용자가 정한 10분)
    "3690003090": ("hakmyeong", ["급행9-3"], 3),                # 학명리(등골마을입구): 동명면우체국에서 3정거장 -> 3분
}
DAEGU_REF_NAMES = ["동명면행정복지센터", "동명교통", "동명면우체국"]   # 정거장 수를 셀 동명 정류장, 앞쪽 우선
# 종점(동명)에서 바로 돌아 학명리 방향으로 가는 노선(사용자 확인 2026-10-24: "동명방향으로 885 도착해가면 그게 곧 학명리 방향 버스야").
# 동명행으로 station 을 지나는 그 노선 버스를 학명리행 카드에도 "동명 N정류장 전"으로 보여준다(시간은 station 도착 값 그대로).
TURNAROUND = [{"direction": "hakmyeong", "station": "2479", "route_id": "88510"}]


def gap_entry(stop_list, ref_ids, target_id):
    """{stops, board, alts}: 기준 승차 정류장(ref_ids 우선순위) + 그보다 학명리에 가까운 동명 정류장(alts, 먼 것부터).
    버스가 기준 정류장을 지났어도 alts 정류장 앞이면 화면이 그 정류장으로 보여준다. 노선이 해당 없으면 None."""
    found = stops_between(stop_list, ref_ids, target_id)
    if not found:
        return None
    alts = [{"stops": n, "board": b} for n, b in boarding_options(stop_list, ref_ids, target_id) if n < found[0]]
    return {"stops": found[0], "board": found[1], "alts": alts}


def post(path, **data):
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode(), headers=HEADERS)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def dget(path):
    req = urllib.request.Request(DGB + path, headers={"User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read()).get("body") or []


def daegu_stops():
    """대구 정류장 설정. 노선 정류장 목록(bs/route)을 칠곡 StopListByRoute 모양으로 바꿔 stops_between 을 그대로 쓴다."""
    route_nos = sorted({no for _, nos, _ in DAEGU_STOPS.values() for no in nos})
    routes, lists, names = [], {}, {}
    for no in route_nos:
        routes += [r for r in dget("route/search?searchText=" + urllib.parse.quote(no)) if r.get("routeNo") == no]
        time.sleep(0.25)
    for r in routes:
        lists[r["routeId"]] = [{"WAYPOINT_ORD": int(x["seq"]), "STOP_KNAME": x["bsNm"], "STOP_SERVICEID": x["bsId"]}
                               for x in dget("bs/route?routeId=" + r["routeId"])]
        names.update({x["STOP_SERVICEID"]: x["STOP_KNAME"] for x in lists[r["routeId"]]})
        time.sleep(0.25)
    out = {}
    for bs, (direction, nos, offset) in DAEGU_STOPS.items():
        entry = {"source": "daegu", "direction": direction, "name": names.get(bs, bs), "route_nos": nos}
        if direction == "dongmyeong":
            entry["route_ids"] = None
        else:
            gaps = {}
            for r in routes:
                if r["routeNo"] not in nos:
                    continue
                sl = lists[r["routeId"]]
                ref_ids = [x["STOP_SERVICEID"] for nm in DAEGU_REF_NAMES for x in sl if x["STOP_KNAME"] == nm]
                entry_gap = gap_entry(sl, ref_ids, bs)
                if entry_gap:
                    gaps["dgb:" + r["routeId"]] = entry_gap
            entry.update({"route_ids": list(gaps), "gaps": gaps, "offset_min": offset})
        out["dgb:" + bs] = entry
    return out


def main():
    stops, stop_lists = {}, {}
    for direction, ids in DIRECTIONS.items():
        for sid in ids:
            page = post("/map/AjaxRouteListByStop.do", station_id=sid)
            cap = re.search(r"<p class=caption>\s*(.*?)\s*<span>\((\d+)\)", page, re.S)
            if not cap:
                sys.exit("정류장 %s 팝업에서 이름/번호를 못 찾음" % sid)
            stops[sid] = {"direction": direction, "name": re.sub(r"\s+", " ", cap.group(1)).strip(),
                          "service_id": cap.group(2), "rows": parse_stop_popup(page)}
            time.sleep(0.25)
    out_stops, taken = {}, set()
    for direction, ids in DIRECTIONS.items():
        for sid in ids:
            s = stops[sid]
            entry = {"direction": direction, "name": s["name"], "service_id": s["service_id"],
                     "routes": {r["route_id"]: {"no": r["route_no"], "ends": r["ends"]} for r in s["rows"]}}
            if direction == "dongmyeong":
                entry["route_ids"] = None
            else:
                gaps = {}
                for r in s["rows"]:
                    if r["route_id"] in taken:
                        continue
                    if r["api_id"] not in stop_lists:
                        stop_lists[r["api_id"]] = json.loads(post("/map/StopListByRoute.do", route_id=r["api_id"])).get("stopList") or []
                        time.sleep(0.25)
                    entry_gap = gap_entry(stop_lists[r["api_id"]], REF_IDS, s["service_id"])
                    if entry_gap:
                        gaps[r["route_id"]] = entry_gap
                taken.update(gaps)
                entry.update({"route_ids": list(gaps), "gaps": gaps, "offset_min": OFFSET_MIN[sid]})
            out_stops[sid] = entry
    out_stops.update(daegu_stops())
    turnaround = []
    for t in TURNAROUND:
        row = next((r for r in stops[t["station"]]["rows"] if r["route_id"] == t["route_id"]), None)
        if row is None:
            sys.exit("정류장 %s 에 노선 %s 가 없음" % (t["station"], t["route_id"]))
        if row["api_id"] not in stop_lists:
            stop_lists[row["api_id"]] = json.loads(post("/map/StopListByRoute.do", route_id=row["api_id"])).get("stopList") or []
            time.sleep(0.25)
        found = stops_to_end(stop_lists[row["api_id"]], stops[t["station"]]["service_id"])
        if found is None:
            sys.exit("노선 %s 정류장 목록에 %s 가 없음" % (t["route_id"], t["station"]))
        turnaround.append(dict(t, route_no=row["route_no"], extra_stops=found[0], terminal=found[1]))
        print("왕복 %s(%s): %s 지나서 %d정류장 뒤 종점 %s -> %s 카드에도" % (row["route_no"], t["route_id"], stops[t["station"]]["name"], found[0], found[1], t["direction"]))
    kst = timezone(timedelta(hours=9))
    OUT.write_text(json.dumps({"generated": datetime.now(kst).isoformat(timespec="minutes"), "stops": out_stops, "turnaround": turnaround},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sid, s in out_stops.items():
        if s["route_ids"] is None:
            names = "/".join(s["route_nos"]) + " 전부" if "route_nos" in s else "전부"
        else:
            names = ", ".join("%s(%s, %s까지 %d정거장)" % (s["routes"][i]["no"] if "routes" in s else "", i, s["gaps"][i]["board"], s["gaps"][i]["stops"]) for i in s["route_ids"]) or "없음"
        print("%s %s [%s]%s: %s" % (sid, s["name"], s["direction"], " -%d분" % s["offset_min"] if "offset_min" in s else "", names))


if __name__ == "__main__":
    main()
