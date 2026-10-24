import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from collector.config import AWAY_ROUTEIDS
from collector.models import ArrivalObservation
from collector.resolve_arrivals import ConfirmedArrival, PollSnapshot, resolve_arrivals
from collector.stats import compute_stats

KST = timezone(timedelta(hours=9))


def _to_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _load_snapshots(direction_dir: Path, direction: str) -> list[PollSnapshot]:
    snapshots: list[PollSnapshot] = []
    if not direction_dir.is_dir():
        return snapshots
    for path in sorted(direction_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                if raw.get("errors"):
                    # A failed poll would look like "every bus arrived".
                    continue
                snapshots.append(PollSnapshot(
                    polled_at=_to_kst(datetime.fromisoformat(raw["polled_at"])),
                    observations=[
                        ArrivalObservation(o["routeid"], o["routeno"], float(o["eta_min"]))
                        for o in raw.get("observations", [])
                        # 예전 기록은 반대 방향(AWAY_ROUTEIDS, 2026-10-24 추가)도 toward 로 저장했다 - 지금 빼고 센다
                        if o.get("toward", True) is True and o["routeid"] not in AWAY_ROUTEIDS.get(direction, set())
                    ],
                ))
    snapshots.sort(key=lambda s: s.polled_at)
    return snapshots


def rebuild_all(data_dir: Path, as_of: date, directions: dict[str, dict]) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    arrivals_out: dict[str, dict] = {}
    stats_out: dict[str, list] = {}

    for direction in directions:
        snapshots = _load_snapshots(data_dir / "observations" / direction, direction)
        confirmed = resolve_arrivals(snapshots)
        by_date: dict[date, list[ConfirmedArrival]] = defaultdict(list)
        for c in confirmed:
            by_date[_to_kst(c.arrival_time).date()].append(c)

        arrivals_out[direction] = {
            d.isoformat(): [
                {
                    "arrival_time": _to_kst(c.arrival_time).isoformat(timespec="seconds"),
                    "routeid": c.routeid,
                    "routeno": c.routeno,
                }
                for c in items
            ]
            for d, items in sorted(by_date.items())
        }
        stats_out[direction] = [
            {
                "routeno": s.routeno,
                "slot_index": s.slot_index,
                "min_time": s.min_time.strftime("%H:%M"),
                "max_time": s.max_time.strftime("%H:%M"),
                "avg_time": s.avg_time.strftime("%H:%M"),
                "sample_count": s.sample_count,
            }
            for s in compute_stats(dict(by_date), as_of=as_of)
        ]

    for name, obj in (("arrivals.json", arrivals_out), ("stats.json", stats_out)):
        (data_dir / name).write_text(
            json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
