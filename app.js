"use strict";
var DIR_LABELS = { hakmyeong: "동명 출발 (학명리행)", dongmyeong: "학명리 출발 (동명행)" };
var STALE_MIN = 15;

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

// ETA 분(실수) -> 표시 문자열. 경과시간 차감 없음.
function validEta(v) {
  // Number(null) and Number("") are 0, which would wrongly read as "곧 도착".
  if (v === null || v === undefined || (typeof v === "string" && v.trim() === "")) return false;
  if (typeof v !== "number" && typeof v !== "string") return false;
  return isFinite(Number(v));
}

function formatEta(etaMin) {
  if (!validEta(etaMin)) return "도착 시간 알 수 없음";
  var n = Number(etaMin);
  if (n < 1) return "곧 도착";
  return "약 " + Math.round(n) + "분 후 도착";
}

function ageMinutes(polledAt, nowMs) {
  var t = Date.parse(polledAt);
  if (isNaN(t)) return null;
  return Math.max(0, Math.floor((nowMs - t) / 60000));
}

function renderStats(rows) {
  if (!rows || !rows.length) return '<p class="muted">통계 준비 중 (데이터 수집 중)</p>';
  return rows.map(function (r) {
    return '<div class="row"><span>' + esc(r.slot_index) + '번째 차 <b>' + esc(r.avg_time) +
      '</b></span><span class="range">' + esc(r.min_time) + '~' + esc(r.max_time) +
      ' (표본 ' + esc(r.sample_count) + '일)</span></div>';
  }).join("");
}

function renderLive(entry, nowMs) {
  if (!entry) return '<p class="muted">아직 수집된 데이터가 없음</p>';
  var html = "";
  var age = ageMinutes(entry.polled_at, nowMs);
  if (age === null) {
    html += '<div class="notice stale">수집 시각을 알 수 없음</div>';
  } else if (age > STALE_MIN) {
    html += '<div class="notice stale">' + age + '분 전 데이터 — 수집 시간(06:00–21:30) 외이거나 지연</div>';
  } else {
    html += '<p class="muted">' + age + '분 전 기준</p>';
  }
  var obs = (entry.observations || []).filter(function (o) { return validEta(o.eta_min); })
    .sort(function (a, b) { return Number(a.eta_min) - Number(b.eta_min); });
  var hasErr = !!(entry.errors && entry.errors.length > 0);
  if (hasErr) html += '<div class="notice error">조회 오류 — 이번 수집에서는 확인하지 못함</div>';
  if (obs.length) {
    html += obs.map(function (o) {
      return '<div class="row bus"><span><b>' + esc(o.routeno) + '번</b></span><span>' + esc(formatEta(o.eta_min)) + '</span></div>';
    }).join("");
  } else if (!hasErr) {
    html += '<p>지금 접근 중인 버스 없음</p>';
  }
  return html;
}

