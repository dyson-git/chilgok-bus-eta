"use strict";
var DIR_LABELS = { hakmyeong: "학명리방향", dongmyeong: "동명방향" };
var STALE_MIN = 15;

function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

// ETA 분(실수) -> 표시 문자열. 경과시간 차감 없음.
function formatEta(etaMin) {
  var n = Number(etaMin);
  if (!isFinite(n)) return "도착 시간 알 수 없음";
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
  var obs = (entry.observations || []).slice().sort(function (a, b) { return a.eta_min - b.eta_min; });
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
    live: "<h2>" + DIR_LABELS[d] + " 지금 접근 중</h2>" + renderLive(latestEntry, nowMs)
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { formatEta: formatEta, ageMinutes: ageMinutes, renderStats: renderStats, renderLive: renderLive, renderAll: renderAll };
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

    function getJson(url) {
      return fetch(url, { cache: "no-store" }).then(function (r) {
        return r.ok ? r.json() : null;
      }).catch(function () { return null; });
    }

    function load() {
      return Promise.all([getJson("data/stats.json"), getJson("data/latest.json")]).then(function (res) {
        state.stats = res[0];
        state.latest = res[1];
        draw();
      });
    }

    Array.prototype.forEach.call(buttons, function (b) {
      b.addEventListener("click", function () { state.dir = b.dataset.dir; draw(); });
    });
    document.getElementById("refresh").addEventListener("click", load);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
    setInterval(function () { if (!document.hidden) load(); }, 60000);
    load();
  })();
}
