"""칠곡 버스정보시스템에서 화면이 쓸 정류장·노선 설정을 만들어 bis/routes.json 에 쓴다.

실행: python -m bis.build_routes   (노선이 바뀌었을 때만. 약 25회 요청, 요청마다 0.25초 쉰다)
- 동명행 = 학명리 건너2(2479). 동명행 전용 정류장이라 노선을 거르지 않는다(route_ids = null).
- 학명리행 = 학명리 정류소(2483, 학명리 방향 버스가 서는 곳. 건너2 와 다른 정류장). 사용자 방식(2026-10-24):
  학명리 정류소 도착 시간에서 10분을 빼서 동명 기준으로 보여준다. 정거장 수는 노선 정류장 순서로 동명 정류장까지 실제 개수를 뺀다.
  동명 정류장을 먼저 지나는 노선만 남긴다. 9-3 은 학명리 정류소에 안 서고 등골마을입구(2485)에 서서 그 정류장으로 따로 받는다."""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bis.parse import parse_stop_popup, stops_between

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


def post(path, **data):
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode(), headers=HEADERS)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


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
                    found = stops_between(stop_lists[r["api_id"]], REF_IDS, s["service_id"])
                    if found:
                        gaps[r["route_id"]] = {"stops": found[0], "board": found[1]}
                taken.update(gaps)
                entry.update({"route_ids": list(gaps), "gaps": gaps, "offset_min": OFFSET_MIN[sid]})
            out_stops[sid] = entry
    kst = timezone(timedelta(hours=9))
    OUT.write_text(json.dumps({"generated": datetime.now(kst).isoformat(timespec="minutes"), "stops": out_stops}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sid, s in out_stops.items():
        if s["route_ids"] is None:
            names = "전부"
        else:
            names = ", ".join("%s(%s, %s까지 %d정거장)" % (s["routes"][i]["no"], i, s["gaps"][i]["board"], s["gaps"][i]["stops"]) for i in s["route_ids"]) or "없음"
        print("%s %s [%s]%s: %s" % (sid, s["name"], s["direction"], " -%d분" % s["offset_min"] if "offset_min" in s else "", names))


if __name__ == "__main__":
    main()
