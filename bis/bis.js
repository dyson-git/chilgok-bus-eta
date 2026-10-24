// 칠곡 버스정보시스템(bus.chilgok.go.kr) 기반 앱 (두 번째 갈래, 2026-10-24). 화면은 기존 앱(index.html)과 같다:
// 위 = 시간표(터치로 펴기/접기), 아래 = 동명 가는 버스 / 학명리 가는 버스(앱을 열면 지금 버스, 카드를 터치하면 새로고침).
// 정류장 팝업(중계 /bis?stop=<번호> 가 그대로 전달)을 읽어 "노선당 가장 빠른 버스"를 보여준다.
// 칠곡3·급행9-3 만 대구 버스정보시스템(중계 /dgb?bs=<번호>)에서 같은 방식으로 받는다(칠곡 시스템에 실시간이 없다).
// 규칙(사용자 지시): 시간을 받으면 거기서 초 단위로 줄이고, 못 받아도 (옛 시간 - 지난 시간)으로 계속 줄이고,
// 새 값이 오면 그 값으로 갱신한다. N정류장 전은 항상 보인다.
"use strict";

var HOLD_AFTER_END_MS = 180000;  // 도착 시각이 지나도 새 정보가 없으면 이 시간까지 "곧 도착"으로 남긴다

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
}
function pad2(n) { return (n < 10 ? "0" : "") + n; }
function clockHM(ms) { var d = new Date(ms); return pad2(d.getHours()) + ":" + pad2(d.getMinutes()); }
function clockHMS(ms) { var d = new Date(ms); return clockHM(ms) + ":" + pad2(d.getSeconds()); }
function clean(s) { return String(s).replace(/ /g, " ").replace(/\s+/g, " ").trim(); }
function formatAway(n) { return n === 0 ? "정류장에 있음" : n + "정류장 전"; }

// 도착 시각(ms)까지 남은 시간을 초 단위로. 0 이하면 "곧 도착".
function countdownText(endMs, nowMs) {
  var sec = Math.round((endMs - nowMs) / 1000);
  if (sec <= 0) return "곧 도착";
  if (sec < 60) return sec + "초 뒤";
  if (sec >= 3600) return Math.floor(sec / 3600) + "시간 " + Math.floor((sec % 3600) / 60) + "분 " + pad2(sec % 60) + "초 뒤";
  return Math.floor(sec / 60) + "분 " + pad2(sec % 60) + "초 뒤";
}

// 정류장 팝업 HTML -> [{route_id, route_no, ends, stops_away, minutes, text}] (bis/parse.py 와 같은 규칙)
// 버스가 없으면 stops_away/minutes 는 null. 모르는 문구는 숫자로 바꾸지 않는다("곧 도착"만 0분).
function parsePopup(htmlText) {
  var doc = new DOMParser().parseFromString(htmlText, "text/html");
  return Array.prototype.map.call(doc.querySelectorAll("tr[id]"), function (tr) {
    var no = tr.querySelector("th span"), sub = tr.querySelector("th sub");
    var joined = clean(Array.prototype.map.call(tr.querySelectorAll("td"), function (td) { return td.textContent; }).join(" "));
    var none = joined.indexOf("도착정보가 없습니다") >= 0;
    var away = /(\d+)\s*정거장\s*전/.exec(joined), mins = /(\d+)\s*분\s*후/.exec(joined);
    var minutes = null;
    if (!none && mins) minutes = Number(mins[1]);
    else if (!none && /곧/.test(joined)) minutes = 0;
    return {
      route_id: tr.id.split("_")[0],
      route_no: no ? clean(no.textContent) : "",
      ends: sub ? clean(sub.textContent).replace(/^\(\s*/, "").replace(/\s*\)$/, "") : "",
      stops_away: !none && away ? Number(away[1]) : null,
      minutes: minutes,
      text: none ? "" : joined
    };
  });
}

