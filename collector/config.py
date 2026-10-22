
# TAGO 정류소 등록의 두 가지 함정 (둘 다 실측으로 확인됨):
#
# 1) 같은 물리적 정류소라도 버스 운행 회사가 등록된 시/군(cityCode)마다 nodeId가
#    따로 있다. 구미시 885번 버스가 이 지역에 실제 GPS로 잡히는데, 칠곡군(37390)
#    cityCode로는 전혀 안 보이고 구미시(37050) nodeId로만 보였다.
# 2) 같은 방향이라도 노선/회사마다 기·종점으로 쓰는 물리적 정류소가 다르다.
#    칠곡군 노선(36, 36-1, 칠곡3 등)은 "동명교통"(차고지)에서 출발/종료하고,
#    구미 885번 역방향은 "동명면우체국"에서 출발한다. 행정복지센터만 보면 놓친다.
#
# 그래서 방향마다 "이 방향 버스를 잡을 수 있는 모든 (city_code, node_id) 조합"을
# 전부 조회해서 합친다. 조합은 좌표 기준 근접정류소 조회(getCrdntPrxmtSttnList)로
# 찾았다 — 이 API는 cityCode와 무관하게 그 좌표의 모든 시/군 등록을 돌려주므로,
# 나중에 다른 시/군이 추가로 등장해도 같은 방법으로 찾을 수 있다.

DIRECTIONS = {
    # 동명면 쪽에서 학명리/학명동 쪽으로 가는 버스
    "hakmyeong": {
        "label": "학명리방향",
        "registrations": [
            # 동명면행정복지센터
            {"city_code": "37390", "node_id": "CGB2142"},
            {"city_code": "37050", "node_id": "GMB2142"},
            {"city_code": "22", "node_id": "DGB7181001000"},
            # 동명면우체국 (구미 885 역방향 기점)
            {"city_code": "37390", "node_id": "CGB2141"},
            {"city_code": "37050", "node_id": "GMB2141"},
            {"city_code": "22", "node_id": "DGB3690003750"},
            # 동명교통 차고지 (칠곡군 노선 36/36-1/칠곡3 기·종점)
            {"city_code": "37390", "node_id": "CGB4870"},
            {"city_code": "37390", "node_id": "CGB4871"},
            {"city_code": "37050", "node_id": "GMB4871"},
            {"city_code": "37100", "node_id": "GYB369007000"},
            {"city_code": "22", "node_id": "DGB7181007000"},
            {"city_code": "22", "node_id": "DGB3690005830"},
        ],
    },
    # 학명리 쪽에서 동명면 쪽으로 가는 버스 ("학명리 건너2" 정류소)
    "dongmyeong": {
        "label": "동명방향",
        "registrations": [
            {"city_code": "37390", "node_id": "CGB2479"},
            {"city_code": "37050", "node_id": "GMB2479"},
            {"city_code": "37100", "node_id": "GYB369001900"},
        ],
    },
}


# 칠곡 BIS "학명리 건너2" 정류장 노선 목록(사용자 제공, 2026-10-21) + 칠곡3 경로 확인(사용자, 2026-10-22)
ALLOWED_ROUTENOS = {"885", "300", "34", "34-1", "36", "36-1", "9-3", "급행9-3"}
# 칠곡3은 경로별로 노선ID가 다르고, 경운대/예술대/하판 경유만 학명리를 지난다 (기성 경유, 동명-칠곡시장-동명은 안 감)
ALLOWED_CHILGOK3_ROUTEIDS = {
    "DGB4090003001",  # 칠곡3[동명-칠곡시장-동명-예술대-경운대-동명]
    "DGB4090003011",  # 칠곡3[동명-칠곡시장-동명-경운대-동명]
    "DGB4090003014",  # 칠곡3[동명-칠곡시장-동명-경운대-예술대-동명]
    "DGB4090003015",  # 칠곡3[동명-칠곡시장-동명-하판]
}


# 칠곡 BIS 학명리 건너2 노선 목록 + 사용자 확인 2026-10-22 (동명방향 승차 정류소에만 해당, 학명리방향은 아님)
EXTRA_ALLOWED = {
    "dongmyeong": {
        "routenos": {"885-1"},
        "chilgok3_routeids": {"DGB4090003023"},  # 칠곡3[하판-동명-기성-동명]
    },
}


def is_allowed(routeid: str, routeno: str, direction: str | None = None) -> bool:
    extra = EXTRA_ALLOWED.get(direction, {})
    if routeno == "칠곡3":
        return routeid in ALLOWED_CHILGOK3_ROUTEIDS | extra.get("chilgok3_routeids", set())
    return routeno in ALLOWED_ROUTENOS | extra.get("routenos", set())
