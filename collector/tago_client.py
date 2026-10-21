import requests
from collector.models import ArrivalObservation


def get_arrivals(service_key: str, city_code: str, node_id: str) -> list[ArrivalObservation]:
    """
    Fetch bus arrival information from TAGO ArvlInfoInqireService.

    Args:
        service_key: TAGO API service key
        city_code: City code (e.g., "37050" for Chilgok)
        node_id: Bus stop node ID (e.g., "DGB7021234")

    Returns:
        List of ArrivalObservation objects
    """
    url = "http://api.tago.go.kr/openapi/v2/arrival"
    params = {
        "serviceKey": service_key,
        "cityCode": city_code,
        "nodeId": node_id,
        "_type": "json"
    }

    response = requests.get(url, params=params)
    data = response.json()

    items = data["response"]["body"]["items"]

    # Handle empty string response (public data API quirk for no buses)
    if items == "":
        return []

    # Normalize single dict to list
    item_list = items["item"]
    if isinstance(item_list, dict):
        item_list = [item_list]

    # Convert items to ArrivalObservation objects
    arrivals = []
    for item in item_list:
        arrtime_seconds = int(item["arrtime"])
        eta_min = arrtime_seconds / 60
        observation = ArrivalObservation(
            routeid=item["routeid"],
            routeno=item["routeno"],
            eta_min=eta_min
        )
        arrivals.append(observation)

    return arrivals
