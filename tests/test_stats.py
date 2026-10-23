from datetime import date, time, datetime
from collector.resolve_arrivals import ConfirmedArrival
from collector.stats import compute_stats, SlotStats


def test_groups_by_route_number_and_slot_index_across_days():
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
    r250 = next(s for s in result if s.routeno == "250")
    assert (r250.slot_index, r250.min_time, r250.max_time, r250.sample_count) == (1, time(6, 10), time(6, 20), 2)
    r251 = next(s for s in result if s.routeno == "251")
    assert (r251.slot_index, r251.min_time, r251.max_time, r251.sample_count) == (1, time(9, 0), time(9, 10), 2)


def test_short_day_only_lowers_sample_count_for_its_missing_slot():
    # 하루는 1건만 수집됨(네트워크 오류 등) -> 그 노선의 slot_index 2는 다른 날짜들로만 계산되고 크래시 없음
    data = {
        date(2026, 10, 1): [ConfirmedArrival(datetime(2026, 10, 1, 6, 10), "R1", "250")],
        date(2026, 10, 2): [
            ConfirmedArrival(datetime(2026, 10, 2, 6, 15), "R1", "250"),
            ConfirmedArrival(datetime(2026, 10, 2, 9, 10), "R1", "250"),
        ],
    }
    result = compute_stats(data, as_of=date(2026, 10, 2), window_days=30)
    slot2 = next(s for s in result if s.routeno == "250" and s.slot_index == 2)
    assert slot2.sample_count == 1


def test_missing_route_on_one_day_does_not_shift_other_routes_slots():
    """번호별로 묶는 이유: 예전엔 "그날 몇 번째 차"로만 묶어서, 어떤 날 250이 빠지면 251이 1번 슬롯으로 밀려
    250 의 시각과 섞였다. 노선별로 따로 세면 한 노선의 누락이 다른 노선에 영향을 주지 않는다."""
    data = {
        date(2026, 10, 1): [
            ConfirmedArrival(datetime(2026, 10, 1, 6, 10), "R1", "250"),
            ConfirmedArrival(datetime(2026, 10, 1, 7, 0), "R2", "251"),
        ],
        date(2026, 10, 2): [ConfirmedArrival(datetime(2026, 10, 2, 7, 5), "R2", "251")],  # 250 누락된 날
    }
    result = compute_stats(data, as_of=date(2026, 10, 2), window_days=30)
    r251 = next(s for s in result if s.routeno == "251")
    assert (r251.min_time, r251.max_time, r251.sample_count) == (time(7, 0), time(7, 5), 2)
    r250 = next(s for s in result if s.routeno == "250")
    assert (r250.min_time, r250.max_time, r250.sample_count) == (time(6, 10), time(6, 10), 1)


def test_results_sorted_by_average_time_then_route_number():
    data = {date(2026, 10, 1): [
        ConfirmedArrival(datetime(2026, 10, 1, 9, 0), "R1", "250"),
        ConfirmedArrival(datetime(2026, 10, 1, 6, 0), "R2", "251"),
    ]}
    result = compute_stats(data, as_of=date(2026, 10, 1), window_days=30)
    assert [s.routeno for s in result] == ["251", "250"]


def test_excludes_dates_outside_rolling_window():
    data = {date(2026, 1, 1): [ConfirmedArrival(datetime(2026, 1, 1, 6, 10), "R1", "250")]}
    assert compute_stats(data, as_of=date(2026, 10, 21), window_days=30) == []


def test_empty_input_returns_empty_list():
    assert compute_stats({}, as_of=date(2026, 10, 21)) == []
