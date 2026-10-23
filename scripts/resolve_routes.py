"""허용 노선별 (도시, routeId, 승차 정류장의 노선 내 순번)을 TAGO에서 한 번 조회해 collector/route_stops.json 으로 저장한다.

위치 기반 표시("N정류장 전")는 버스의 현재 nodeord 와 우리 승차 정류장의 nodeord 차이로 계산하므로,
노선마다 승차 정류장이 몇 번째인지를 미리 알아야 한다. 노선 구성은 거의 안 바뀌어 매번 조회하지 않는다.
노선/정류장 구성이 바뀌면 다시 실행: python scripts/resolve_routes.py  (TAGO_SERVICE_KEY 환경변수 필요, 키는 출력하지 않음)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

OUT = ROOT / "collector" / "route_stops.json"
BASE = "https://apis.data.go.kr/1613000/"
CITIES = ["22", "37390", "37050", "37100"]
GAP_S = 1.3  # 명세: 호출 간 최소 1.2초


def _key() -> str:
    key = os.environ.get("TAGO_SERVICE_KEY")
    if not key and sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            key = winreg.QueryValueEx(k, "TAGO_SERVICE_KEY")[0]
    if not key:
        sys.exit("TAGO_SERVICE_KEY 가 없습니다")
    return key


def _items(resp: dict) -> list:
    body = resp["response"]["body"]
    it = body.get("items") or {}
    it = it.get("item", []) if isinstance(it, dict) else []
    return [it] if isinstance(it, dict) else it


def _call(key: str, svc: str, op: str, **params) -> list:
    q = urllib.parse.urlencode({"serviceKey": key, "_type": "json", "numOfRows": 300, "pageNo": 1, **params})
    req = urllib.request.Request(f"{BASE}{svc}/{op}?{q}", headers={"User-Agent": "Mozilla/5.0"})
    last = None
    for attempt in range(5):  # TAGO 게이트웨이는 200 + 오류 봉투로 일시 실패하는 일이 잦다
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            time.sleep(GAP_S)
            if "response" not in data:
                raise RuntimeError((data.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader") or "오류 봉투")
            if data["response"]["header"]["resultCode"] != "00":
                raise RuntimeError(data["response"]["header"])
            return _items(data)
        except Exception as e:  # 에러와 "없음"을 구분: 에러는 재시도 후 실패로 끝낸다
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"TAGO 실패 {op} {params.get('cityCode')} {params.get('routeNo') or params.get('routeId')}: {last}")


def main() -> int:
    key = _key()
    out = {}
    for direction, cfg in config.DIRECTIONS.items():
        boarding = {(r["city_code"], r["node_id"]) for r in cfg["registrations"]}
        want = sorted(config.ALLOWED_ROUTENOS | config.EXTRA_ALLOWED.get(direction, {}).get("routenos", set()) | {"칠곡3"})
        routes, seen = [], set()
        for routeno in want:
            for city in CITIES:
                for rt in _call(key, "BusRouteInfoInqireService", "getRouteNoList", cityCode=city, routeNo=routeno):
                    # 칠곡3 은 노선 목록 API 가 "칠곡3[동명-칠곡시장-...]" 처럼 구간 설명을 붙여 돌려준다
                    rid, no = str(rt["routeid"]), re.sub(r"\[.*\]$", "", str(rt["routeno"]))
                    if no != routeno or (city, rid) in seen or not config.is_allowed(rid, no, direction):
                        continue
                    seen.add((city, rid))
                    stops = _call(key, "BusRouteInfoInqireService", "getRouteAcctoThrghSttnList", cityCode=city, routeId=rid)
                    ords = [{"node_id": s["nodeid"], "name": s["nodenm"], "ord": int(s["nodeord"])}
                            for s in stops if (city, s["nodeid"]) in boarding]
                    if ords:  # 우리 승차 정류장을 실제로 지나는 노선만. last_ord = 종점(거기선 타지 않는다)
                        routes.append({"city_code": city, "routeid": rid, "routeno": no,
                                       "last_ord": max(int(s["nodeord"]) for s in stops), "boarding": ords})
        # 노선 번호마다 상행/하행 routeid 가 따로 있어 한쪽이 탈락하는 건 정상이다.
        # 그 번호의 routeid 가 이 방향에서 하나도 안 남았을 때만 알린다(예: TAGO 정류장 목록에 승차 정류장이 없는 노선).
        kept = {r["routeno"] for r in routes}
        for routeno in want:
            if routeno not in kept:
                print(f"경고 [{direction}] {routeno}: 승차 정류장을 지나는 routeid 를 찾지 못함 - 위치 표시 불가", file=sys.stderr)
        out[direction] = routes
        print(direction, len(routes), "노선", file=sys.stderr)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
