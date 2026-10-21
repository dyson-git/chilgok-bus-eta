CITY_CODE = "37390"  # 칠곡군 (TAGO cityCode, confirmed via live API call)

DIRECTIONS = {
    # 동명면행정복지센터 정류소(CGB2142, "건너" 아닌 쪽)에서 수집 = 학명리 쪽으로 가는 버스
    "hakmyeong": {"node_id": "CGB2142", "label": "학명리방향"},
    # 학명리 정류소 중 "학명리 건너2"(CGB2479)에서 수집 = 동명면 쪽으로 가는 버스
    "dongmyeong": {"node_id": "CGB2479", "label": "동명방향"},
}
