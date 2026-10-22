"use strict";
var DIR_LABELS = { hakmyeong: "학명리방향", dongmyeong: "동명방향" };
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

function renderAll(state, nowMs) {
  var d = state.dir;
  var statsHtml = state.stats === null
    ? '<p class="muted">아직 수집된 데이터가 없음</p>'
    : renderStats(state.stats[d]);
  var latestEntry = state.latest ? state.latest[d] : null;
  return {
    timetable: "<h2>" + DIR_LABELS[d] + " 시간표</h2>" + statsHtml,
    live: "<h2>" + DIR_LABELS[d] + " 지금 접근 중</h2>" +
      (state.refreshFailed ? '<div class="notice error">새로고침 실패 — 이전 데이터 표시 중</div>' : "") +
      renderLive(latestEntry, nowMs)
  };
}

// 기점·종점 기준 참고 시간표. 변환·보정 없이 원본 시각 그대로 표시한다.
function renderReference(tt) {
  if (!tt || !Array.isArray(tt.routes) || !tt.routes.length) return "";
  var html = "";
  if (tt.note) html += '<div class="notice stale">' + esc(tt.note) + '</div>';
  html += tt.routes.map(function (r) {
    var trips = (r.trips || []).map(function (t) {
      return '<div class="trip">' + esc(t.from) + ' <b>' + esc(t.depart) + '</b> → ' + esc(t.to) + ' ' + esc(t.arrive) + '</div>';
    }).join("");
    return '<div class="rt"><div><b>' + esc(r.routeno) + '번</b> <span class="muted">' + esc(r.path) + '</span></div>' + trips + '</div>';
  }).join("");
  if (Array.isArray(tt.missing) && tt.missing.length) {
    html += '<p class="muted">시간표 없음: ' + tt.missing.map(esc).join(", ") + '</p>';
  }
  if (tt.source) html += '<p class="muted">' + esc(tt.source) + '</p>';
  return html;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { validEta: validEta, formatEta: formatEta, ageMinutes: ageMinutes, renderStats: renderStats, renderLive: renderLive, renderAll: renderAll, renderReference: renderReference };
}

if (typeof document !== "undefined") {
  (function () {
    var state = { dir: "hakmyeong", stats: null, latest: null };
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
      return fetch(url, { cache: "no-store" }).then(function (r) {
        if (r.status === 404) return { missing: true };
        if (!r.ok) return { failed: true };
        return r.json().then(function (data) { return { data: data }; });
      }).catch(function () { return { failed: true }; });
    }

    function load() {
      return Promise.all([getJson("data/stats.json"), getJson("data/latest.json")]).then(function (res) {
        var failed = false;
        if (res[0].failed) failed = true; else state.stats = res[0].missing ? null : res[0].data;
        if (res[1].failed) failed = true; else state.latest = res[1].missing ? null : res[1].data;
        state.refreshFailed = failed;
        draw();
      });
    }

    Array.prototype.forEach.call(buttons, function (b) {
      b.addEventListener("click", function () { state.dir = b.dataset.dir; draw(); });
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
