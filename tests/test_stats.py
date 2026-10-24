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


# ---- 2026-10-24 사용자 지시: "칠곡3번이 하루 여러 대 있는데 어젠 3시, 오늘 11시를 평균 내면 어떡하니.
#      비슷한 시간대에만 카운트해야지" -> N번째 차가 아니라 시각이 가까운 것끼리(한 줄 안 최대 30분) 묶는다 ----

def _arr(d, h, m, routeno="칠곡3"):
    return ConfirmedArrival(datetime(2026, 10, d, h, m), "R", routeno)


def test_same_route_at_far_apart_times_on_different_days_is_not_averaged():
    data = {date(2026, 10, 23): [_arr(23, 15, 3)], date(2026, 10, 24): [_arr(24, 9, 43)]}
    result = compute_stats(data, as_of=date(2026, 10, 24))
    assert [(s.min_time, s.max_time, s.sample_count) for s in result] == [(time(9, 43), time(9, 43), 1), (time(15, 3), time(15, 3), 1)]


def test_same_route_at_similar_times_across_days_is_one_row():
    data = {date(2026, 10, 23): [_arr(23, 12, 1)], date(2026, 10, 24): [_arr(24, 12, 20)]}
    (row,) = compute_stats(data, as_of=date(2026, 10, 24))
    assert (row.min_time, row.max_time, row.avg_time, row.sample_count) == (time(12, 1), time(12, 20), time(12, 10), 2)


def test_one_row_never_spreads_more_than_30_minutes():
    data = {date(2026, 10, 22): [_arr(22, 10, 0)], date(2026, 10, 23): [_arr(23, 10, 25)], date(2026, 10, 24): [_arr(24, 10, 40)]}
    result = compute_stats(data, as_of=date(2026, 10, 24))
    assert [(s.min_time, s.max_time, s.sample_count) for s in result] == [(time(10, 0), time(10, 25), 2), (time(10, 40), time(10, 40), 1)]


def test_two_buses_of_the_same_route_on_the_same_day_stay_in_separate_rows():
    data = {date(2026, 10, 24): [_arr(24, 9, 0), _arr(24, 9, 20)]}
    result = compute_stats(data, as_of=date(2026, 10, 24))
    assert [(s.min_time, s.sample_count) for s in result] == [(time(9, 0), 1), (time(9, 20), 1)]


def test_other_route_numbers_are_never_mixed_into_the_row():
    data = {date(2026, 10, 23): [_arr(23, 12, 1)], date(2026, 10, 24): [_arr(24, 12, 5, routeno="급행9-3")]}
    result = compute_stats(data, as_of=date(2026, 10, 24))
    assert sorted((s.routeno, s.sample_count) for s in result) == [("급행9-3", 1), ("칠곡3", 1)]
