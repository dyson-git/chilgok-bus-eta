import requests
from collector.models import ArrivalObservation


class TagoApiError(Exception):
    """Raised when TAGO API returns an error response."""
    pass


def get_arrivals(service_key: str, city_code: str, node_id: str) -> list[ArrivalObservation]:
    """
    Fetch bus arrival information from TAGO ArvlInfoInqireService.

    Args:
        service_key: TAGO API service key (decoded format with literal +, /, = characters)
        city_code: City code (e.g., "37050" for Chilgok)
        node_id: Bus stop node ID (e.g., "DGB7021234")

    Returns:
        List of ArrivalObservation objects

    Raises:
        TagoApiError: If the API returns an error response
    """
    url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList"
    params = {
        "serviceKey": service_key,
        "cityCode": city_code,
        "nodeId": node_id,
        "_type": "json"
    }

    response = requests.get(url, params=params, timeout=15)
    data = response.json()

    # Check for error response envelope (no "response" key)
    if "response" not in data:
        err_msg = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {}).get("errMsg", "Unknown error")
        reason_code = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {}).get("returnReasonCode", "Unknown")
        raise TagoApiError(f"TAGO API error: {err_msg} (code: {reason_code})")

    # Check for error in response header
    response_obj = data["response"]
    if "header" in response_obj:
        result_code = response_obj["header"].get("resultCode")
        if result_code and result_code != "00":
            err_msg = response_obj["header"].get("resultMessage", "Unknown error")
            raise TagoApiError(f"TAGO API error: {err_msg} (code: {result_code})")

    items = response_obj["body"]["items"]

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
