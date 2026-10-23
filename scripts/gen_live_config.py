"""live-config.js 생성기. collector/config.py 로부터 페이지용 설정(중계 주소 + 노선 허용 목록)을 만든다.

서비스키는 페이지에 넣지 않는다(Cloudflare Worker 중계가 보관).
config.py 가 바뀌면 다시 실행: python scripts/gen_live_config.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

OUT = ROOT / "live-config.js"
ROUTE_STOPS = ROOT / "collector" / "route_stops.json"  # scripts/resolve_routes.py 가 만든다
RELAY_URL = "https://chilgok-bus-relay.wisdomdy.workers.dev"
PREFIX = "window.LIVE_CONFIG = "


def _arriving(name: str, tracked: dict) -> list:
    out = []
    for a in config.TURNAROUND_ARRIVING.get(name, []):
        t = next((t for ts in tracked.values() for t in ts
                  if t["routeid"] == a["routeid"] and t["city_code"] == a["city_code"]), None)
        if t is None:
            raise SystemExit("TURNAROUND_ARRIVING 노선이 route_stops.json 에 없음: " + a["routeid"])
        out.append({**a, "last_ord": t["last_ord"]})
    return out


def build_directions() -> dict:
    """키를 제외한 설정. 테스트(드리프트 가드)도 이 함수를 쓴다."""
    tracked = json.loads(ROUTE_STOPS.read_text(encoding="utf-8"))
    out = {}
    for name, cfg in config.DIRECTIONS.items():
        extra = config.EXTRA_ALLOWED.get(name, {})
        out[name] = {
            "registrations": [
                {"city_code": r["city_code"], "node_id": r["node_id"]} for r in cfg["registrations"]],
            "routenos": sorted(config.ALLOWED_ROUTENOS | extra.get("routenos", set())),
            "chilgok3_routeids": sorted(
                config.ALLOWED_CHILGOK3_ROUTEIDS | extra.get("chilgok3_routeids", set())),
            "all_routes": name in config.ALL_ROUTES_DIRECTIONS,  # 이 방향은 노선 필터 없이 전부 보여준다
            # 위치 표시용: 노선별 (도시, routeId, 승차 정류장의 노선 내 nodeord)
            "tracked": tracked[name],
            # 종점에서 되돌아가는 왕복 노선: 종점에 다가오는 버스를 "곧 도착"으로 보여준다
            "arriving": _arriving(name, tracked),
        }
    return out


def main() -> int:
    blob = {"relayUrl": RELAY_URL, "directions": build_directions()}
    OUT.write_text(PREFIX + json.dumps(blob, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
