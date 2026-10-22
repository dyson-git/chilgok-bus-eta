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
function clockHM(ms) {
  var d = new Date(ms);
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
}

// res = { observations, errors, snapshotAt? } | null
function renderCard(dir, res) {
  var info = CARD_INFO[dir];
  var html = "<h2>" + esc(info.title) + '</h2><p class="sub">' + esc(info.sub) + "</p>";
  if (!res) return html + '<p class="note">확인 중…</p>';
  if (res.snapshotAt) html += '<p class="note">지금은 실시간 정보를 못 받아 ' + esc(res.snapshotAt) + ' 기록을 보여드려요</p>';
  var hasErr = res.errors > 0;
  if (hasErr) html += '<div class="warn">일부 정보를 못 받았어요</div>';
  if (res.observations.length) {
    html += res.observations.map(function (o) {
      return '<div class="bus"><span>' + esc(o.routeno) + '번</span><span class="when">' + esc(formatEta(o.eta_min)) + "</span></div>";
    }).join("");
  } else if (!hasErr) {
    html += '<div class="none">지금 오는 버스 없음</div>';
  }
  return html;
}

var CHEVRON_DOWN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9l7 7 7-7"/></svg>';
var CHEVRON_UP = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 15l7-7 7 7"/></svg>';

function renderSlots(rows) {
  if (!rows || !rows.length) return '<p class="note">아직 기록이 모이는 중이에요</p>';
  return rows.map(function (r) {
    return '<div class="slot"><div class="avg">평균 ' + esc(r.avg_time) + '</div>' +
      '<div class="rng">가장 빠름 ' + esc(r.min_time) + '</div>' +
      '<div class="rng">가장 늦음 ' + esc(r.max_time) + '</div>' +
      '<small>(' + esc(r.sample_count) + '일 기록)</small></div>';
  }).join("");
}

function renderFold(dir, stats, open) {
  var label = CARD_INFO[dir].title + " 시간표";
  var rows = stats ? stats[dir] : null;
  return '<div class="fold"><button type="button" data-fold="' + dir + '" aria-expanded="' + (open ? "true" : "false") + '">' +
    "<span>" + (open ? "접기" : esc(label)) + "</span>" + (open ? CHEVRON_UP : CHEVRON_DOWN) + "</button>" +
    (open ? '<div class="body">' + renderSlots(rows) + "</div>" : "") +
    "</div>";
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
  module.exports = { isAllowed: isAllowed, parseArrivals: parseArrivals, selectArrivals: selectArrivals, buildDirection: buildDirection, parseAllResponse: parseAllResponse, renderCard: renderCard, renderSlots: renderSlots, renderFold: renderFold, validEta: validEta, formatEta: formatEta, renderReference: renderReference };
}

if (typeof document !== "undefined") {
  (function () {
    var state = { stats: null, latest: null, res: { dongmyeong: null, hakmyeong: null },
      checkedAt: null, loading: false, open: {}, refOpen: false };
    var MAX_INFLIGHT = 3, MAX_ATTEMPTS = 3;
    var elRefresh = document.getElementById("refresh");
    var elChecked = document.getElementById("checked");
    var elFolds = document.getElementById("folds");

    function drawCards() {
      DIRS.forEach(function (d) {
        document.getElementById("card-" + d).innerHTML = renderCard(d, state.res[d]);
      });
      elRefresh.disabled = state.loading;
      elRefresh.textContent = state.loading ? "확인 중…" : "새로고침";
      elChecked.textContent = state.checkedAt ? "마지막 확인 " + clockHM(state.checkedAt) : "";
    }
    function drawFolds() {
      elFolds.innerHTML = DIRS.map(function (d) { return renderFold(d, state.stats, !!state.open[d]); }).join("");
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

    // 1순위: 중계 /all 한 번으로 전부. 실패하면 null.
    function fetchAll(c) {
      return retrying(function () {
        return fetch(c.relayUrl + "/all", { cache: "no-store" }).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        }).then(function (j) {
          if (!j || !j.results) throw new Error("bad /all");
          return parseAllResponse(j);
        });
      }, 2).catch(function () { return null; });
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
    function load() {
      var my = ++seq;
      state.loading = true;
      drawCards();
      var c = cfg();
      var livePromise = c ? fetchAll(c).then(function (m) { return m || fetchEach(c); }) : Promise.resolve(null);
      return Promise.all([livePromise, getJson("data/stats.json"), getJson("data/latest.json")]).then(function (res) {
        if (my !== seq) return;
        if (!res[1].failed) state.stats = res[1].missing ? null : res[1].data;
        if (!res[2].failed) state.latest = res[2].missing ? null : res[2].data;
        var byKey = res[0];
        DIRS.forEach(function (d) {
          var live = byKey && c.directions[d] ? buildDirection(c.directions[d], byKey) : null;
          state.res[d] = live || snapshot(d) || { observations: [], errors: 1 };
        });
        state.checkedAt = Date.now();
        state.loading = false;
        drawCards();
        drawFolds();
      });
    }

    elFolds.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-fold]");
      if (!b) return;
      var d = b.getAttribute("data-fold");
      state.open[d] = !state.open[d];
      drawFolds();
    });
    elRefresh.addEventListener("click", load);
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

    // 1분마다 자동 새로고침 (화면이 보일 때만). 돌아오면 즉시 새로고침. 이전 결과는 계속 보인다.
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
    setInterval(function () { if (!document.hidden) load(); }, 60000);
    drawFolds();
    load();
  })();
}
