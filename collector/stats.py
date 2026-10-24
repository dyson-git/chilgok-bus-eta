from dataclasses import dataclass
from collections import defaultdict
from datetime import date, time, timedelta

from collector.resolve_arrivals import ConfirmedArrival


# 한 줄(같은 시간대) 안의 가장 이른 시각과 가장 늦은 시각 차이의 최대값(분). 2026-10-24 사용자 지시:
# "비슷한 시간대에만 카운트해야지" - 어제 15시와 오늘 11시의 칠곡3 를 평균 내지 않는다.
SLOT_SPREAD_MAX_MIN = 30


@dataclass
class SlotStats:
    """Statistics for one route number's arrivals at a similar time of day, across multiple days."""
    routeno: str
    slot_index: int
    min_time: time
    max_time: time
    avg_time: time
    sample_count: int


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def compute_stats(
    confirmed_by_date: dict[date, list[ConfirmedArrival]],
    as_of: date,
    window_days: int = 30
) -> list[SlotStats]:
    """
    노선 번호별로, 날짜가 달라도 시각이 가까운 도착끼리 한 줄로 묶어 최소/최대/평균 시각과 기록 일수를 낸다.

    1. as_of - window_days 이전 날짜는 버린다.
    2. 노선 번호마다 모든 날짜의 도착을 하루 중 시각 순으로 늘어놓는다.
    3. 앞에서부터, 지금 줄의 첫 시각에서 SLOT_SPREAD_MAX_MIN 분 안이고 그 줄에 같은 날짜가 아직 없으면 그 줄에 넣고,
       아니면 새 줄을 시작한다. 그래서 한 줄은 최대 30분 폭이고, 같은 날 두 대(배차가 촘촘한 노선)는 다른 줄이 된다.
       (예전에는 "그날 그 노선의 N번째 차"끼리 묶어서, 어떤 날 앞차를 못 잡으면 다른 시간대 차가 같은 줄로 섞였다.)
    4. slot_index 는 노선별 줄 번호(시각 순, 1부터).

    Returns: 평균 시각, 노선 번호, slot_index 순으로 정렬한 SlotStats 목록
    """
    cutoff_date = as_of - timedelta(days=window_days)
    valid_dates = sorted(d for d in confirmed_by_date if d > cutoff_date)
    if not valid_dates:
        return []

    per_route: dict[str, list[tuple[time, date]]] = defaultdict(list)
    for d in valid_dates:
        for arrival in confirmed_by_date[d]:
            per_route[arrival.routeno].append((arrival.arrival_time.time(), d))

    results = []
    for routeno, items in per_route.items():
        rows: list[list[tuple[time, date]]] = []
        for t, d in sorted(items):
            row = rows[-1] if rows else None
            if row and _minutes(t) - _minutes(row[0][0]) <= SLOT_SPREAD_MAX_MIN and d not in {x[1] for x in row}:
                row.append((t, d))
            else:
                rows.append([(t, d)])
        for slot_index, row in enumerate(rows, start=1):
            times = [t for t, _ in row]
            avg_minutes = round(sum(_minutes(t) for t in times) / len(times))
            results.append(SlotStats(
                routeno=routeno,
                slot_index=slot_index,
                min_time=min(times),
                max_time=max(times),
                avg_time=time(avg_minutes // 60, avg_minutes % 60),
                sample_count=len({d for _, d in row}),
            ))

    results.sort(key=lambda s: (s.avg_time, s.routeno, s.slot_index))
    return results
