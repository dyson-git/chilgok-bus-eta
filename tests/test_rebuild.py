import json
from datetime import date

from collector.config import DIRECTIONS
from collector.rebuild import rebuild_all


def _snap(ts, obs=(), **extra):
    d = {"polled_at": ts, "observations": [
        {"routeid": r, "routeno": n, "eta_min": e} for r, n, e in obs]}
    d.update(extra)
    return json.dumps(d, ensure_ascii=False)


def _write(data, direction, name, lines):
    p = data / "observations" / direction
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load(data, name):
    return json.loads((data / name).read_text(encoding="utf-8"))


def test_rebuild_all_writes_arrivals_and_stats_json(tmp_path):
    data = tmp_path / "data"
    _write(data, "hakmyeong", "2026-10-01.jsonl", [
        _snap("2026-10-01T08:00:00+09:00", [("R1", "250", 3)]),
        "",
        _snap("2026-10-01T08:01:00+09:00"),
    ])
    rebuild_all(data, as_of=date(2026, 10, 1), directions=DIRECTIONS)
    arrivals = _load(data, "arrivals.json")
    assert arrivals["hakmyeong"] == {"2026-10-01": [
        {"arrival_time": "2026-10-01T08:03:00+09:00", "routeid": "R1", "routeno": "250"}]}
    assert arrivals["dongmyeong"] == {}
    stats = _load(data, "stats.json")
    assert stats["hakmyeong"] == [{"slot_index": 1, "min_time": "08:03",
                                   "max_time": "08:03", "avg_time": "08:03",
                                   "sample_count": 1}]
    assert stats["dongmyeong"] == []


def test_rebuild_all_with_no_observation_files_writes_empty_structures(tmp_path):
    rebuild_all(tmp_path / "data", as_of=date(2026, 10, 1), directions=DIRECTIONS)
    data = tmp_path / "data"
    assert _load(data, "stats.json") == {"hakmyeong": [], "dongmyeong": []}
    assert _load(data, "arrivals.json") == {"hakmyeong": {}, "dongmyeong": {}}


def test_errored_snapshot_does_not_fabricate_arrival(tmp_path):
    data = tmp_path / "data"
    _write(data, "hakmyeong", "2026-10-01.jsonl", [
        _snap("2026-10-01T08:00:00+09:00", [("R1", "250", 3)]),
        _snap("2026-10-01T08:01:00+09:00", errors=["timeout"]),
        _snap("2026-10-01T08:02:00+09:00", [("R1", "250", 1)]),
    ])
    rebuild_all(data, as_of=date(2026, 10, 1), directions=DIRECTIONS)
    assert _load(data, "arrivals.json")["hakmyeong"] == {}


def test_empty_errors_list_is_kept_and_unknown_keys_ignored(tmp_path):
    data = tmp_path / "data"
    _write(data, "dongmyeong", "2026-10-01.jsonl", [
        _snap("2026-10-01T08:00:00+09:00", [("R1", "250", 2)], errors=[], foo=1),
        _snap("2026-10-01T08:01:00+09:00"),
    ])
    rebuild_all(data, as_of=date(2026, 10, 1), directions=DIRECTIONS)
    assert len(_load(data, "arrivals.json")["dongmyeong"]["2026-10-01"]) == 1


def test_bus_spanning_midnight_file_boundary_is_resolved_once(tmp_path):
    data = tmp_path / "data"
    _write(data, "hakmyeong", "2026-10-01.jsonl", [
        _snap("2026-10-01T23:59:00+09:00", [("R1", "250", 4)]),
    ])
    _write(data, "hakmyeong", "2026-10-02.jsonl", [
        _snap("2026-10-02T00:00:00+09:00", [("R1", "250", 3)]),
        _snap("2026-10-02T00:01:00+09:00"),
    ])
    rebuild_all(data, as_of=date(2026, 10, 2), directions=DIRECTIONS)
    arrivals = _load(data, "arrivals.json")["hakmyeong"]
    assert arrivals == {"2026-10-02": [
        {"arrival_time": "2026-10-02T00:03:00+09:00", "routeid": "R1", "routeno": "250"}]}


def test_non_toward_observations_ignored_and_missing_toward_kept(tmp_path):
    data = tmp_path / "data"

    def snap(ts, obs):
        return json.dumps({"polled_at": ts, "observations": obs, "errors": []}, ensure_ascii=False)

    def o(rid, eta, **kw):
        return {"routeid": rid, "routeno": rid, "eta_min": eta, **kw}

    _write(data, "hakmyeong", "2026-10-01.jsonl", [
        snap("2026-10-01T08:00:00+09:00", [o("A", 3, toward=True), o("B", 3, toward=False), o("C", 3)]),
        snap("2026-10-01T08:01:00+09:00", []),
    ])
    rebuild_all(data, as_of=date(2026, 10, 1), directions=DIRECTIONS)
    ids = [a["routeid"] for a in _load(data, "arrivals.json")["hakmyeong"]["2026-10-01"]]
    assert sorted(ids) == ["A", "C"]
