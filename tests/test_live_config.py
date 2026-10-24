import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_live_config  # noqa: E402
from collector import config  # noqa: E402


def _load():
    text = (ROOT / "live-config.js").read_text(encoding="utf-8")
    m = re.fullmatch(r"window\.LIVE_CONFIG = (.*);\s*", text, re.S)
    assert m, "live-config.js format changed"
    return json.loads(m.group(1))


def test_live_config_matches_collector_config():
    cfg = _load()
    assert cfg["directions"] == gen_live_config.build_directions()


def test_live_config_marks_dongmyeong_as_all_routes_only():
    cfg = _load()["directions"]
    assert cfg["dongmyeong"]["all_routes"] is True
    assert cfg["hakmyeong"]["all_routes"] is False


def test_hakmyeong_shows_885_outbound_arriving_at_dongmyeong_terminal():
    """885 는 구미에서 동명(종점)까지 왔다가 바로 되돌아가는 왕복 노선이라, 학명리행 노선(GMB88520)은 종점에서
    되돌아간 뒤에야 위치 목록에 뜬다. 그래서 학명리방향 화면에는 종점에 다가오는 구미발 버스를 따로 보여준다."""
    cfg = _load()["directions"]
    arr = cfg["hakmyeong"]["arriving"]
    assert [(a["routeno"], a["routeid"], a["city_code"], a["last_ord"]) for a in arr] == [
        ("885", "GMB88510", "37050", 63)]
    assert arr[0]["terminal"] == "동명"
    assert cfg["dongmyeong"]["arriving"] == []


def test_arriving_routes_are_tracked_so_the_worker_fetches_their_positions():
    cfg = _load()["directions"]
    tracked = {(t["city_code"], t["routeid"]) for d in cfg.values() for t in d["tracked"]}
    for d in cfg.values():
        for a in d["arriving"]:
            assert (a["city_code"], a["routeid"]) in tracked


def test_worker_refresh_button_bypasses_cache_but_not_within_fifteen_seconds():
    js = (Path(__file__).resolve().parents[1] / "worker" / "relay.js").read_text(encoding="utf-8")
    assert 'searchParams.get("fresh") === "1"' in js
    assert "FRESH_MIN_AGE_MS = 15000" in js


def test_worker_caches_failures_briefly_and_successes_longer_to_stay_under_tago_rate_limit():
    """TAGO 는 짧은 시간에 호출이 몰리면 429 를 건다(2026-10-23 확인: 페이지 한 번에 36회). 실패 응답도 잠깐 들고 있어야
    사용자 여러 명/자동 갱신이 제한을 더 키우지 않고, 도착정보는 화면이 초 단위로 줄여 보여주므로 오래 들고 있어도 된다."""
    js = (Path(__file__).resolve().parents[1] / "worker" / "relay.js").read_text(encoding="utf-8")
    num = lambda name: int(re.search(r"const " + name + r" = (\d+);", js).group(1))
    assert num("CACHE_TTL_S") >= 60 and num("LOC_CACHE_TTL_S") >= 45
    assert 0 < num("FAIL_CACHE_TTL_S") <= 15 < num("PARTIAL_CACHE_TTL_S") <= num("CACHE_TTL_S")
    assert js.count("cacheTtl(") >= 3  # 정의 1 + /all + /loc
    assert "CACHE_MIN_OK" not in js    # 실패 응답도 캐시하므로 "충분히 성공했을 때만 캐시" 규칙은 없다


def test_worker_stays_under_cloudflare_subrequest_limit():
    """Workers 무료 한도는 요청 1회당 외부 호출 50개. /loc 는 노선 N개 x 시도 횟수, /all 은 정류소 M개 x 시도 횟수라
    TAGO 가 오류를 내서 재시도가 몰려도 이 곱이 50 을 넘으면 뒤쪽 노선이 'Too many subrequests' 로 통째로 실패한다."""
    js = (Path(__file__).resolve().parents[1] / "worker" / "relay.js").read_text(encoding="utf-8")
    attempts = int(re.search(r"const ATTEMPTS = (\d+);", js).group(1))
    loc_attempts = int(re.search(r"const LOC_ATTEMPTS = (\d+);", js).group(1))
    routes = {(t["city_code"], t["routeid"]) for d in _load()["directions"].values() for t in d["tracked"]}
    nodes = {(r["city_code"], r["node_id"]) for d in _load()["directions"].values() for r in d["registrations"]}
    assert len(routes) * loc_attempts <= 50
    assert len(nodes) * attempts <= 50


