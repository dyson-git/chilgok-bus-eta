"""클라우드 수집(2026-10-24): Cloudflare Worker 가 5분마다 TAGO 도착정보를 KV 에 쌓고(worker/relay.js scheduled),
GitHub Actions 가 1시간마다 가져와 로컬 수집(collector/poll.py)과 같은 기록으로 바꿔 쓴다(collector/cloud_import.py).
PC 를 꺼도 시간표 기록이 끊기지 않게 하려는 것."""
import json
import re
from datetime import date
from pathlib import Path

from collector.cloud_import import import_snapshots, records_from_snapshot
from collector.config import DIRECTIONS

ROOT = Path(__file__).resolve().parents[1]


def _snapshot(fetched_at, results):
    full = {f'{r["city_code"]}:{r["node_id"]}': {"ok": True, "items": []}
            for d in DIRECTIONS.values() for r in d["registrations"]}
    full.update(results)
    return {"fetched_at": fetched_at, "results": full}


def test_snapshot_becomes_the_same_records_as_a_local_poll():
    snap = _snapshot("2026-10-24T07:20:01.297Z", {
        "37390:CGB2479": {"ok": True, "items": [{"routeid": "CGB30010", "routeno": "300", "arrtime": 2772}]},
        "37050:GMB2479": {"ok": False, "error": "TAGO 04"},
        "22:DGB3690003750": {"ok": True, "items": [{"routeid": "DGB3000527000", "routeno": "527", "arrtime": 600},
                                                   {"routeid": "DGB4090003014", "routeno": "칠곡3", "arrtime": 165}]},
    })
    polled_at, records = records_from_snapshot(snap, DIRECTIONS)
    assert polled_at == "2026-10-24T16:20:01+09:00"                     # 기록은 한국 시각
    dong = records["dongmyeong"]
    assert dong["polled_at"] == polled_at
    assert dong["observations"] == [{"routeid": "CGB30010", "routeno": "300", "eta_min": 46.2,
                                     "city_code": "37390", "node_id": "CGB2479", "toward": True}]
    assert dong["errors"] == [{"city_code": "37050", "node_id": "GMB2479", "error": "TAGO 04"}]
    hak = records["hakmyeong"]
    assert [(o["routeno"], o["toward"]) for o in hak["observations"]] == [("칠곡3", True), ("527", False)]
    assert hak["errors"] == []


def test_a_stop_missing_from_the_snapshot_counts_as_an_error_not_as_no_bus():
    snap = _snapshot("2026-10-24T07:20:01Z", {})
    del snap["results"]["37390:CGB2479"]
    _, records = records_from_snapshot(snap, DIRECTIONS)
    assert {"city_code": "37390", "node_id": "CGB2479", "error": "결과 없음"} in records["dongmyeong"]["errors"]


def test_snapshots_outside_collection_hours_are_skipped():
    assert records_from_snapshot(_snapshot("2026-10-24T13:01:00Z", {}), DIRECTIONS) is None   # 22:01 KST
    assert records_from_snapshot(_snapshot("2026-10-24T13:00:00Z", {}), DIRECTIONS) is not None   # 22:00 KST 까지


def _lines(data, direction, day):
    p = data / "observations" / direction / f"{day}.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def test_import_appends_only_snapshots_newer_than_what_is_already_recorded_and_rebuilds(tmp_path):
    data = tmp_path / "data"
    d = data / "observations" / "dongmyeong"
    d.mkdir(parents=True)
    (d / "2026-10-24.jsonl").write_text(json.dumps({"polled_at": "2026-10-24T16:21:00+09:00", "observations": [], "errors": []}) + "\n", encoding="utf-8")
    bus = {"37390:CGB2479": {"ok": True, "items": [{"routeid": "CGB30010", "routeno": "300", "arrtime": 120}]}}
    snaps = [_snapshot("2026-10-24T07:20:00Z", bus),          # 16:20 - 이미 로컬 수집이 쓴 시각보다 이르다 -> 건너뜀
             _snapshot("2026-10-24T07:25:00Z", bus),          # 16:25
             _snapshot("2026-10-24T07:25:00Z", bus),          # 같은 것 두 번 -> 한 번만
             _snapshot("2026-10-24T07:30:00Z", {})]           # 16:30 (버스 지나감)
    n = import_snapshots(snaps, data, DIRECTIONS)
    assert n == 2
    assert [r["polled_at"] for r in _lines(data, "dongmyeong", "2026-10-24")] == [
        "2026-10-24T16:21:00+09:00", "2026-10-24T16:25:00+09:00", "2026-10-24T16:30:00+09:00"]
    assert [r["polled_at"] for r in _lines(data, "hakmyeong", "2026-10-24")] == ["2026-10-24T16:25:00+09:00", "2026-10-24T16:30:00+09:00"]
    latest = json.loads((data / "latest.json").read_text(encoding="utf-8"))
    assert latest["dongmyeong"]["polled_at"] == "2026-10-24T16:30:00+09:00"
    arrivals = json.loads((data / "arrivals.json").read_text(encoding="utf-8"))
    assert arrivals["dongmyeong"]["2026-10-24"][0]["routeno"] == "300"   # 시간표도 다시 만든다
    assert import_snapshots(snaps, data, DIRECTIONS) == 0                 # 다시 돌려도 중복 없음


def test_relay_collects_every_five_minutes_into_kv_and_serves_it_by_hour():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    assert "async scheduled(" in js
    assert re.search(r"env\.OBS\.put\(\s*\"obs:\"", js)                 # 수집 한 번 = KV 키 하나(읽고 고쳐 쓰지 않는다)
    assert "expirationTtl" in js
    assert 'url.pathname === "/obs"' in js


def test_github_imports_hourly_and_commits_data():
    wf = (ROOT / ".github" / "workflows" / "import.yml").read_text(encoding="utf-8")
    assert re.search(r"cron: \"\d+ \* \* \* \*\"", wf)
    assert "python -m collector.cloud_import" in wf
    assert "git push origin HEAD:main" in wf


def test_import_fetches_every_collection_hour_since_the_last_record_up_to_7_days():
    # PC 가 꺼져 있었거나 GitHub 예약 실행이 밀려도 빠짐없이 가져온다(KV 는 7일 보관). 수집 시간(06~22시) 밖 시간은 안 묻는다.
    from datetime import datetime, timedelta, timezone
    from collector.cloud_import import hours_to_fetch
    kst = timezone(timedelta(hours=9))
    now = datetime(2026, 10, 25, 7, 10, tzinfo=kst)
    assert hours_to_fetch(datetime(2026, 10, 24, 18, 30, tzinfo=kst), now) == [
        "2026-10-24T18", "2026-10-24T19", "2026-10-24T20", "2026-10-24T21", "2026-10-24T22", "2026-10-25T06", "2026-10-25T07"]
    assert hours_to_fetch(None, now)[0] == "2026-10-18T07"
    assert hours_to_fetch(datetime(2026, 9, 1, 12, 0, tzinfo=kst), now)[0] == "2026-10-18T07"


