"""클라우드 수집 가져오기 (2026-10-24, PC 를 꺼도 시간표 기록이 이어지게).

Cloudflare Worker(worker/relay.js scheduled)가 5분마다 전 정류소 TAGO 도착정보를 KV 에 쌓고, 이 모듈이 그것을
로컬 수집(collector/poll.py)과 똑같은 기록 줄로 바꿔 data/observations 에 붙이고 시간표(stats.json)를 다시 만든다.
GitHub Actions(.github/workflows/import.yml)가 1시간마다 실행: python -m collector.cloud_import

스냅숏 = {"fetched_at": ISO(UTC), "results": {"도시:정류소": {"ok": true, "items": [{routeid, routeno, arrtime}]}
                                                | {"ok": false, "error": "..."}}}
이미 기록된 가장 늦은 시각보다 뒤의 스냅숏만 붙인다(로컬 수집과 겹치지 않게, 여러 번 돌려도 중복 없이).
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

from collector.config import DIRECTIONS
from collector.models import ArrivalObservation
from collector.poll import (KST, append_record, build_direction_record, is_within_collection_window,
                            write_latest)
from collector.rebuild import rebuild_all

RELAY_URL = "https://chilgok-bus-relay.wisdomdy.workers.dev"
KEEP_DAYS = 7  # KV 보관 기간(worker/relay.js OBS_TTL_S). 이보다 오래 못 가져왔으면 그 앞은 이미 지워졌다


def records_from_snapshot(snapshot, directions):
    """스냅숏 -> (한국 시각 polled_at, {방향: 기록 줄}). 수집 시간 밖이면 None."""
    got = _convert(snapshot, directions)
    return None if got is None else got[:2]


def _convert(snapshot, directions):
    """스냅숏 -> (polled_at, {방향: 기록 줄}, {방향: latest.json 항목}) | None(수집 시간 밖)."""
    now_kst = datetime.fromisoformat(snapshot["fetched_at"].replace("Z", "+00:00")).astimezone(KST)
    if not is_within_collection_window(now_kst):
        return None
    polled_at = now_kst.isoformat(timespec="seconds")
    results = snapshot.get("results") or {}

    def fetch(reg):
        r = results.get(f'{reg["city_code"]}:{reg["node_id"]}')
        if not r:
            return None, "결과 없음"
        if not r.get("ok"):
            return None, str(r.get("error") or "실패")
        return [ArrivalObservation(str(i["routeid"]), str(i["routeno"]), int(i["arrtime"]) / 60)
                for i in r.get("items") or []], None

    records, latest = {}, {}
    for direction, cfg in directions.items():
        records[direction], latest[direction] = build_direction_record(direction, cfg, fetch, polled_at)
    return polled_at, records, latest


def _last_recorded(data_dir: Path, directions) -> datetime | None:
    last = None
    for direction in directions:
        files = sorted((data_dir / "observations" / direction).glob("*.jsonl"))
        for path in files[-2:]:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    t = datetime.fromisoformat(json.loads(line)["polled_at"])
                    last = t if last is None or t > last else last
    return last


def import_snapshots(snapshots, data_dir, directions) -> int:
    """새 스냅숏을 기록에 붙이고 latest.json·시간표를 다시 만든다. 붙인 스냅숏 수를 돌려준다."""
    data_dir = Path(data_dir)
    last = _last_recorded(data_dir, directions)
    done, newest = set(), None
    for snap in sorted(snapshots, key=lambda s: s["fetched_at"]):
        got = _convert(snap, directions)
        if got is None:
            continue
        polled_at, records, latest = got
        t = datetime.fromisoformat(polled_at)
        if polled_at in done or (last is not None and t <= last):
            continue
        for direction, record in records.items():
            append_record(data_dir, direction, t.date().isoformat(), record)
        done.add(polled_at)
        newest = (t, latest)
    if newest is None:
        return 0
    write_latest(data_dir, newest[1])
    rebuild_all(data_dir, as_of=newest[0].date(), directions=directions)
    return len(done)


def hours_to_fetch(last: datetime | None, now_kst: datetime) -> list[str]:
    """가져올 한국 시각 시간들("YYYY-MM-DDTHH"): 마지막 기록 시간부터 지금까지(최대 7일 전부터), 수집 시간(06~22시)만.
    PC 가 꺼져 있었거나 GitHub 예약 실행이 밀려도 빠짐없이 가져오려는 것(이미 기록된 건 import_snapshots 가 건너뛴다)."""
    start = now_kst - timedelta(days=KEEP_DAYS)
    if last is not None and last.astimezone(KST) > start:
        start = last.astimezone(KST)
    t = start.replace(minute=0, second=0, microsecond=0)
    out = []
    while t <= now_kst:
        if 6 <= t.hour <= 22:
            out.append(t.strftime("%Y-%m-%dT%H"))
        t += timedelta(hours=1)
    return out


def import_tracks(tracks, data_dir) -> int:
    """대구 BIS 따라가기(worker /trk, 2026-10-28)를 data/track/<한국 날짜>.jsonl 에 붙인다. 이미 있는 started 는 건너뛴다.
    KV 에는 7일만 남으므로, 예상 시각과 실제 지나간 시각 비교를 나중에도 할 수 있게 그대로 옮겨 둔다."""
    out_dir = Path(data_dir) / "track"
    added = 0
    for rec in sorted(tracks, key=lambda r: r["started"]):
        day = datetime.fromisoformat(rec["started"].replace("Z", "+00:00")).astimezone(KST).date().isoformat()
        path = out_dir / f"{day}.jsonl"
        have = set()
        if path.exists():
            have = {json.loads(l)["started"] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}
        if rec["started"] in have:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added += 1
    return added


def last_track(data_dir) -> datetime | None:
    """data/track 의 가장 늦은 started(한국 시각). TAGO 기록과 따로 센다 - 따라가기는 늦게 시작해 빠진 시간이 있을 수 있다."""
    files = sorted((Path(data_dir) / "track").glob("*.jsonl"))
    if not files:
        return None
    lines = [l for l in files[-1].read_text(encoding="utf-8").splitlines() if l.strip()]
    return max(datetime.fromisoformat(json.loads(l)["started"].replace("Z", "+00:00")).astimezone(KST) for l in lines) if lines else None


def fetch_hours(hours: list[str], path: str = "/obs") -> list:
    snaps = []
    for hour in hours:
        r = requests.get(RELAY_URL + path, params={"hour": hour}, timeout=30, headers={"User-Agent": "chilgok-bus-eta-import"})
        r.raise_for_status()
        snaps += r.json()
    return snaps


def main() -> int:
    data_dir = Path(__file__).resolve().parent.parent / "data"
    hours = hours_to_fetch(_last_recorded(data_dir, DIRECTIONS), datetime.now(KST))
    snaps = fetch_hours(hours)
    n = import_snapshots(snaps, data_dir, DIRECTIONS)
    print(f"{hours[0] if hours else '-'} ~ {hours[-1] if hours else '-'} ({len(hours)}시간) 스냅숏 {len(snaps)}개 중 {n}개 기록")
    t = import_tracks(fetch_hours(hours_to_fetch(last_track(data_dir), datetime.now(KST)), "/trk"), data_dir)
    print(f"대구 BIS 따라가기 {t}개 기록")
    return 0


if __name__ == "__main__":
    sys.exit(main())