// 대구 버스정보시스템 도착정보 JSON(중계 /dgb?bs=<번호>) -> parsePopup 과 같은 모양의 줄. 칠곡3·급행9-3 은 대구 시스템 버스라
// 칠곡 버스정보시스템에 실시간이 없어서 이걸로 받는다. route_id 앞에 "dgb:" 를 붙여 칠곡 노선과 섞이지 않게 한다.
// arrState 가 "N분"이면 N분, "곧"이 들어가면 0분, 그 밖(기점출발예정·출발예정 등)은 시간을 만들지 않는다. bsGap 이 음수면 정류장 수 없음.
function parseDaegu(json) {
  var list = json && json.body && Array.isArray(json.body.list) ? json.body.list : [];
  return list.map(function (r) {
    var st = String(r.arrState || ""), m = /(\d+)\s*분/.exec(st), gap = Number(r.bsGap);
    return {
      route_id: "dgb:" + r.routeId,
      route_no: String(r.routeNo || ""),
      ends: String(r.routeNote || ""),
      stops_away: isFinite(gap) && gap >= 0 ? gap : null,
      minutes: m ? Number(m[1]) : (/곧/.test(st) ? 0 : null),
      text: st
    };
  });
}

// cfg.stops[station] = {name, route_ids|null, route_nos?, gaps?, offset_min?}. popups[station] = 파싱한 줄들(못 받았으면 없음).
// 허용된 노선만, 노선당 가장 빠른 한 줄(같은 노선이 여러 정류장에서 나오면 가장 빨리 오는 정류장). 버스가 없는 노선은 줄이 없다.
// gaps 가 있는 정류장(학명리 정류소)은 사용자 방식: 그 정류소 시간에서 offset_min 분을 빼서 동명 기준으로 보여주고,
// 정거장 수는 동명 정류장까지 실제 개수(gaps[노선].stops 를 뺀다)로 바꾼다. 이미 동명을 지난 버스와 정거장 수를 모르는 버스는 뺀다.
function buildRows(cfg, stationIds, popups) {
  var best = {}, order = [];
  stationIds.forEach(function (sid) {
    var st = cfg.stops[sid], list = popups[sid];
    if (!st || !list) return;
    list.forEach(function (r) {
      if (r.minutes === null && r.stops_away === null) return;
      if (st.route_ids && st.route_ids.indexOf(r.route_id) < 0) return;
      if (st.route_nos && st.route_nos.indexOf(r.route_no) < 0) return;
      var row = { route_id: r.route_id, route_no: r.route_no, ends: r.ends, station_id: sid, station_name: st.name,
        stops_away: r.stops_away, minutes: r.minutes };
      var gap = st.gaps ? st.gaps[r.route_id] : null;
      if (gap) {
        // 기준 승차 정류장(gap)을 이미 지났으면 아직 앞에 있는 더 가까운 동명 정류장(alts, 먼 것부터)에서 탄다.
        // 빼는 분은 기준 정류장의 분(사용자 방식 10분)을 정거장 수 비율로 줄인다(예: 8정거장 10분 -> 7정거장 9분).
        var board = r.stops_away === null ? null : r.stops_away >= gap.stops ? gap :
          (gap.alts || []).filter(function (a) { return r.stops_away >= a.stops; })[0];
        if (!board) return;
        var off = board === gap ? st.offset_min : Math.round(st.offset_min * board.stops / gap.stops);
        row.stops_away = r.stops_away - board.stops;
        row.station_name = board.board;
        row.minutes = r.minutes === null ? null : Math.max(0, r.minutes - off);
        row.estimated = true;
        row.offset_min = off;
      }
      var cur = best[r.route_id];
      var better = !cur || (row.minutes !== null && (cur.minutes === null || row.minutes < cur.minutes));
      if (!cur) order.push(r.route_id);
      if (better) best[r.route_id] = row;
    });
  });
  return order.map(function (id) { return best[id]; });
}

