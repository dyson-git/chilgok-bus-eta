
# 같은 물리적 정류소라도 버스 운행 회사가 등록된 시/군(cityCode)에 따라 TAGO의
# nodeId가 따로 등록돼 있다 (실측 확인: 구미시 885번 버스가 이 물리적 위치에 실제
# GPS로 잡히지만, 칠곡군(37390) cityCode로는 전혀 보이지 않고 구미시(37050)
# cityCode + 구미 쪽 nodeId로만 보인다). 그래서 방향마다 nodeId 하나가 아니라
# "이 물리적 정류소를 등록해놓은 시/군들의 (city_code, node_id) 목록"을 전부 갖고
# 전부 조회해서 합쳐야 한다.

DIRECTIONS = {
    # 동명면행정복지센터 정류소("건너" 아닌 쪽)에서 수집 = 학명리 쪽으로 가는 버스
    "hakmyeong": {
        "label": "학명리방향",
        "registrations": [
            {"city_code": "37390", "node_id": "CGB2142"},  # 칠곡군
            {"city_code": "37050", "node_id": "GMB2142"},  # 구미시
            {"city_code": "22", "node_id": "DGB7181001000"},  # 대구광역시
        ],
    },
    # 학명리 정류소 중 "학명리 건너2"에서 수집 = 동명면 쪽으로 가는 버스
    "dongmyeong": {
        "label": "동명방향",
        "registrations": [
            {"city_code": "37390", "node_id": "CGB2479"},  # 칠곡군
            {"city_code": "37050", "node_id": "GMB2479"},  # 구미시
            {"city_code": "37100", "node_id": "GYB369001900"},  # 경산시
        ],
    },
}
