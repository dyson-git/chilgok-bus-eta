"""칠곡 버스정보시스템(bus.chilgok.go.kr) 응답 파서. 순수 함수만 둔다(네트워크 없음).

정류장 팝업(POST /map/AjaxRouteListByStop.do, station_id=<번호>)은 그 정류장을 지나는 노선마다 한 줄을 준다:
  <tr id="52710_52710"> <th> <span>527</span> <p>다사_동명 <sub>( 연화리2↔ 동명교통)</sub></p> </th>
    <td><b>7</b> 정거장전</td> <td><b>10</b>분후 도착예정</td> </tr>
버스가 없으면 두 칸 모두 "도착정보가 없습니다." 이 시스템은 노선당 가장 가까운 한 대만 준다."""
import html as _html
import re


def _text(fragment):
    s = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", _html.unescape(s).replace("\xa0", " ")).strip()


def parse_stop_popup(page):
    """정류장 팝업 HTML -> [{route_id, route_no, name, ends, stops_away, minutes, text}].

    stops_away/minutes 는 팝업이 숫자로 준 경우만 채운다. 모르는 문구는 숫자로 바꾸지 않고 text 에만 남긴다(시간을 만들지 않는다)."""
    rows = []
    for m in re.finditer(r"<tr[^>]*\bid=[\"']([^\"']+)[\"'][^>]*>(.*?)</tr>", page, re.S):
        row_id, body = m.group(1), m.group(2)
        th = re.search(r"<th[^>]*>(.*?)</th>", body, re.S)
        if not th:
            continue
        th_html = th.group(1)
        no = re.search(r"<span[^>]*>(.*?)</span>", th_html, re.S)
        sub = re.search(r"<sub[^>]*>(.*?)</sub>", th_html, re.S)
        p = re.search(r"<p[^>]*>(.*?)</p>", th_html[no.end():] if no else th_html, re.S)
        name = _text(re.sub(r"<sub.*?</sub>", " ", p.group(1), flags=re.S)) if p else ""
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
        joined = " ".join(cells)
        away = re.search(r"(\d+)\s*정거장\s*전", joined)
        mins = re.search(r"(\d+)\s*분\s*후", joined)
        rows.append({
            "route_id": row_id.split("_")[0],
            # 노선 정류장 API(StopListByRoute)는 숫자 id 만 받는다: 팝업 id 의 앞 글자(칠곡330 -> 330, 급행310 -> 310)를 뗀다
            "api_id": re.sub(r"^[가-힣]+", "", row_id.split("_")[0]),
            "route_no": _text(no.group(1)) if no else "",
            "name": name,
            "ends": _text(sub.group(1)).strip("() ").strip() if sub else "",
            "stops_away": int(away.group(1)) if away else None,
            "minutes": int(mins.group(1)) if mins else None,
            "text": "" if "도착정보가 없습니다" in joined else joined,
        })
    return rows


def routes_toward(stop_list, boarding_ids, target_substr):
    """노선 정류장 목록(StopListByRoute 의 stopList)에서, boarding_ids 정류장에서 타면 이름에 target_substr 이 들어간
    정류장을 그 뒤에 지나는가. 되돌아오는(순환) 노선은 어느 한 번이라도 타는 쪽이 앞서면 true. 이미 학명리를 지나서
    온 버스(타는 정류장이 뒤)는 false."""
    boarding = [int(s["WAYPOINT_ORD"]) for s in stop_list if str(s["STOP_SERVICEID"]) in boarding_ids]
    targets = [int(s["WAYPOINT_ORD"]) for s in stop_list if target_substr in (s.get("STOP_KNAME") or "")]
    return any(b < t for b in boarding for t in targets)


def stops_between(stop_list, ref_ids, target_id):
    """노선 정류장 목록에서 동명 정류장(ref_ids, 앞쪽이 우선)부터 target_id 정류장까지 정거장 수 -> (수, 동명 정류장 이름).

    target 은 노선에서 처음 지나는 곳을 쓰고, 동명 정류장은 그 바로 앞에 지나는 회차를 쓴다(순환 노선).
    ref_ids 중 노선이 target 앞에서 지나는 첫 정류장을 쓴다. 없거나 target 이 노선에 없으면 None."""
    target = [int(s["WAYPOINT_ORD"]) for s in stop_list if str(s["STOP_SERVICEID"]) == str(target_id)]
    if not target:
        return None
    t = min(target)
    for ref in ref_ids:
        before = [s for s in stop_list if str(s["STOP_SERVICEID"]) == str(ref) and int(s["WAYPOINT_ORD"]) < t]
        if before:
            s = max(before, key=lambda x: int(x["WAYPOINT_ORD"]))
            return t - int(s["WAYPOINT_ORD"]), s.get("STOP_KNAME") or ""
    return None
