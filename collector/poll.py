import json
import os
import sys
import time
from urllib.parse import quote, quote_plus
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

import requests

from collector.config import DIRECTIONS, is_allowed
from collector.rebuild import rebuild_all
from collector.tago_client import TagoApiError, get_arrivals

# Korea has no DST, so a fixed offset avoids needing the tzdata package on Windows.
KST = timezone(timedelta(hours=9))

WINDOW_START = dtime(6, 0, 0)
WINDOW_END = dtime(22, 0, 0)  # 사용자 지시(2026-10-24): 06시부터 22시까지
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (2, 4)  # wait after the 1st / 2nd failure
MIN_CALL_SPACING = 1.2
RETRYABLE = (TagoApiError, requests.RequestException, ValueError)


def is_within_collection_window(now_kst: datetime) -> bool:
    return WINDOW_START <= now_kst.time() <= WINDOW_END


def _scrub(text: str, service_key: str) -> str:
    """Remove the service key (raw and URL-encoded forms) from an error message."""
    if not service_key:
        return text
    for form in {service_key, quote(service_key, safe=""), quote_plus(service_key)}:
        text = text.replace(form, "***")
    return text


def _call_with_retry(call, sleep, state):
    """Run `call()` with retries. Returns (result, exception_or_None).

    `state["waited"]` is the time slept since the previous API call, so that any
    two consecutive arrival calls are at least
    MIN_CALL_SPACING apart (backoff counts).
    """
    last_exc = None
    for attempt in range(MAX_ATTEMPTS):
        if state["called"] and state["waited"] < MIN_CALL_SPACING:
            gap = MIN_CALL_SPACING - state["waited"]
            sleep(gap)
        state["called"] = True
        state["waited"] = 0.0
        try:
            return call(), None
        except RETRYABLE as exc:
            last_exc = exc
        if attempt < MAX_ATTEMPTS - 1:
            wait = BACKOFF_SECONDS[attempt]
            sleep(wait)
            state["waited"] += wait
    return None, last_exc


def _error_text(exc, service_key):
    return f"{type(exc).__name__}: {_scrub(str(exc), service_key)}"


def build_direction_record(direction, cfg, fetch, polled_at):
    """한 방향의 수집 기록. fetch(reg) -> (관측 목록, 오류 문구 | None).
    로컬 수집(run_poll)과 클라우드 가져오기(collector/cloud_import.py)가 같이 쓴다. -> (기록 줄, latest.json 항목)"""
    annotated: list[dict] = []
    errors: list[dict] = []
    for reg in cfg["registrations"]:
        obs_list, err = fetch(reg)
        if err is not None:
            errors.append({"city_code": reg["city_code"], "node_id": reg["node_id"], "error": err})
            continue
        for o in obs_list:
            annotated.append({
                "routeid": o.routeid, "routeno": o.routeno, "eta_min": o.eta_min,
                "city_code": reg["city_code"], "node_id": reg["node_id"],
                "toward": is_allowed(o.routeid, o.routeno, direction),
            })
    best: dict[str, dict] = {}
    for o in annotated:
        if o["toward"] is not True:
            continue
        cur = best.get(o["routeid"])
        if cur is None or o["eta_min"] < cur["eta_min"]:
            best[o["routeid"]] = o
    kept = list(best.values()) + [o for o in annotated if o["toward"] is not True]
    record = {"polled_at": polled_at, "observations": kept, "errors": errors}
    latest = {
        "polled_at": polled_at,
        "observations": [
            {"routeid": o["routeid"], "routeno": o["routeno"], "eta_min": o["eta_min"]}
            for o in best.values()],
        "errors": errors,
    }
    return record, latest


def append_record(data_dir: Path, direction: str, day: str, record: dict) -> None:
    out_dir = Path(data_dir) / "observations" / direction
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{day}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_latest(data_dir: Path, latest: dict) -> None:
    (Path(data_dir) / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")


def run_poll(service_key, directions, now_kst, data_dir, sleep=time.sleep) -> None:
    if not is_within_collection_window(now_kst):
        return
    data_dir = Path(data_dir)
    polled_at = now_kst.isoformat(timespec="seconds")
    day = now_kst.date().isoformat()
    state = {"called": False, "waited": 0.0}
    latest: dict[str, dict] = {}

    def fetch(reg):
        obs_list, exc = _call_with_retry(
            lambda: get_arrivals(service_key, reg["city_code"], reg["node_id"]), sleep, state)
        return obs_list, (None if exc is None else _error_text(exc, service_key))

    for direction, cfg in directions.items():
        record, latest[direction] = build_direction_record(direction, cfg, fetch, polled_at)
        append_record(data_dir, direction, day, record)

    write_latest(data_dir, latest)
    rebuild_all(data_dir, as_of=now_kst.date(), directions=directions)


def main() -> int:
    key = (os.environ.get("TAGO_SERVICE_KEY") or "").strip()
    if not key:
        print("TAGO_SERVICE_KEY environment variable is not set", file=sys.stderr)
        return 1
    data_dir = Path(__file__).resolve().parent.parent / "data"
    run_poll(key, DIRECTIONS, datetime.now(KST), data_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
