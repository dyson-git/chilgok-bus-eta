import json
import os
from datetime import date
from pathlib import Path

import requests

from collector.tago_client import TagoApiError

ROUTE_STOPS_URL = "https://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteAcctoThrghSttnList"
PAGE_SIZE = 300


def fetch_route_stops(service_key: str, city_code: str, route_id: str) -> list[tuple[int, str, str]]:
    """Return a route's stops as (nodeord, nodeid, nodenm), sorted by nodeord."""
    stops: list[tuple[int, str, str]] = []
    page = 1
    while True:
        params = {
            "serviceKey": service_key,
            "cityCode": city_code,
            "routeId": route_id,
            "numOfRows": PAGE_SIZE,
            "pageNo": page,
            "_type": "json",
        }
        data = requests.get(ROUTE_STOPS_URL, params=params, timeout=15).json()
        if "response" not in data:
            header = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
            raise TagoApiError(
                f"TAGO API error: {header.get('errMsg', 'Unknown error')} "
                f"(code: {header.get('returnReasonCode', 'Unknown')})")
        resp = data["response"]
        code = resp.get("header", {}).get("resultCode")
        if code and code != "00":
            raise TagoApiError(
                f"TAGO API error: {resp['header'].get('resultMessage', 'Unknown error')} (code: {code})")
        body = resp["body"]
        items = body.get("items")
        if not items:
            break
        item_list = items["item"]
        if isinstance(item_list, dict):
            item_list = [item_list]
        for it in item_list:
            stops.append((int(it["nodeord"]), str(it["nodeid"]), str(it["nodenm"])))
        if not item_list or len(stops) >= int(body.get("totalCount", 0)):
            break
        page += 1
    stops.sort(key=lambda s: s[0])
    return stops


def route_goes_toward(stops, boarding_node_id: str, destination_keywords: list[str]) -> bool:
    """True if some visit to the boarding stop is followed by a stop whose name has a keyword."""
    ordered = sorted(stops, key=lambda s: s[0])
    for i, (_, node_id, _) in enumerate(ordered):
        if node_id != boarding_node_id:
            continue
        for _, _, name in ordered[i + 1:]:
            if any(k in name for k in destination_keywords):
                return True
    return False


class RouteCache:
    def __init__(self, path: Path, max_age_days: int = 7, *, today: date):
        self.path = Path(path)
        self.max_age_days = max_age_days
        self.today = today
        self._entries: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._entries = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                self._entries = {}

    @staticmethod
    def _key(city_code, route_id) -> str:
        return f"{city_code}:{route_id}"

    def _cached(self, key):
        entry = self._entries.get(key)
        if not entry:
            return None, False
        stops = [tuple(s) for s in entry["stops"]]
        try:
            age = (self.today - date.fromisoformat(entry["fetched"])).days
        except (ValueError, KeyError):
            return stops, False
        return stops, age <= self.max_age_days

    def get_stops(self, service_key, city_code, route_id, fetch=fetch_route_stops):
        key = self._key(city_code, route_id)
        cached, fresh = self._cached(key)
        if cached is not None and fresh:
            return cached
        try:
            stops = fetch(service_key, city_code, route_id)
        except (TagoApiError, requests.RequestException, ValueError):
            if cached is not None:
                return cached
            raise
        self._entries[key] = {"fetched": self.today.isoformat(),
                              "stops": [list(s) for s in stops]}
        return [tuple(s) for s in stops]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self._entries, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
