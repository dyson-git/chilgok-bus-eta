from datetime import date, time, datetime
from collector.resolve_arrivals import ConfirmedArrival
from collector.stats import compute_stats, SlotStats


def test_groups_by_slot_index_across_days():
    data = {
        date(2026, 10, 1): [
            ConfirmedArrival(datetime(2026, 10, 1, 6, 10), "R1", "250"),
            ConfirmedArrival(datetime(2026, 10, 1, 9, 0), "R2", "251"),
        ],
        date(2026, 10, 2): [
            ConfirmedArrival(datetime(2026, 10, 2, 6, 20), "R1", "250"),
            ConfirmedArrival(datetime(2026, 10, 2, 9, 10), "R2", "251"),
        ],
    }
    result = compute_stats(data, as_of=date(2026, 10, 2), window_days=30)
    slot1 = next(s for s in result if s.slot_index == 1)
    assert slot1.min_time == time(6, 10)
    assert slot1.max_time == time(6, 20)
    assert slot1.sample_count == 2


def test_short_day_only_lowers_sample_count_for_its_missing_slot():
    # 하루는 1건만 수집됨(네트워크 오류 등) -> slot_index 2는 다른 날짜들로만 계산되고 크래시 없음
    data = {
        date(2026, 10, 1): [ConfirmedArrival(datetime(2026, 10, 1, 6, 10), "R1", "250")],
        date(2026, 10, 2): [
            ConfirmedArrival(datetime(2026, 10, 2, 6, 15), "R1", "250"),
            ConfirmedArrival(datetime(2026, 10, 2, 9, 10), "R2", "251"),
        ],
    }
    result = compute_stats(data, as_of=date(2026, 10, 2), window_days=30)
    slot2 = next(s for s in result if s.slot_index == 2)
    assert slot2.sample_count == 1


def test_excludes_dates_outside_rolling_window():
    data = {date(2026, 1, 1): [ConfirmedArrival(datetime(2026, 1, 1, 6, 10), "R1", "250")]}
    assert compute_stats(data, as_of=date(2026, 10, 21), window_days=30) == []


def test_empty_input_returns_empty_list():
    assert compute_stats({}, as_of=date(2026, 10, 21)) == []
