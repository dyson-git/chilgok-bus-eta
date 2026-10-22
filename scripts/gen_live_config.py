r"""live-config.js 생성기. collector/config.py 와 서비스키로부터 페이지용 설정을 만든다.

config.py 나 키가 바뀌면 다시 실행: python scripts/gen_live_config.py
키는 환경변수 TAGO_SERVICE_KEY, 없으면 Windows 사용자 환경변수(HKCU\Environment)에서 읽는다.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

OUT = ROOT / "live-config.js"
PREFIX = "window.LIVE_CONFIG = "


def build_directions() -> dict:
    """키를 제외한 설정. 테스트(드리프트 가드)도 이 함수를 쓴다."""
    out = {}
    for name, cfg in config.DIRECTIONS.items():
        extra = config.EXTRA_ALLOWED.get(name, {})
        out[name] = {
            "registrations": [
                {"city_code": r["city_code"], "node_id": r["node_id"]} for r in cfg["registrations"]],
            "routenos": sorted(config.ALLOWED_ROUTENOS | extra.get("routenos", set())),
            "chilgok3_routeids": sorted(
                config.ALLOWED_CHILGOK3_ROUTEIDS | extra.get("chilgok3_routeids", set())),
        }
    return out


def read_key() -> str:
    key = (os.environ.get("TAGO_SERVICE_KEY") or "").strip()
    if not key and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = str(winreg.QueryValueEx(k, "TAGO_SERVICE_KEY")[0]).strip()
        except OSError:
            pass
    return key


def main() -> int:
    key = read_key()
    if not key:
        print("TAGO_SERVICE_KEY not found", file=sys.stderr)
        return 1
    blob = {"serviceKey": key, "directions": build_directions()}
    OUT.write_text(PREFIX + json.dumps(blob, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