// collector/config.py is_allowed 의 정확한 JS 포트 (순수 함수). dirCfg = LIVE_CONFIG.directions[dir]
function isAllowed(routeid, routeno, dirCfg) {
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
    return { routeid: String(it.routeid), routeno: String(it.routeno), eta_min: Number(it.arrtime) / 60 };
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

function pad2(n) { return (n < 10 ? "0" : "") + n; }
function clockText(ms) {
  var d = new Date(ms);
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
}

// live = { observations, errors, queriedAt }  (실시간 직접 조회 결과)
function renderLiveResult(live) {
  var html = '<p class="muted">실시간 (방금 조회) ' + esc(clockText(live.queriedAt)) + '</p>';
  var hasErr = live.errors.length > 0;
  if (hasErr) html += '<div class="notice error">조회 오류 — 일부 정류소를 확인하지 못함</div>';
  if (live.observations.length) {
    html += live.observations.map(function (o) {
      return '<div class="row bus"><span><b>' + esc(o.routeno) + '번</b></span><span>' + esc(formatEta(o.eta_min)) + '</span></div>';
    }).join("");
  } else if (!hasErr) {
    html += '<p>지금 접근 중인 버스 없음</p>';
  }
  return html;
}

function renderAll(state, nowMs) {
  var d = state.dir;
  var statsHtml = state.stats === null
    ? '<p class="muted">아직 수집된 데이터가 없음</p>'
    : renderStats(state.stats[d]);
  var latestEntry = state.latest ? state.latest[d] : null;
  return {
    timetable: "<h2>" + DIR_LABELS[d] + " — 시간표</h2>" + statsHtml,
    live: "<h2>" + DIR_LABELS[d] + " — 접근 중인 버스</h2>" +
      (state.refreshFailed ? '<div class="notice error">새로고침 실패 — 이전 데이터 표시 중</div>' : "") +
      (state.live ? renderLiveResult(state.live)
        : state.liveLoading ? '<p class="muted">실시간 조회 중…</p>' : renderLive(latestEntry, nowMs))
  };
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
  module.exports = { isAllowed: isAllowed, parseArrivals: parseArrivals, selectArrivals: selectArrivals, renderLiveResult: renderLiveResult, validEta: validEta, formatEta: formatEta, ageMinutes: ageMinutes, renderStats: renderStats, renderLive: renderLive, renderAll: renderAll, renderReference: renderReference };
}

if (typeof document !== "undefined") {
  (function () {
    var state = { dir: "hakmyeong", stats: null, latest: null, live: null, liveLoading: true };
    var TAGO_URL = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList";
    var MAX_INFLIGHT = 3, MAX_ATTEMPTS = 3;
    var liveSeq = 0;

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    function fetchReg(key, reg) {
      var url = TAGO_URL + "?serviceKey=" + encodeURIComponent(key) + "&cityCode=" + encodeURIComponent(reg.city_code) +
        "&nodeId=" + encodeURIComponent(reg.node_id) + "&numOfRows=100&_type=json";
      function attempt(n) {
        return fetch(url, { cache: "no-store" }).then(function (r) { return r.json(); })
          .then(parseArrivals)
          .catch(function (e) {
            if (n >= MAX_ATTEMPTS) throw e;
            return sleep(n * 1000).then(function () { return attempt(n + 1); });
          });
      }
      return attempt(1);
    }

    // Resolves { observations, errors, queriedAt } or null if every registration failed / no config.
    function fetchLive(dir) {
      var cfg = window.LIVE_CONFIG;
      if (!cfg || !cfg.serviceKey || !cfg.directions || !cfg.directions[dir]) return Promise.resolve(null);
      var dirCfg = cfg.directions[dir];
      var regs = dirCfg.registrations, all = [], errors = [], next = 0;
      function worker() {
        if (next >= regs.length) return Promise.resolve();
        var reg = regs[next++];
        return fetchReg(cfg.serviceKey, reg).then(function (list) { all = all.concat(list); })
          .catch(function () { errors.push({ city_code: reg.city_code, node_id: reg.node_id }); })
          .then(worker);
      }
      var workers = [];
      for (var i = 0; i < Math.min(MAX_INFLIGHT, regs.length); i++) workers.push(worker());
      return Promise.all(workers).then(function () {
        if (errors.length >= regs.length) return null;
        return { observations: selectArrivals(all, dirCfg), errors: errors, queriedAt: Date.now() };
      });
    }
    var elT = document.getElementById("timetable");
    var elL = document.getElementById("live");
    var buttons = document.querySelectorAll(".dirs button");

    function draw() {
      var out = renderAll(state, Date.now());
      elT.innerHTML = out.timetable;
      elL.innerHTML = out.live;
      Array.prototype.forEach.call(buttons, function (b) {
        b.setAttribute("aria-pressed", String(b.dataset.dir === state.dir));
      });
    }

    // Resolves { data } on success, { missing: true } on 404, { failed: true } otherwise.
    function getJson(url) {
      var bust = url + (url.includes("?") ? "&" : "?") + "t=" + Date.now();
      return fetch(bust, { cache: "no-store" }).then(function (r) {
        if (r.status === 404) return { missing: true };
        if (!r.ok) return { failed: true };
        return r.json().then(function (data) { return { data: data }; });
      }).catch(function () { return { failed: true }; });
    }

    function load() {
      var dir = state.dir, seq = ++liveSeq;
      return Promise.all([getJson("data/stats.json"), getJson("data/latest.json"), fetchLive(dir).catch(function () { return null; })]).then(function (res) {
        if (seq !== liveSeq) return; // 그 사이 방향이 바뀌었거나 더 새 요청이 있음
        state.live = res[2]; state.liveLoading = false;
        var failed = false;
        if (res[0].failed) failed = true; else state.stats = res[0].missing ? null : res[0].data;
        if (res[1].failed) failed = true; else state.latest = res[1].missing ? null : res[1].data;
        state.refreshFailed = failed && !state.live;
        draw();
      });
    }

    Array.prototype.forEach.call(buttons, function (b) {
      b.addEventListener("click", function () { state.dir = b.dataset.dir; state.live = null; state.liveLoading = true; draw(); load(); });
    });
    // 참고 시간표는 정적 데이터라 한 번만 불러온다. 없거나 실패하면 섹션을 숨긴 채 둔다.
    getJson("timetable.json").then(function (res) {
      var html = res.data ? renderReference(res.data) : "";
      if (!html) return;
      document.getElementById("refbody").innerHTML = html;
      document.getElementById("reference").hidden = false;
    });

    document.getElementById("refresh").addEventListener("click", load);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
    setInterval(function () { if (!document.hidden) load(); }, 60000);
    load();
  })();
}
