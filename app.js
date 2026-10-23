"use strict";
// 카드 순서: 동명 가는 버스 = 키 dongmyeong(학명리 건너2에서 탑승), 학명리 가는 버스 = 키 hakmyeong
var DIRS = ["dongmyeong", "hakmyeong"];
var CARD_INFO = {
  dongmyeong: { title: "동명 가는 버스", sub: "학명리 건너2 정류장에서 타기" },
  hakmyeong: { title: "학명리 가는 버스", sub: "동명 정류장(행정복지센터·우체국·동명교통)에서 타기" }
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function validEta(v) {
  // Number(null) and Number("") are 0, which would wrongly read as "곧 도착".
  if (v === null || v === undefined || (typeof v === "string" && v.trim() === "")) return false;
  if (typeof v !== "number" && typeof v !== "string") return false;
  return isFinite(Number(v));
}

function formatEta(etaMin) {
  if (!validEta(etaMin)) return "알 수 없음";
  var n = Number(etaMin);
  if (n < 1) return "곧 도착";
  return Math.round(n) + "분 뒤";
}

// 도착 시각(ms)까지 남은 시간을 초 단위로. 0 이하면 "곧 도착".
function countdownText(endMs, nowMs) {
  var sec = Math.round((endMs - nowMs) / 1000);
  if (sec <= 0) return "곧 도착";
  if (sec < 60) return sec + "초 뒤";
  return Math.floor(sec / 60) + "분 " + pad2(sec % 60) + "초 뒤";
}

// TAGO 가 알려준 남은 시간(eta_min)을 "도착 시각"(eta_end, ms)으로 바꿔서 화면이 초 단위로 줄여 보여줄 수 있게 한다.
// memo 는 방향+노선+차량번호별 마지막 도착 시각. 다음 갱신에 TAGO 가 시간을 안 주거나 위치와 안 맞아 숨겨져도 같은 차는 마지막으로
// 받은 도착 시각을 이어서 줄여 보여준다(시간이 갑자기 사라지지 않게). 그 시각이 지나면 끊고 위치만 보여준다(곧 도착이라고 하지 않는다).
// ageMs: 중계가 이 정보를 받아 둔 지 얼마나 됐는지(캐시 나이). 그만큼 이미 흐른 시간으로 친다.
function applyCountdown(buses, memo, dirKey, now, ageMs) {
  var seen = {};
  buses.forEach(function (b) {
    var key = b.vehicleno ? dirKey + ":" + b.routeid + ":" + b.vehicleno : null;
    if (key) seen[key] = true;
    if (b.eta_min !== null && b.eta_min !== undefined && validEta(b.eta_min)) {
      b.eta_end = now - ageMs + Math.round(Number(b.eta_min) * 60) * 1000;
      if (key) memo[key] = b.eta_end;
    } else if (key && memo[key] !== undefined) {
      if (memo[key] > now) b.eta_end = memo[key]; else delete memo[key];
    }
  });
  Object.keys(memo).forEach(function (k) {
    if (k.indexOf(dirKey + ":") === 0 && !seen[k]) delete memo[k];
  });
}

// 노선의 절반 넘게 실패한 추적 결과는 "지금 운행 중인 버스 없음"과 구별할 수 없으니 믿지 않는다.
function trackingUsable(res, dirCfg) {
  return !!res && res.errors * 2 <= ((dirCfg && dirCfg.tracked) || []).length;
}

// collector/config.py is_allowed 의 정확한 JS 포트 (순수 함수). dirCfg = LIVE_CONFIG.directions[dir]
function isAllowed(routeid, routeno, dirCfg) {
  if (dirCfg && dirCfg.all_routes) return true;  // 학명리 건너2: 거기서 잡히는 건 전부 동명행
  routeid = String(routeid); routeno = String(routeno);
  if (routeno === "칠곡3") return dirCfg.chilgok3_routeids.indexOf(routeid) !== -1;
  return dirCfg.routenos.indexOf(routeno) !== -1;
}

// TAGO 응답 JSON -> [{routeid, routeno, eta_min}]. 오류 봉투/헤더 오류는 throw.
function parseArrivals(data) {
  if (!data || !data.response) {
    var h = (data && data.OpenAPI_ServiceResponse && data.OpenAPI_ServiceResponse.cmmMsgHeader) || {};
    throw new Error("TAGO error " + (h.returnReasonCode || "?"));
  }
  var hdr = data.response.header;
  if (hdr && hdr.resultCode && hdr.resultCode !== "00") throw new Error("TAGO error " + hdr.resultCode);
  var items = data.response.body && data.response.body.items;
  if (items === "" || items === undefined || items === null) return [];
  var list = items.item;
  if (list === undefined || list === null) return [];
  if (!Array.isArray(list)) list = [list];
  return list.map(function (it) {
    return { routeid: String(it.routeid), routeno: String(it.routeno), eta_min: Number(it.arrtime) / 60, stops: Number(it.arrprevstationcnt) };
  });
}

// 허용 노선만 거르고 routeid별 최소 ETA로 중복 제거, 오름차순 정렬.
function selectArrivals(all, dirCfg) {
  var best = {};
  all.forEach(function (o) {
    if (!isAllowed(o.routeid, o.routeno, dirCfg) || !validEta(o.eta_min)) return;
    var cur = best[o.routeid];
    if (!cur || o.eta_min < cur.eta_min) best[o.routeid] = o;
  });
  return Object.keys(best).map(function (k) { return best[k]; })
    .sort(function (a, b) { return a.eta_min - b.eta_min; });
}

// byKey: { "city:node": {ok:true, list:[...]} | {ok:false} }  ->  { observations, errors } or null(전부 실패)
function buildDirection(dirCfg, byKey) {
  var all = [], errors = 0, total = dirCfg.registrations.length;
  dirCfg.registrations.forEach(function (r) {
    var e = byKey[r.city_code + ":" + r.node_id];
    if (e && e.ok) all = all.concat(e.list); else errors++;
  });
  if (errors >= total) return null;
  return { observations: selectArrivals(all, dirCfg), errors: errors };
}

// ---- 실시간 위치 (2026-10-22) ----
// TAGO "도착 예측"(arrtime)은 버스가 가까워져야(칠곡3 은 약 6정류장/8분 이내) 나온다. 위치 API 는 운행 중인
// 버스를 항상 준다. 그래서 위치로는 "N정류장 전"이라는 관측 사실만 보여주고 시간 예측은 하지 않는다.

// TAGO 위치 응답 JSON -> [{vehicleno, nodenm, nodeord}]. 오류 봉투/헤더 오류는 throw.
function parseBusLocations(data) {
  if (!data || !data.response) throw new Error("TAGO error");
  var hdr = data.response.header;
  if (hdr && hdr.resultCode && hdr.resultCode !== "00") throw new Error("TAGO error " + hdr.resultCode);
  var items = data.response.body && data.response.body.items;
  if (items === "" || items === undefined || items === null) return [];
  var list = items.item;
  if (list === undefined || list === null) return [];
  if (!Array.isArray(list)) list = [list];
  return list.map(function (it) {
    return { vehicleno: String(it.vehicleno), nodenm: String(it.nodenm), nodeord: Number(it.nodeord) };
  }).filter(function (b) { return isFinite(b.nodeord); });
}

// /loc 응답 -> { "city:routeid": {ok:true, list:[...]} | {ok:false} }
function parseLocResponse(resp) {
  var byRoute = {};
  var results = (resp && resp.results) || {};
  Object.keys(results).forEach(function (k) {
    var r = results[k];
    if (!r || !r.ok) { byRoute[k] = { ok: false }; return; }
    try { byRoute[k] = { ok: true, list: parseBusLocations(r.body) }; } catch (e) { byRoute[k] = { ok: false }; }
  });
  return byRoute;
}

var MAX_SHOW = 8, MAX_STOPS_AWAY = 40, ARRIVING_MAX = 12;

// dirCfg.tracked = [{city_code, routeid, routeno, last_ord, boarding:[{node_id, name, ord}]}], byRoute = parseLocResponse 결과,
// byKey = parseAllResponse 결과(TAGO 도착정보, 없으면 null).
// 버스의 현재 nodeord 에서 앞으로 가장 먼저 만나는 승차 정류장까지의 정류장 수. 이미 지나친 정류장은 건너뛴다.
// 종점(last_ord)은 승차 정류장으로 치지 않는다(거기서 운행이 끝난다). 전 노선 실패면 null.
// 시간(eta_min)은 TAGO 가 도착정보로 준 값만 붙인다: 같은 노선·같은 승차 정류장에서 남은 정류장 수(arrprevstationcnt)가
// 위치로 센 값과 같은 항목이 그 버스다. TAGO 가 시간을 안 주는 버스는 eta_min=null(위치만). 시간을 만들어 내지 않는다.
function buildTracking(dirCfg, byRoute, byKey) {
  var out = [], okRoutes = 0, tracked = dirCfg.tracked || [];
  // 도착정보 풀: "도시:정류소" -> [{a, used}] (이 방향의 정류소만)
  var pool = {};
  (dirCfg.registrations || []).forEach(function (r) {
    var k = r.city_code + ":" + r.node_id, e = byKey && byKey[k];
    if (e && e.ok) pool[k] = e.list.map(function (a) { return { a: a, used: false }; });
  });
  // 같은 노선, 남은 정류장 수가 slack 이내인 아직 안 쓴 도착 항목 중 가장 가까운 것을 "이 위치 버스의 도착정보"로 가져온다.
  // 위치(/loc)와 도착정보(/all)는 몇 초 간격으로 따로 받아서 버스가 한 정류장 움직이는 사이에 1정류장 어긋날 수 있다(slack 1).
  function take(key, routeid, stops, slack) {
    var arr = pool[key] || [], best = null;
    for (var i = 0; i < arr.length; i++) {
      var it = arr[i], d = Math.abs(it.a.stops - stops);
      if (!it.used && it.a.routeid === routeid && validEta(it.a.eta_min) && d <= slack && (best === null || d < Math.abs(best.a.stops - stops))) best = it;
    }
    if (best) best.used = true;
    return best && best.a;
  }
  var cands = [], validated = {};
  tracked.forEach(function (t) {
    var e = byRoute[t.city_code + ":" + t.routeid];
    if (!e || !e.ok) return;
    okRoutes++;
    validated[t.routeid] = true;
    var stops = t.boarding.filter(function (b) { return b.ord !== t.last_ord; });
    e.list.forEach(function (bus) {
      var next = null;
      stops.forEach(function (b) { if (b.ord >= bus.nodeord && (!next || b.ord < next.ord)) next = b; });
      if (!next) return;
      cands.push({ t: t, bus: bus, stops: stops, next: next, away: next.ord - bus.nodeord, eta: null });
    });
  });
  cands.sort(function (x, y) { return x.away - y.away; });
  // 먼저 정류장 수까지 정확히 맞는 것끼리, 그다음 1정류장 어긋난 것끼리 짝짓는다. 2대가 동시에 와도(885) 각자 자기 항목을 가져간다.
  [0, 1].forEach(function (slack) {
    cands.forEach(function (c) {
      if (slack && c.eta !== null) return;
      // 이 버스가 앞으로 지나갈 모든 승차 정류장의 도착 항목을 소비한다(같은 버스가 정류장마다 따로 나오므로 별도 행으로 새지 않게)
      c.stops.forEach(function (b) {
        if (b.ord < c.bus.nodeord || (slack && c.eta !== null)) return;
        var a = take(c.t.city_code + ":" + b.node_id, c.t.routeid, b.ord - c.bus.nodeord, slack);
        if (a && b === c.next) c.eta = Number(a.eta_min);
      });
    });
  });
  cands.forEach(function (c) {
    // 멀고 시간도 없는 버스(차고지 대기 등)만 잡음으로 보고 숨긴다. 시간이 있으면 1시간 넘게 멀어도 보여준다.
    if (c.away > MAX_STOPS_AWAY && c.eta === null) return;
    out.push({ routeno: c.t.routeno, routeid: c.t.routeid, vehicleno: c.bus.vehicleno, nodenm: c.bus.nodenm, stops_away: c.away, stop_name: c.next.name, eta_min: c.eta });
  });
  if (!okRoutes) return null;
  // 위치를 확인할 수 없는 노선의 도착 항목은 버리지 않는다(TAGO 가 시간을 줬다). 같은 정류장의 항목은 항상 별개 버스다
  // (885 는 구미에서 와서 2대가 같이 오기도 한다). 이웃 정류장마다 나온 같은 버스만 접는다(다른 정류장, 1~3정류장 뒤, 0~2.5분 뒤).
  var left = [];
  Object.keys(pool).forEach(function (k) {
    pool[k].forEach(function (it) {
      // 위치로 확인되는 노선(validated)에서 위치와 안 맞는 도착 항목은 이미 지나간 버스의 낡은 기록이라 버린다(TAGO 는 지나간 뒤에도
      // 몇 분간 같은 시간을 계속 내보낸다). 위치를 못 받은 노선·위치 추적이 안 되는 노선(885-1)만 도착정보 그대로 보여준다.
      if (!it.used && !validated[it.a.routeid] && validEta(it.a.eta_min) && isAllowed(it.a.routeid, it.a.routeno, dirCfg)) left.push({ key: k, a: it.a });
    });
  });
  function stopsOf(x) { return isFinite(x.a.stops) ? x.a.stops : 1e9; }
  left.sort(function (x, y) { return stopsOf(x) - stopsOf(y); });
  var kept = [];
  left.forEach(function (x) {
    var dup = kept.some(function (y) {
      var ds = x.a.stops - y.a.stops, de = x.a.eta_min - y.a.eta_min;
      return y.a.routeid === x.a.routeid && y.key !== x.key && ds >= 1 && ds <= 3 && de >= 0 && de <= 2.5;
    });
    if (!dup) kept.push(x);
  });
  kept.forEach(function (x) {
    out.push({ routeno: x.a.routeno, routeid: x.a.routeid, vehicleno: null, nodenm: null, stops_away: isFinite(x.a.stops) ? x.a.stops : null, stop_name: "", eta_min: Number(x.a.eta_min) });
  });
  out.sort(function (x, y) {
    return (x.stops_away === null ? 1e9 : x.stops_away) - (y.stops_away === null ? 1e9 : y.stops_away);
  });
  // 종점에서 되돌아가는 왕복 노선(885): 종점에 다가오는 버스는 곧 이 방향 버스가 된다. 시간은 만들지 않고 위치만 보여준다.
  var arriving = [];
  (dirCfg.arriving || []).forEach(function (a) {
    var e = byRoute[a.city_code + ":" + a.routeid];
    if (!e || !e.ok) return;
    e.list.forEach(function (bus) {
      var away = a.last_ord - bus.nodeord;
      if (away < 0 || away > ARRIVING_MAX) return;
      arriving.push({ routeno: a.routeno, routeid: a.routeid, vehicleno: bus.vehicleno, nodenm: bus.nodenm, stops_away: away,
        stop_name: "", eta_min: null, arriving: true, terminal: a.terminal });
    });
  });
  arriving.sort(function (x, y) { return x.stops_away - y.stops_away; });
  return { buses: out.slice(0, MAX_SHOW).concat(arriving), errors: tracked.length - okRoutes };
}

function formatAway(n) { return n === 0 ? "정류장에 있음" : n + "정류장 전"; }

function renderTracking(dir, res) {
  var info = CARD_INFO[dir];
  var html = "<h2>" + esc(info.title) + '</h2><p class="sub">' + esc(info.sub) + "</p>";
  if (res.buses.length) {
    html += res.buses.map(function (b) {
      if (b.arriving) {
        var tn = b.terminal || "종점";
        return '<div class="bus"><span>' + esc(b.routeno) + '번</span><span class="when">' +
          esc(b.stops_away === 0 ? tn + " 도착" : tn + " " + b.stops_away + "정류장 전") + "</span></div>" +
          '<div class="where">' + ["구미에서 오는 버스", b.nodenm ? "지금 " + b.nodenm : null, "도착하면 학명리 방향으로 가요"].filter(Boolean).map(esc).join(" · ") + "</div>";
      }
      var hasEnd = typeof b.eta_end === "number";
      var hasEta = hasEnd || (b.eta_min !== null && b.eta_min !== undefined && validEta(b.eta_min));
      var hasAway = b.stops_away !== null && b.stops_away !== undefined;
      var big = hasEnd ? countdownText(b.eta_end, Date.now()) : (hasEta ? formatEta(b.eta_min) : (hasAway ? formatAway(b.stops_away) : ""));
      // 매초 바뀌는 숫자라 role=timer(화면 낭독이 매초 읽지 않는다). data-end 는 1초마다 갱신하는 타이머가 쓴다.
      var whenAttr = hasEnd ? ' role="timer" data-end="' + b.eta_end + '"' : "";
      var where = [b.nodenm ? "지금 " + b.nodenm : null, hasEta && hasAway ? formatAway(b.stops_away) : null,
        b.stop_name ? b.stop_name + "에서 타기" : null].filter(Boolean).map(esc).join(" · ");
      return '<div class="bus"><span>' + esc(b.routeno) + '번</span><span class="when"' + whenAttr + ">" + esc(big) + "</span></div>" +
        (where ? '<div class="where">' + where + "</div>" : "");
    }).join("");
    html += '<p class="note">시간은 국토부(TAGO)가 알려준 값에서 초 단위로 줄여 보여줘요. 시간이 없는 버스는 지금 위치만 보여요</p>';
  } else if (res.errors === 0) {
    html += '<div class="none">지금 운행 중인 버스 없음</div>';
  }
  if (res.errors > 0) html += '<p class="note">일부 노선 정보가 늦어요</p>';
  if (res.snapshotAt) html += '<p class="note">지금은 연결이 늦어 ' + esc(res.snapshotAt) + ' 정보를 보여드려요</p>';
  return html;
}

// /all 응답 -> byKey
function parseAllResponse(resp) {
  var byKey = {};
  var results = (resp && resp.results) || {};
  Object.keys(results).forEach(function (k) {
    var r = results[k];
    if (!r || !r.ok) { byKey[k] = { ok: false }; return; }
    try { byKey[k] = { ok: true, list: parseArrivals(r.body) }; } catch (e) { byKey[k] = { ok: false }; }
  });
  return byKey;
}

function pad2(n) { return (n < 10 ? "0" : "") + n; }
function clockHMS(ms) {
  var d = new Date(ms);
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
}
function clockHM(ms) {
  var d = new Date(ms);
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}

// res = { observations, errors, snapshotAt? } | null
function renderCard(dir, res) {
  if (res && res.buses) return renderTracking(dir, res);
  var info = CARD_INFO[dir];
  var html = "<h2>" + esc(info.title) + '</h2><p class="sub">' + esc(info.sub) + "</p>";
  if (!res) return html + '<p class="note">확인 중…</p>';
  if (res.snapshotAt) html += '<p class="note">지금은 실시간 정보를 못 받아 ' + esc(res.snapshotAt) + ' 기록을 보여드려요</p>';
  var hasErr = res.errors > 0;
  if (hasErr && !res.observations.length) html += '<div class="warn">버스 정보를 다 받지 못했어요. 잠시 후 다시 확인해요</div>';
  if (res.observations.length) {
    html += res.observations.map(function (o) {
      return '<div class="bus"><span>' + esc(o.routeno) + '번</span><span class="when">' + esc(formatEta(o.eta_min)) + "</span></div>";
    }).join("");
    if (hasErr) html += '<p class="note">일부 정류장 정보가 늦어요</p>';
  } else if (!hasErr) {
    html += '<div class="none">지금 오는 버스 없음</div>';
  }
  return html;
}

var TIME_TITLE = { dongmyeong: "동명행", hakmyeong: "학명리행" };

function renderSlots(rows) {
  if (!rows || !rows.length) return '<p class="note">아직 기록이 모이는 중이에요</p>';
  // 버스 번호 | 평균 시각 | 최소~최대 시각 (한 표). 노선별 집계(collector/stats.py)라 행마다 번호가 있다.
  // 예전 stats.json(번호 없음)이 남아 있어도 깨지지 않게 "-" 로 표시한다.
  return '<table class="times"><thead><tr><th>버스</th><th>평균</th><th>최소~최대</th></tr></thead><tbody>' +
    rows.map(function (r) {
      return '<tr><td>' + (r.routeno ? esc(r.routeno) + "번" : "-") + '</td><td>' + esc(r.avg_time) + '</td><td>' +
        esc(r.min_time) + "~" + esc(r.max_time) + '<small>' + esc(r.sample_count) + '일 기록</small></td></tr>';
    }).join("") + "</tbody></table>";
}

// 시간표는 방향별 박스로 항상 보여준다(동명행 / 학명리행).
function renderTimeBox(dir, stats) {
  var rows = stats ? stats[dir] : null;
  return '<section class="card"><h2>' + esc(TIME_TITLE[dir]) + "</h2>" + renderSlots(rows) + "</section>";
}

// 기점·종점 기준 참고 시간표. 변환·보정 없이 원본 시각 그대로 표시한다.
function renderReference(tt) {
  if (!tt || !Array.isArray(tt.routes) || !tt.routes.length) return "";
  var html = "";
  if (tt.note) html += '<div class="notice stale">' + esc(tt.note) + '</div>';
  html += tt.routes.map(function (r) {
    var trips = (r.trips || []).map(function (t) {
      var v = t.variant ? ' (' + esc(t.variant) + ')' : '';
      if (t.arrive) return '<div class="trip">' + esc(t.from) + ' <b>' + esc(t.depart) + '</b> → ' + esc(t.to) + ' ' + esc(t.arrive) + v + '</div>';
      return '<div class="trip">' + esc(t.from) + ' <b>' + esc(t.depart) + '</b> 출발 → ' + esc(t.to) + v + '</div>';
    }).join("");
    var stops = (r.stop_times || []).map(function (s) {
      return '<div class="trip">' + esc(s.stop) + ' (' + esc(s.direction) + ') 통과: ' + (s.times || []).map(esc).join(", ") + '</div>';
    }).join("");
    return '<div class="rt"><div><b>' + esc(r.routeno) + '번</b> <span class="muted">' + esc(r.path) + '</span>' + (r.source ? '<br><small class="muted">' + esc(r.source) + '</small>' : '') + '</div>' + trips + stops + '</div>';
  }).join("");
  if (Array.isArray(tt.missing) && tt.missing.length) {
    html += '<p class="muted">시간표 없음: ' + tt.missing.map(esc).join(", ") + '</p>';
  }
  if (tt.source) html += '<p class="muted">' + esc(tt.source) + '</p>';
  return html;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { isAllowed: isAllowed, parseArrivals: parseArrivals, selectArrivals: selectArrivals, buildDirection: buildDirection, parseAllResponse: parseAllResponse, renderCard: renderCard, renderSlots: renderSlots, renderTimeBox: renderTimeBox, validEta: validEta, formatEta: formatEta, countdownText: countdownText, applyCountdown: applyCountdown, trackingUsable: trackingUsable, renderReference: renderReference, parseBusLocations: parseBusLocations, parseLocResponse: parseLocResponse, buildTracking: buildTracking, formatAway: formatAway };
}

if (typeof document !== "undefined") {
  (function () {
    var state = { stats: null, latest: null, res: { dongmyeong: null, hakmyeong: null },
      checkedAt: null, loading: false, refOpen: false, etaEnd: {}, good: {} };
    var MAX_INFLIGHT = 3, MAX_ATTEMPTS = 3;
    var elRefresh = document.getElementById("refresh");
    var elChecked = document.getElementById("checked");
    var elTimes = document.getElementById("times");

    function drawCards() {
      DIRS.forEach(function (d) {
        document.getElementById("card-" + d).innerHTML = renderCard(d, state.res[d]);
      });
      elRefresh.disabled = state.loading;
      elRefresh.textContent = state.loading ? "확인 중…" : "새로고침";
      elChecked.textContent = state.checkedAt ? (state.live ? "실시간 확인 " : "실시간 연결 안 됨 · ") + clockHMS(state.checkedAt) : "";
    }
    function drawTimes() {
      elTimes.innerHTML = DIRS.map(function (d) { return renderTimeBox(d, state.stats); }).join("");
    }

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
    function getJson(url) {
      var bust = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
      return fetch(bust, { cache: "no-store" }).then(function (r) {
        if (r.status === 404) return { missing: true };
        if (!r.ok) return { failed: true };
        return r.json().then(function (data) { return { data: data }; });
      }).catch(function () { return { failed: true }; });
    }
    function retrying(fn, maxAttempts) {
      function attempt(n) {
        return fn().catch(function (e) {
          if (n >= maxAttempts) throw e;
          return sleep(n * 1000).then(function () { return attempt(n + 1); });
        });
      }
      return attempt(1);
    }

    function cfg() {
      var c = window.LIVE_CONFIG;
      return c && c.relayUrl && c.directions ? c : null;
    }

    // 1순위: 중계 /all 한 번으로 전부 (재시도는 중계가 한다). 12초 안에 못 받으면 null.
    function fetchAll(c, fresh, meta) {
      var ctl = new AbortController();
      var timer = setTimeout(function () { ctl.abort(); }, 15000); // 중계 최악 ~12.5초(9초 예산 + 진행 중 1회 3.5초)보다 길게
      return fetch(c.relayUrl + "/all" + (fresh ? "?fresh=1" : ""), { cache: "no-store", signal: ctl.signal }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (j) {
        if (!j || !j.results) throw new Error("bad /all");
        if (meta) meta.arrAt = j.fetched_at;  // 중계가 TAGO 에서 받은 시각 - 카운트다운 기준(캐시 나이 보정)
        return parseAllResponse(j);
      }).catch(function () { return null; }).then(function (m) { clearTimeout(timer); return m; });
    }

    // 0순위: 중계 /loc — 운행 중인 버스의 현재 위치. 중계에 /loc 가 없거나 전부 실패하면 null(기존 /all 로 대체).
    function fetchLoc(c, fresh) {
      var ctl = new AbortController();
      var timer = setTimeout(function () { ctl.abort(); }, 15000);
      return fetch(c.relayUrl + "/loc" + (fresh ? "?fresh=1" : ""), { cache: "no-store", signal: ctl.signal }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (j) {
        if (!j || !j.results) throw new Error("bad /loc");
        var m = parseLocResponse(j);
        var anyOk = Object.keys(m).some(function (k) { return m[k].ok; });
        return anyOk ? m : null;
      }).catch(function () { return null; }).then(function (m) { clearTimeout(timer); return m; });
    }

    // 2순위: 정류소별 /arrivals (동시 3개)
    function fetchEach(c) {
      var seen = {}, regs = [];
      DIRS.forEach(function (d) {
        ((c.directions[d] || {}).registrations || []).forEach(function (r) {
          var k = r.city_code + ":" + r.node_id;
          if (!seen[k]) { seen[k] = 1; regs.push(r); }
        });
      });
      var byKey = {}, next = 0;
      function worker() {
        if (next >= regs.length) return Promise.resolve();
        var reg = regs[next++], k = reg.city_code + ":" + reg.node_id;
        var url = c.relayUrl + "/arrivals?city=" + encodeURIComponent(reg.city_code) + "&node=" + encodeURIComponent(reg.node_id);
        return retrying(function () {
          return fetch(url, { cache: "no-store" }).then(function (r) { return r.json(); }).then(parseArrivals);
        }, MAX_ATTEMPTS).then(function (list) { byKey[k] = { ok: true, list: list }; })
          .catch(function () { byKey[k] = { ok: false }; })
          .then(worker);
      }
      var ws = [];
      for (var i = 0; i < Math.min(MAX_INFLIGHT, regs.length); i++) ws.push(worker());
      return Promise.all(ws).then(function () { return byKey; });
    }

    function snapshot(dir) {
      var e = state.latest && state.latest[dir];
      if (!e) return null;
      var t = Date.parse(e.polled_at);
      var obs = (e.observations || []).filter(function (o) { return validEta(o.eta_min); })
        .sort(function (a, b) { return Number(a.eta_min) - Number(b.eta_min); });
      return { observations: obs, errors: (e.errors && e.errors.length) || 0, snapshotAt: isNaN(t) ? "이전" : clockHM(t) };
    }

    var seq = 0;
    function load(fresh) {
      var my = ++seq;
      state.loading = true;
      drawCards();
      var c = cfg();
      var got = { loc: null, arr: null, arrAt: null };
      // 위치(/loc)와 도착정보(/all)는 먼저 오는 것부터 그린다(전부 기다리면 느리다). 이전에 받은 시간은 계속 줄고 있어서
      // 갱신하는 동안에도 사라지지 않는다. /loc 가 안 되면 도착정보만, 둘 다 안 되면 정류소별 /arrivals, 그래도 안 되면 저장된 기록.
      function paint(final) {
        if (my !== seq) return;
        var now = Date.now(), t = Date.parse(got.arrAt), age = isNaN(t) ? 0 : now - t;
        if (age < 0 || age > 90000) age = 0;  // 기기 시계가 어긋났거나 너무 오래된 값은 믿지 않는다
        DIRS.forEach(function (d) {
          var dc = c && c.directions[d];
          var tracked = got.loc && dc ? buildTracking(dc, got.loc, got.arr) : null;
          if (!trackingUsable(tracked, dc)) tracked = null;
          var live = got.arr && dc ? buildDirection(dc, got.arr) : null;
          var r = tracked || live;
          if (r) {
            applyCountdown(r.buses || [], state.etaEnd, d, now, age);
            state.good[d] = { res: r, at: now };
          } else if (final) {
            // 이번에 못 받았으면 5분 안에 받아 둔 실시간 결과를 계속 보여준다(시간도 계속 줄어든다). 그보다 오래됐으면 저장된 기록.
            var g = state.good[d];
            r = g && now - g.at < 300000 ? Object.assign({}, g.res, { snapshotAt: clockHMS(g.at) }) : (snapshot(d) || { observations: [], errors: 1 });
          } else {
            return;
          }
          state.res[d] = r;
        });
        state.checkedAt = now;
        state.live = !!(got.loc || got.arr);
        drawCards();
      }
      var pLoc = c ? fetchLoc(c, fresh).then(function (m) { got.loc = m; if (m) paint(false); }) : Promise.resolve();
      var pArr = c ? fetchAll(c, fresh, got).then(function (m) { got.arr = m; if (m) paint(false); }) : Promise.resolve();
      var pStats = getJson("data/stats.json").then(function (r) {
        if (my === seq && !r.failed) { state.stats = r.missing ? null : r.data; drawTimes(); }
      });
      var pLatest = getJson("data/latest.json").then(function (r) { if (!r.failed) state.latest = r.missing ? null : r.data; });
      return Promise.all([pLoc, pArr, pStats, pLatest]).then(function () {
        if (my !== seq) return;
        if (c && !got.loc && !got.arr) return fetchEach(c).then(function (m) { got.arr = m; });
      }).then(function () {
        if (my !== seq) return;
        state.loading = false;
        paint(true);
      });
    }

    // 버튼은 중계 캐시를 건너뛰고 지금 바로 다시 받는다. 자동 새로고침(30초)은 캐시를 써도 된다.
    elRefresh.addEventListener("click", function () { load(true); });
    document.getElementById("refbtn").addEventListener("click", function () {
      state.refOpen = !state.refOpen;
      document.getElementById("refbody").hidden = !state.refOpen;
      this.setAttribute("aria-expanded", String(state.refOpen));
    });
    // 참고 시간표는 정적 데이터라 한 번만 불러온다. 없거나 실패하면 숨긴 채 둔다.
    getJson("timetable.json").then(function (res) {
      var html = res.data ? renderReference(res.data) : "";
      if (!html) return;
      document.getElementById("refbody").innerHTML = html;
      document.getElementById("reference").hidden = false;
    });

    // 30초마다 자동 새로고침 (화면이 보일 때만). 돌아오면 즉시 새로고침. 이전 결과는 계속 보인다.
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
    setInterval(function () { if (!document.hidden) load(); }, 30000);
    // 1초마다 남은 시간 숫자만 갱신한다(카드를 다시 그리지 않는다).
    setInterval(function () {
      if (document.hidden) return;
      var now = Date.now();
      Array.prototype.forEach.call(document.querySelectorAll("[data-end]"), function (el) {
        el.textContent = countdownText(Number(el.getAttribute("data-end")), now);
      });
    }, 1000);
    drawTimes();
    load();
  })();
}
