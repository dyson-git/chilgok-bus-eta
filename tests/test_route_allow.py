import pytest

from collector.config import is_allowed


@pytest.mark.parametrize("routeid,routeno,expected", [
    ("X", "885", True), ("X", "급행9-3", True), ("X", "9-3", True), ("X", "36-1", True),
    ("X", "300", True), ("X", "34", True), ("X", "34-1", True), ("X", "36", True),
    ("X", "급행3", False), ("X", "527", False), ("X", "730", False), ("X", "885-1", False),
    ("DGB4090003011", "칠곡3", True), ("DGB4090003001", "칠곡3", True),
    ("DGB4090003014", "칠곡3", True), ("DGB4090003015", "칠곡3", True),
    ("DGB4090003013", "칠곡3", False), ("DGB4090003023", "칠곡3", False),
    ("DGB4090003007", "칠곡3", False),
    ("DGB4090003011", "885-1", False),
])
def test_is_allowed(routeid, routeno, expected):
    assert is_allowed(routeid, routeno) is expected


@pytest.mark.parametrize("routeid,routeno,direction,expected", [
    ("X", "885-1", "dongmyeong", True), ("X", "885-1", "hakmyeong", False),
    ("DGB4090003023", "칠곡3", "dongmyeong", True), ("DGB4090003023", "칠곡3", "hakmyeong", False),
    ("X", "885", "dongmyeong", True), ("X", "885", "hakmyeong", True),
    ("DGB4090003011", "칠곡3", "dongmyeong", True), ("DGB4090003011", "칠곡3", "hakmyeong", True),
    # 학명리 건너2 는 동명행 전용 정류소라 거기서 잡히는 버스는 노선과 무관하게 전부 동명으로 간다(사용자 확인 2026-10-22)
    ("DGB4090003013", "칠곡3", "dongmyeong", True), ("X", "527", "dongmyeong", True),
    ("X", "급행3", "dongmyeong", True),
    # 동명 정류소(학명리행)는 여러 방향 버스가 섞이므로 계속 허용 목록으로 거른다
    ("DGB4090003013", "칠곡3", "hakmyeong", False), ("X", "527", "hakmyeong", False), ("X", "급행3", "hakmyeong", False),
])
def test_is_allowed_by_direction(routeid, routeno, direction, expected):
    assert is_allowed(routeid, routeno, direction) is expected