// 노선별 도착 시각을 기억해 두고 화면용 줄을 만든다. memo["방향:노선id"] = {end, raw, last, lastAt}.
// - 새 값(분)이 오면 그 값으로 다시 시작, 같은 값이 또 오면 처음 받은 때부터 계속 줄인다(1분 단위 값이라 같은 값이 여러 번 온다).
// - 이번에 못 받은 노선은 도착 시각 + 3분까지 이어서 보여준다(carried). 그 뒤엔 놓는다.
function applyAnchors(rows, memo, dirKey, now) {
  var out = [], seen = {};
  rows.forEach(function (r) {
    var key = dirKey + ":" + r.route_id;
    seen[key] = true;
    var info = { route_id: r.route_id, route_no: r.route_no, ends: r.ends, station_name: r.station_name, stops_away: r.stops_away,
      estimated: !!r.estimated, offset_min: r.offset_min || null };
    if (r.minutes === null) { out.push(Object.assign({ end: null, carried: false, lastAt: now }, info)); return; }
    var raw = r.minutes * 60, m = memo[key];
    var end = m && m.raw === raw ? m.end : now + raw * 1000;
    memo[key] = { end: end, raw: raw, last: info, lastAt: now };
    out.push(Object.assign({ end: end, carried: false, lastAt: now }, info));
  });
  Object.keys(memo).forEach(function (k) {
    if (k.indexOf(dirKey + ":") !== 0 || seen[k]) return;
    var m = memo[k];
    if (now - m.end > HOLD_AFTER_END_MS) { delete memo[k]; return; }
    out.push(Object.assign({ end: m.end, carried: true, lastAt: m.lastAt }, m.last));
  });
  out.sort(function (a, b) { return (a.end === null ? 1e18 : a.end) - (b.end === null ? 1e18 : b.end); });
  return out;
}

// 기기에 저장해 둔 기억(JSON 문자열) -> memo. 앱을 다시 열어도 받은 시간을 이어서 줄이려고 쓴다.
// 깨졌거나 없으면 빈 기억, 도착 시각 + 3분이 지난 것은 버린다(applyAnchors 와 같은 기준).
function loadAnchorMemo(text, now) {
  var out = {}, j;
  try { j = JSON.parse(text); } catch (e) { return out; }
  if (!j || typeof j !== "object") return out;
  Object.keys(j).forEach(function (k) {
    var m = j[k];
    if (m && typeof m.end === "number" && m.last && now - m.end <= HOLD_AFTER_END_MS) out[k] = m;
  });
  return out;
}

// 카드 제목·설명은 기존 앱(app.js CARD_INFO)과 같다
var CARD_INFO = {
  dongmyeong: { title: "동명 가는 버스", sub: "학명리 건너2 정류장에서 타기" },
  hakmyeong: { title: "학명리 가는 버스", sub: "동명 정류장(행정복지센터·우체국·동명교통)에서 타기" }
};

// status = {failed, total}: 이번에 못 받은 정류장 수 / 전체 정류장 수
function renderCard(dir, rows, status, now) {
  var info = CARD_INFO[dir];
  var html = "<h2>" + esc(info.title) + '</h2><p class="sub">' + esc(info.sub) + "</p>";
  if (rows.length) {
    html += rows.map(function (b) {
      var hasEnd = typeof b.end === "number", hasAway = b.stops_away !== null && b.stops_away !== undefined;
      var big = hasEnd ? countdownText(b.end, now) : (hasAway ? formatAway(b.stops_away) : "");
      var attr = hasEnd ? ' role="timer" data-end="' + b.end + '"' : "";
      var where = [hasEnd && hasAway ? formatAway(b.stops_away) : null,
        b.station_name ? b.station_name + "에서 타기" : null,
        b.route_no === "칠곡3" && b.ends ? b.ends : null,
        b.estimated ? "학명리 정류소 시간 −" + b.offset_min + "분" : null,
        b.carried ? clockHM(b.lastAt) + " 기준" : null].filter(Boolean).map(esc).join(" · ");
      return '<div class="bus"><span>' + esc(b.route_no) + '번</span><span class="when"' + attr + ">" + esc(big) + "</span></div>" +
        (where ? '<div class="where">' + where + "</div>" : "");
    }).join("");
    html += '<p class="note">시간은 칠곡군 버스정보시스템(칠곡3·급행9-3은 대구 버스정보시스템)이 분 단위로 알려준 값에서 초 단위로 줄여 보여줘요</p>';
    if (status.failed > 0) html += '<p class="note">일부 정류장 정보가 늦어서 직전 값을 이어 보여줘요</p>';
  } else if (status.failed > 0) {
    html += '<div class="warn">칠곡군 버스정보시스템에서 정보를 못 받았어요. 잠시 후 다시 확인해요</div>';
  } else {
    html += '<div class="none">지금 오는 버스 없음</div>';
  }
  return html;
}

