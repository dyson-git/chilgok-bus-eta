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


# 반대 방향(학명리를 지난 뒤 동명을 거쳐 멀어지는) 노선은 동명 정류소에 와도 학명리행이 아니다(2026-10-24 실측:
# 300 30010 = 가산->학명리 건너2->동명교통->북부정류장. 같은 버스가 동명행 22정류장 / 학명리행 30정류장으로 둘 다 떴다).
@pytest.mark.parametrize("routeid,routeno,direction,expected", [
    ("CGB30010", "300", "hakmyeong", False), ("CGB3410", "34", "hakmyeong", False), ("CGB34-110", "34-1", "hakmyeong", False),
    ("CGB30020", "300", "hakmyeong", True), ("CGB3420", "34", "hakmyeong", True), ("CGB34-120", "34-1", "hakmyeong", True),
    ("CGB30010", "300", "dongmyeong", True),
])
def test_routes_heading_away_from_hakmyeong_are_not_hakmyeong_bound(routeid, routeno, direction, expected):
    assert is_allowed(routeid, routeno, direction) is expected
