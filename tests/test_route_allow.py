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