// ---- 위 시간표 (기존 앱 app.js 의 renderSlots/renderTimeBox 와 같은 모양) ----
var TIME_TITLE = { dongmyeong: "동명행", hakmyeong: "학명리행" };

function renderSlots(rows) {
  if (!rows || !rows.length) return '<p class="note">아직 기록이 모이는 중이에요</p>';
  return '<table class="times"><thead><tr><th>버스</th><th>평균</th><th>최소~최대</th></tr></thead><tbody>' +
    rows.map(function (r) {
      return '<tr><td>' + (r.routeno ? esc(r.routeno) + "번" : "-") + '</td><td>' + esc(r.avg_time) + '</td><td>' +
        esc(r.min_time) + "~" + esc(r.max_time) + '<small>' + esc(r.sample_count) + '일 기록</small></td></tr>';
    }).join("") + "</tbody></table>";
}

// 박스를 터치하면 펴고 접는다(접으면 표를 숨긴다).
function renderTimeBox(dir, stats, folded) {
  var rows = stats ? stats[dir] : null;
  return '<section class="card" data-fold="' + dir + '" role="button" tabindex="0" aria-expanded="' + (folded ? "false" : "true") + '"><h2>' +
    esc(TIME_TITLE[dir]) + "</h2>" + (folded ? '<p class="note">눌러서 펼치기</p>' : renderSlots(rows)) + "</section>";
}

window.BisLive = { parsePopup: parsePopup, parseDaegu: parseDaegu, countdownText: countdownText, buildRows: buildRows, applyAnchors: applyAnchors, loadAnchorMemo: loadAnchorMemo,
  renderCard: renderCard, renderTimeBox: renderTimeBox };

