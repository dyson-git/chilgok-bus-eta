from datetime import datetime
from collector.models import ArrivalObservation
from collector.resolve_arrivals import PollSnapshot, ConfirmedArrival, resolve_arrivals


def dt(hour: int, minute: int) -> datetime:
    """Helper to create datetime for 2026-10-21."""
    return datetime(2026, 10, 21, hour, minute)


def test_confirms_arrival_from_last_observation_before_disappearing():
    # 13:00 ETA10 -> 13:05 ETA5 -> 13:10 사라짐 => 확정 13:10 (spec 예시 그대로)
    snapshots = [
        PollSnapshot(dt(13, 0), [ArrivalObservation("R1", "250", 10.0)]),
        PollSnapshot(dt(13, 5), [ArrivalObservation("R1", "250", 5.0)]),
        PollSnapshot(dt(13, 10), []),
    ]
    result = resolve_arrivals(snapshots)
    assert result == [ConfirmedArrival(dt(13, 10), "R1", "250")]


def test_discards_candidate_that_disappears_while_eta_still_large():
    # ETA 20분짜리가 다음 폴링(5분 뒤)에 바로 사라짐 -> 노이즈로 간주, 기록 안 함
    snapshots = [
        PollSnapshot(dt(13, 0), [ArrivalObservation("R1", "250", 20.0)]),
        PollSnapshot(dt(13, 5), []),
    ]
    assert resolve_arrivals(snapshots) == []


def test_candidate_still_open_at_end_of_day_is_not_recorded():
    snapshots = [PollSnapshot(dt(21, 25), [ArrivalObservation("R1", "250", 3.0)])]
    assert resolve_arrivals(snapshots) == []


def test_empty_snapshots_produce_no_arrivals():
    assert resolve_arrivals([]) == []