def test_live_config_has_no_key():
    text = (ROOT / "live-config.js").read_text(encoding="utf-8")
    assert "serviceKey" not in text
    assert not re.search(r"[A-Za-z0-9+/=%]{80,}", text)
    assert _load()["relayUrl"].startswith("https://")


def test_worker_allowlist_matches_collector_config():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_NODES\s*=\s*new Set\(\[(.*?)\]\)", js, re.S).group(1)
    nodes = set(re.findall(r'"([^"]+:[^"]+)"', block))
    expected = {f"{r['city_code']}:{r['node_id']}"
                for d in config.DIRECTIONS.values() for r in d["registrations"]}
    assert nodes == expected


def test_worker_has_all_route():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    assert '"/all"' in js and "fetchAllNodes" in js


def test_worker_has_retry_timeout_and_cache():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    for marker in ("AbortSignal.timeout", "caches.default", "X-Relay-Cache", "MAX_INFLIGHT", "BACKOFF_MS", "BUDGET_MS"):
        assert marker in js, marker


# ---- 위치 기반 표시(2026-10-22): TAGO 도착 "예측" API 는 칠곡3 이 약 6정류장/8분 안으로 와야 내놓는다.
# 위치 API(getRouteAcctoBusLcList)는 운행 중인 버스를 항상 준다. 그래서 허용 노선별로
# (도시, routeId, 승차 정류장의 노선 내 nodeord)를 정적으로 들고, 화면은 버스의 현재 nodeord 와
# 승차 정류장 nodeord 의 차이("N정류장 전")만 보여준다. 시간 예측은 하지 않는다.

def test_live_config_tracked_routes_are_allowed_and_board_at_our_stops():
    cfg = _load()
    for name, d in cfg["directions"].items():
        regs = {(r["city_code"], r["node_id"]) for r in d["registrations"]}
        assert d["tracked"], f"{name}: tracked 노선이 비어 있음"
        for t in d["tracked"]:
            assert config.is_allowed(t["routeid"], t["routeno"], name), (name, t)
            assert t["boarding"], (name, t)
            for b in t["boarding"]:
                assert (t["city_code"], b["node_id"]) in regs, (name, t["routeid"], b)
                assert isinstance(b["ord"], int)


def test_live_config_tracks_chilgok3_both_directions():
    """회귀: 노선 목록 API 가 칠곡3 을 "칠곡3[동명-칠곡시장-...]" 로 돌려줘서 정확 일치 비교가 칠곡3 을 통째로 버렸었다."""
    cfg = _load()
    for name in ("hakmyeong", "dongmyeong"):
        ids = {t["routeid"] for t in cfg["directions"][name]["tracked"] if t["routeno"] == "칠곡3"}
        assert ids, f"{name}: 칠곡3 이 추적 대상에 없음"


def test_worker_loc_allowlist_matches_tracked_routes():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_ROUTES\s*=\s*new Set\(\[(.*?)\]\)", js, re.S).group(1)
    routes = set(re.findall(r'"([^"]+:[^"]+)"', block))
    expected = {f"{t['city_code']}:{t['routeid']}"
                for d in _load()["directions"].values() for t in d["tracked"]}
    assert routes == expected


def test_live_config_tracked_routes_know_their_terminus():
    """종점(last_ord)에서는 승차하지 않는다 - 안 그러면 학명리로 가는 중인 버스가 "동명교통(종점)까지 47정류장 전"으로 잘못 잡힌다."""
    for name, d in _load()["directions"].items():
        for t in d["tracked"]:
            assert isinstance(t["last_ord"], int), (name, t["routeid"])
            assert t["last_ord"] >= max(b["ord"] for b in t["boarding"]), (name, t["routeid"])


def test_live_config_hakmyeong_drops_routes_heading_away():
    d = _load()["directions"]["hakmyeong"]
    assert {"CGB30010", "CGB3410", "CGB34-110"} <= set(d["away_routeids"])
    assert "CGB30010" not in {t["routeid"] for t in d["tracked"]}
    assert "CGB30020" in {t["routeid"] for t in d["tracked"]}