// ---- 화면 연결 (bis/index.html 의 <body data-app="bis"> 에서만. 검사 페이지는 건너뛴다) ----
if (!window.BIS_NO_INIT && document.body && document.body.getAttribute("data-app") === "bis") {
  (function () {
    var DIRS = ["dongmyeong", "hakmyeong"];
    var elCard = { dongmyeong: document.getElementById("card-dongmyeong"), hakmyeong: document.getElementById("card-hakmyeong") };
    var elRefresh = document.getElementById("refresh"), elChecked = document.getElementById("checked"), elTimes = document.getElementById("times");
    var state = { cfg: null, memo: readMemo(), rows: { dongmyeong: [], hakmyeong: [] }, status: { dongmyeong: null, hakmyeong: null },
      checkedAt: null, loading: false, okStations: 0, stats: null, fold: readFold() };

    function readFold() {
      try { return JSON.parse(localStorage.getItem("bisTimesFold")) || {}; } catch (e) { return {}; }
    }
    // 받은 도착 시각 기억은 이 기기에 저장한다(앱을 다시 열어도 이어서 줄인다. 못 읽으면 빈 기억)
    function readMemo() {
      try { return loadAnchorMemo(localStorage.getItem("bisEtaMemo"), Date.now()); } catch (e) { return {}; }
    }
    function drawTimes() {
      elTimes.innerHTML = DIRS.map(function (d) { return renderTimeBox(d, state.stats, state.fold[d]); }).join("");
    }
    function draw() {
      var now = Date.now();
      DIRS.forEach(function (d) {
        elCard[d].innerHTML = state.status[d] ? renderCard(d, state.rows[d], state.status[d], now) :
          "<h2>" + esc(CARD_INFO[d].title) + '</h2><p class="sub">' + esc(CARD_INFO[d].sub) + '</p><p class="note">확인 중…</p>';
      });
      elRefresh.disabled = state.loading;
      elRefresh.textContent = state.loading ? "확인 중…" : "새로고침";
      elChecked.textContent = state.checkedAt ? (state.okStations ? "실시간 확인 " : "실시간 연결 안 됨 · ") + clockHMS(state.checkedAt) : "";
    }

    // 칠곡 정류장은 /bis(HTML), 대구 정류장("dgb:<번호>")은 /dgb(JSON). 대구는 지금 오는 버스가 없으면 빈 목록이 정상이다.
    function fetchStop(relay, sid) {
      var ctl = new AbortController(), timer = setTimeout(function () { ctl.abort(); }, 12000);
      var daegu = state.cfg.stops[sid].source === "daegu";
      var url = daegu ? relay + "/dgb?bs=" + encodeURIComponent(sid.slice(4)) : relay + "/bis?stop=" + encodeURIComponent(sid);
      return fetch(url, { cache: "no-store", signal: ctl.signal })
        .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return daegu ? r.json() : r.text(); })
        .then(function (t) {
          if (daegu) { if (!t || !t.header || !t.header.success) throw new Error("대구 응답 오류"); return parseDaegu(t); }
          var rows = parsePopup(t); if (!rows.length) throw new Error("빈 응답"); return rows;
        })
        .catch(function () { return null; })
        .then(function (rows) { clearTimeout(timer); return rows; });
    }

    function loadStats() {
      return fetch("../data/stats.json?t=" + Date.now(), { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) { if (j) { state.stats = j; drawTimes(); } })
        .catch(function () { /* 시간표를 못 받으면 이전 것을 그대로 둔다 */ });
    }

    var seq = 0;
    function load() {
      if (!state.cfg || state.loading) return Promise.resolve();
      var my = ++seq, relay = (window.LIVE_CONFIG || {}).relayUrl;
      state.loading = true; draw();
      loadStats();
      var ids = Object.keys(state.cfg.stops);
      return Promise.all(ids.map(function (sid) { return fetchStop(relay, sid); })).then(function (lists) {
        if (my !== seq) return;
        var popups = {}, ok = 0;
        ids.forEach(function (sid, i) { if (lists[i]) { popups[sid] = lists[i]; ok++; } });
        var now = Date.now();
        DIRS.forEach(function (d) {
          var sids = ids.filter(function (sid) { return state.cfg.stops[sid].direction === d; });
          state.rows[d] = applyAnchors(buildRows(state.cfg, sids, popups), state.memo, d, now);
          state.status[d] = { failed: sids.filter(function (sid) { return !popups[sid]; }).length, total: sids.length };
        });
        try { localStorage.setItem("bisEtaMemo", JSON.stringify(state.memo)); } catch (e) { /* 저장 못 해도 동작은 한다 */ }
        state.okStations = ok; state.checkedAt = now; state.loading = false; draw();
      });
    }

    function onKey(fn) {
      return function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(e); } };
    }
    function toggleFold(el) {
      var box = el.closest ? el.closest("[data-fold]") : null;
      if (!box) return;
      var d = box.getAttribute("data-fold");
      state.fold[d] = !state.fold[d];
      try { localStorage.setItem("bisTimesFold", JSON.stringify(state.fold)); } catch (e) { /* 기억 못 해도 동작은 한다 */ }
      drawTimes();
      var again = elTimes.querySelector('[data-fold="' + d + '"]');
      if (again) again.focus();
    }

    elRefresh.addEventListener("click", function () { load(); });
    // 방향 카드를 터치해도 새로고침(확인 중이면 무시). 위 시간표 박스는 터치하면 펴고 접는다.
    DIRS.forEach(function (d) {
      elCard[d].setAttribute("role", "button");
      elCard[d].tabIndex = 0;
      elCard[d].addEventListener("click", function () { load(); });
      elCard[d].addEventListener("keydown", onKey(function () { load(); }));
    });
    elTimes.addEventListener("click", function (e) { toggleFold(e.target); });
    elTimes.addEventListener("keydown", onKey(function (e) { toggleFold(e.target); }));
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
    setInterval(function () { if (!document.hidden) load(); }, 30000);
    // 1초마다 남은 시간 숫자만 갱신한다(카드를 다시 그리지 않는다).
    setInterval(function () {
      if (document.hidden) return;
      var now = Date.now();
      Array.prototype.forEach.call(document.querySelectorAll("[data-end]"), function (el) { el.textContent = countdownText(Number(el.getAttribute("data-end")), now); });
    }, 1000);

    fetch("routes.json", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (cfg) { state.cfg = cfg; return load(); })
      .catch(function () { DIRS.forEach(function (d) { elCard[d].innerHTML = '<div class="warn">설정을 못 읽었어요. 새로고침 해주세요</div>'; }); });
    drawTimes();
    draw();
  })();
}
