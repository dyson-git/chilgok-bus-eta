// Cloudflare Worker: 서비스키를 숨긴 채 TAGO 도착정보를 중계한다.
// 키는 Worker 비밀값 TAGO_SERVICE_KEY 로만 존재하고, 코드·페이지에는 없다.
// 등록된 정류장만 허용해 남이 이 중계를 다른 용도로 쓰지 못하게 한다.
//
//   GET /arrivals?city=37390&node=CGB2479   → TAGO 원본 JSON
//   GET /all                                → 허용된 모든 정류소를 한 번에 조회 {fetched_at, results}
//   GET /loc                                → 허용된 모든 노선의 운행 중 버스 "현재 위치" {fetched_at, results}
//   GET /bis?stop=2479                      → 칠곡 BIS 정류장 도착정보 HTML (비교용)
//   GET /dgb?bs=7181001900                  → 대구 BIS 정류장 도착정보 JSON (칠곡3·급행9-3)
//   GET /obs?hour=2026-10-24T16             → 그 한 시간(한국 시각) 동안 5분마다 쌓은 도착정보 [{fetched_at, results}]
//   GET /trk?hour=2026-10-27T15             → 그 한 시간 동안 대구 BIS 를 1분마다 따라간 칠곡3·급행9-3 [{started, samples}]
//   (Cron Trigger "*/5 * * * *")            → 수집 시간(한국 06:00~22:00)에 전 정류소 도착정보를 KV(바인딩 OBS)에 쌓는다
//   (Cron Trigger "2-59/5 * * * *")         → 같은 시간에 대구 BIS 정류장을 1분마다 5번 묻고 KV 키 하나로 쌓는다(따라가기)
//   (위 "*/5" 크론의 매시 10분)              → 비밀값 GITHUB_TOKEN 이 있으면 GitHub import 작업을 시작시킨다(GitHub 예약 실행이 안 돌아서)

const ALLOWED_ORIGINS = [
  "https://dyson-git.github.io",
  "http://127.0.0.1:8768",
  "http://localhost:8768",
];

// collector/config.py DIRECTIONS 와 같은 목록. 바뀌면 여기도 고친다.
const ALLOWED_NODES = new Set([
  "37390:CGB2142", "37050:GMB2142", "22:DGB7181001000",
  "37390:CGB2141", "37050:GMB2141", "22:DGB3690003750",
  "37390:CGB4870", "37390:CGB4871", "37050:GMB4871", "37100:GYB369007000",
  "22:DGB7181007000", "22:DGB3690005830",
  "37390:CGB2479", "37050:GMB2479", "37100:GYB369001900", "22:DGB7181001900",
]);

// 위치 조회 허용 노선 "cityCode:routeId". collector/route_stops.json(scripts/resolve_routes.py)과 같은 목록 - 바뀌면 여기도 고친다.
const ALLOWED_ROUTES = new Set([
  "37390:CGB30010", "37390:CGB30020", "37390:CGB3410",
  "37390:CGB3420", "37390:CGB34-110", "37390:CGB34-120",
  "37390:CGB3610", "37390:CGB3620", "37390:CGB36-110",
  "37390:CGB36-120", "37050:GMB88520", "37390:CGB9-310",
  "22:DGB1000009300", "22:DGB4090003001", "22:DGB4090003011",
  "22:DGB4090003014", "22:DGB4090003015", "37050:GMB88510",
  "37390:CGB9-320", "22:DGB4090003023",
]);

// 칠곡 BIS STOP_ID: 학명리 건너2, 학명동, 동명면우체국, 동명면행정복지센터, 동명교통
const ALLOWED_BIS_STOPS = new Set(["2479", "2481", "2483", "2485", "2141", "2142", "4870", "4871"]);
// 대구 BIS bsId: 학명리 건너2, 학명리, 학명리(등골마을입구) - 칠곡3·급행9-3 은 대구 시스템 버스라 칠곡 BIS 에 실시간이 없다
const ALLOWED_DGB_STOPS = new Set(["7181001900", "3690003070", "3690003090"]);

function cors(origin) {
  const h = { "Cache-Control": "no-store", "Vary": "Origin" };
  if (ALLOWED_ORIGINS.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

const TAGO_URL = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList";
const LOC_URL = "https://apis.data.go.kr/1613000/BusLcInfoInqireService/getRouteAcctoBusLcList";

const ATTEMPTS = 3;
const LOC_ATTEMPTS = 2; // /loc 는 노선이 20개라 3번씩 시도하면 Workers 무료 한도(요청 1회당 외부 호출 50개)를 넘어 뒤쪽 노선이 통째로 실패한다
const ATTEMPT_TIMEOUT_MS = 3500;
const BACKOFF_MS = [250, 500];
const RATE_BACKOFF_MS = 1000; // TAGO 23(초당 요청 제한): 0.25초 뒤엔 또 걸린다(2026-10-25 /loc 20개 전부 23) - 1초 쉬고 다시 묻는다
const MAX_INFLIGHT = 6;
const BUDGET_MS = 9000;
const CACHE_TTL_S = 60; // /all: 화면이 받은 시각(fetched_at)부터 초 단위로 줄여 보여주므로 길게 둔다(TAGO 호출을 줄인다)
const PARTIAL_CACHE_TTL_S = 20; // 일부 정류소/노선만 성공했을 때
const FAIL_CACHE_TTL_S = 15; // 대부분 실패했을 때도 잠깐 들고 있는다 - TAGO 가 429 를 걸 때 요청이 계속 몰려 제한을 키우지 않게
const FRESH_MIN_AGE_MS = 15000; // 새로고침 버튼(?fresh=1)은 캐시를 건너뛰되, 연타로 TAGO 429 가 나지 않게 15초 안의 사본은 재사용한다
const CACHE_KEY = "https://chilgok-bus-relay.internal/all-cache-v1";
const LOC_CACHE_TTL_S = 45; // /loc: 노선 20개를 한 번에 부르는 호출이라 TAGO 429(요청 제한)를 피하려고 길게 둔다
const LOC_MAX_INFLIGHT = 3;
const LOC_CACHE_KEY = "https://chilgok-bus-relay.internal/loc-cache-v1";

async function readCache(cache, key, fresh) {
  const hit = await cache.match(key);
  if (!hit) return null;
  const text = await hit.text();
  if (!fresh) return text;
  let age = Infinity;
  try { age = Date.now() - Date.parse(JSON.parse(text).fetched_at); } catch (e) { /* 읽을 수 없으면 새로 받는다 */ }
  return age < FRESH_MIN_AGE_MS ? text : null;
}

// 다 성공하면 오래, 일부만 성공하면 짧게, 대부분 실패하면 아주 짧게 들고 있는다.
function cacheTtl(okCount, total, fullTtl) {
  if (okCount === total) return fullTtl;
  if (okCount >= Math.ceil(total * 0.75)) return Math.min(fullTtl, PARTIAL_CACHE_TTL_S);
  return FAIL_CACHE_TTL_S;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// TAGO 게이트웨이는 HTTP 200 + 오류 봉투(returnReasonCode 04 등)로 실패를 돌려주는 일이 잦다.
// "response" 키가 없거나 resultCode 가 00 이 아니면 실패로 보고 재시도한다.
function isGoodTago(body) {
  return !!(body && body.response && (!body.response.header || !body.response.header.resultCode || body.response.header.resultCode === "00"));
}

async function fetchTago(baseUrl, params, deadline, attempts = ATTEMPTS) {
  const q = new URLSearchParams(params);
  let lastErr = "unknown";
  for (let i = 0; i < attempts; i++) {
    if (i > 0) {
      const wait = lastErr === "TAGO 23" ? RATE_BACKOFF_MS : BACKOFF_MS[i - 1];
      if (Date.now() + wait >= deadline) break;
      await sleep(wait);
    }
    if (Date.now() >= deadline) break;
    try {
      const r = await fetch(baseUrl + "?" + q, { signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS) });
      const body = await r.json();
      if (isGoodTago(body)) return body;
      const h = (body && body.OpenAPI_ServiceResponse && body.OpenAPI_ServiceResponse.cmmMsgHeader) || {};
      lastErr = "TAGO " + (h.returnReasonCode || (body && body.response && body.response.header && body.response.header.resultCode) || "bad body");
    } catch (e) {
      lastErr = String((e && e.message) || e);
    }
  }
  throw new Error(lastErr);
}

function fetchNode(key, id, deadline) {
  const [city, node] = id.split(":");
  return fetchTago(TAGO_URL, { serviceKey: key.trim(), cityCode: city, nodeId: node, numOfRows: "100", _type: "json" }, deadline);
}

function fetchRoute(key, id, deadline) {
  const [city, routeId] = id.split(":");
  return fetchTago(LOC_URL, { serviceKey: key.trim(), cityCode: city, routeId, numOfRows: "100", _type: "json" }, deadline, LOC_ATTEMPTS);
}

// 동시에 MAX_INFLIGHT 개까지만 TAGO 로 보낸다 (버스트에 게이트웨이가 약함).
async function fetchMany(ids, fetchOne, inflight = MAX_INFLIGHT) {
  const deadline = Date.now() + BUDGET_MS;
  const results = {};
  let next = 0;
  async function worker() {
    while (next < ids.length) {
      const id = ids[next++];
      try {
        results[id] = { ok: true, body: await fetchOne(id, deadline) };
      } catch (e) {
        results[id] = { ok: false, error: String((e && e.message) || e) };
      }
    }
  }
  await Promise.all(Array.from({ length: inflight }, worker));
  return results;
}

const fetchAllNodes = (key) => fetchMany([...ALLOWED_NODES], (id, dl) => fetchNode(key, id, dl));
const fetchAllRoutes = (key) => fetchMany([...ALLOWED_ROUTES], (id, dl) => fetchRoute(key, id, dl), LOC_MAX_INFLIGHT);

// ---- 클라우드 수집 (2026-10-24): PC 를 꺼도 시간표 기록이 이어지게 ----
// 수집 한 번 = KV 키 하나 "obs:<한국 YYYY-MM-DDTHH>:<분>"(읽고 고쳐 쓰지 않아 겹쳐 돌아도 안 잃는다), 7일 뒤 자동 삭제.
// GitHub Actions(.github/workflows/import.yml)가 1시간마다 /obs 로 가져가 collector/cloud_import.py 로 기록한다.
const OBS_TTL_S = 7 * 86400;
const WINDOW_START_MIN = 6 * 60, WINDOW_END_MIN = 22 * 60; // collector/poll.py 수집 시간과 같다(06:00~22:00)

function kstClock(ms) {
  const iso = new Date(ms + 9 * 3600 * 1000).toISOString();
  return { hour: iso.slice(0, 13), minute: iso.slice(14, 16), dayMin: Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16)) };
}

// TAGO 응답 -> [{routeid, routeno, arrtime}] (collector/tago_client.py 와 같은 해석). 필요한 값만 남겨 KV 에 쓴다.
function tagoItems(body) {
  const items = body && body.response && body.response.body && body.response.body.items;
  if (!items) return [];
  let list = items.item;
  if (list === undefined || list === null) return [];
  if (!Array.isArray(list)) list = [list];
  return list.map((it) => ({ routeid: String(it.routeid), routeno: String(it.routeno), arrtime: Number(it.arrtime) }));
}

async function collectSnapshot(env) {
  const started = Date.now(), clock = kstClock(started);
  if (clock.dayMin < WINDOW_START_MIN || clock.dayMin > WINDOW_END_MIN) return;
  const results = await fetchAllNodes(env.TAGO_SERVICE_KEY);
  const compact = {};
  for (const [id, r] of Object.entries(results)) compact[id] = r.ok ? { ok: true, items: tagoItems(r.body) } : { ok: false, error: r.error };
  await env.OBS.put("obs:" + clock.hour + ":" + clock.minute,
    JSON.stringify({ fetched_at: new Date(started).toISOString(), results: compact }), { expirationTtl: OBS_TTL_S });
}

// ---- 대구 BIS 따라가기 (2026-10-27): 예상 시각과 실제 지나간 시각을 PC 없이 비교하려고 ----
// 대구 "N분"은 정류장에서 시간 맞추려 서 있는 걸 모른다(급행9-3 금화리건너, 칠곡3 동명교통). 1분 간격이어야 지나간 때가 보인다.
// TAGO 수집과 다른 크론으로 돌린다: 한 번 실행에 외부 호출 50개 한도를 TAGO(16곳 x 최대 3번)와 나눠 쓰지 않게.
// KV 쓰기는 5분에 한 번(1분마다 쓰면 무료 한도 하루 1000번을 넘는다).
const TRACK_CRON = "2-59/5 * * * *";
const TRACK_ROUTES = new Set(["칠곡3", "급행9-3"]);
const TRACK_SAMPLES = 5, TRACK_STEP_MS = 60000;
const DGB_TIMEOUT_MS = 8000; // 대구 서버는 Cloudflare 에서 가끔 3.5초를 넘긴다(10/28 14:02 첫 회 3곳 x 5번 전부 시간 초과)
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));

// 대구 응답 -> 칠곡3·급행9-3 만 [{route, vhc, gap, bs, state}]. vhcNo2 는 가끔 없다.
function dgbItems(body) {
  const list = (body && body.body && body.body.list) || [];
  return list.filter((x) => TRACK_ROUTES.has(x.routeNo))
    .map((x) => ({ route: x.routeNo, vhc: x.vhcNo2 || null, gap: x.bsGap, bs: x.bsNm, state: x.arrState }));
}

async function sampleDgb() {
  const stops = {};
  await Promise.all([...ALLOWED_DGB_STOPS].map(async (bs) => {
    try {
      const r = await fetch("https://businfo.daegu.go.kr:8095/dbms_web_api/realtime/arr/" + bs,
        { headers: { "User-Agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(DGB_TIMEOUT_MS) });
      stops[bs] = { ok: true, items: dgbItems(await r.json()) };
    } catch (e) {
      stops[bs] = { ok: false, error: String((e && e.message) || e) };
    }
  }));
  return stops;
}

async function trackDgb(env, sleep = sleepMs) {
  const started = Date.now(), clock = kstClock(started);
  if (clock.dayMin < WINDOW_START_MIN || clock.dayMin > WINDOW_END_MIN) return;
  const samples = [];
  for (let i = 0; i < TRACK_SAMPLES; i++) {
    if (i) await sleep(started + i * TRACK_STEP_MS - Date.now());
    samples.push({ t: new Date(Date.now()).toISOString(), stops: await sampleDgb() });
  }
  await env.OBS.put("trk:" + clock.hour + ":" + clock.minute,
    JSON.stringify({ started: new Date(started).toISOString(), samples }), { expirationTtl: OBS_TTL_S });
}

// ---- import 시작 (2026-10-29): GitHub 예약 실행(cron)이 이 저장소에서 한 번도 안 돌아 PC 작업이 대신 시작했다 - PC 없이 ----
// GITHUB_TOKEN = 이 저장소 Actions 쓰기 권한만 있는 fine-grained 토큰(Worker 비밀값). 없으면 아무것도 안 한다.
const IMPORT_DISPATCH_URL = "https://api.github.com/repos/dyson-git/chilgok-bus-eta/actions/workflows/import.yml/dispatches";
const IMPORT_MINUTE = "10";

async function triggerImport(env) {
  const r = await fetch(IMPORT_DISPATCH_URL, {
    method: "POST",
    headers: { "Authorization": "Bearer " + env.GITHUB_TOKEN, "Accept": "application/vnd.github+json",
      "User-Agent": "chilgok-bus-relay", "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  if (r.status !== 204) console.log("import dispatch " + r.status);
}

async function listHour(env, prefix, hour) {
  const listed = await env.OBS.list({ prefix: prefix + hour + ":" });
  const values = await Promise.all(listed.keys.map((k) => env.OBS.get(k.name, "json")));
  return values.filter(Boolean);
}

export default {
  async scheduled(event, env, ctx) {
    if (!env.OBS) return;
    if (event.cron === TRACK_CRON) { ctx.waitUntil(trackDgb(env)); return; }
    if (env.GITHUB_TOKEN) {
      const clock = kstClock(event.scheduledTime || Date.now());
      if (clock.minute === IMPORT_MINUTE && clock.dayMin >= WINDOW_START_MIN && clock.dayMin <= WINDOW_END_MIN) ctx.waitUntil(triggerImport(env));
    }
    if (!env.TAGO_SERVICE_KEY) return;
    ctx.waitUntil(collectSnapshot(env));
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const headers = cors(origin);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    if (request.method !== "GET") return new Response("method not allowed", { status: 405, headers });

    if (url.pathname === "/arrivals") {
      const city = url.searchParams.get("city") || "";
      const node = url.searchParams.get("node") || "";
      if (!ALLOWED_NODES.has(city + ":" + node)) return new Response("stop not allowed", { status: 403, headers });
      if (!env.TAGO_SERVICE_KEY) return new Response("TAGO_SERVICE_KEY not set", { status: 500, headers });
      const jsonHeaders = { ...headers, "Content-Type": "application/json; charset=utf-8" };
      try {
        const body = await fetchNode(env.TAGO_SERVICE_KEY, city + ":" + node, Date.now() + BUDGET_MS);
        return new Response(JSON.stringify(body), { status: 200, headers: jsonHeaders });
      } catch (e) {
        return new Response(JSON.stringify({ error: String((e && e.message) || e) }), { status: 502, headers: jsonHeaders });
      }
    }

    if (url.pathname === "/all") {
      if (!env.TAGO_SERVICE_KEY) return new Response("TAGO_SERVICE_KEY not set", { status: 500, headers });
      const jsonHeaders = { ...headers, "Content-Type": "application/json; charset=utf-8" };
      const cache = caches.default;
      const hit = await readCache(cache, CACHE_KEY, url.searchParams.get("fresh") === "1");
      if (hit) return new Response(hit, { status: 200, headers: { ...jsonHeaders, "X-Relay-Cache": "hit" } });
      const results = await fetchAllNodes(env.TAGO_SERVICE_KEY);
      const okCount = Object.values(results).filter((r) => r.ok).length;
      const text = JSON.stringify({ fetched_at: new Date().toISOString(), results });
      const ttl = cacheTtl(okCount, ALLOWED_NODES.size, CACHE_TTL_S);
      ctx.waitUntil(cache.put(CACHE_KEY, new Response(text, { headers: { "Content-Type": "application/json", "Cache-Control": "max-age=" + ttl } })));
      return new Response(text, { status: 200, headers: { ...jsonHeaders, "X-Relay-Cache": "miss" } });
    }

    if (url.pathname === "/loc") {
      if (!env.TAGO_SERVICE_KEY) return new Response("TAGO_SERVICE_KEY not set", { status: 500, headers });
      const jsonHeaders = { ...headers, "Content-Type": "application/json; charset=utf-8" };
      const cache = caches.default;
      const hit = await readCache(cache, LOC_CACHE_KEY, url.searchParams.get("fresh") === "1");
      if (hit) return new Response(hit, { status: 200, headers: { ...jsonHeaders, "X-Relay-Cache": "hit" } });
      const results = await fetchAllRoutes(env.TAGO_SERVICE_KEY);
      const okCount = Object.values(results).filter((r) => r.ok).length;
      const text = JSON.stringify({ fetched_at: new Date().toISOString(), results });
      const ttl = cacheTtl(okCount, ALLOWED_ROUTES.size, LOC_CACHE_TTL_S);
      ctx.waitUntil(cache.put(LOC_CACHE_KEY, new Response(text, { headers: { "Content-Type": "application/json", "Cache-Control": "max-age=" + ttl } })));
      return new Response(text, { status: 200, headers: { ...jsonHeaders, "X-Relay-Cache": "miss" } });
    }

    if (url.pathname === "/bis") {
      const stop = url.searchParams.get("stop") || "";
      if (!ALLOWED_BIS_STOPS.has(stop)) return new Response("stop not allowed", { status: 403, headers });
      const r = await fetch("https://bus.chilgok.go.kr/map/AjaxRouteListByStop.do", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "X-Requested-With": "XMLHttpRequest" },
        body: "station_id=" + encodeURIComponent(stop),
      });
      return new Response(await r.text(), {
        status: r.status,
        headers: { ...headers, "Content-Type": "text/html; charset=utf-8" },
      });
    }

    if (url.pathname === "/obs" || url.pathname === "/trk") {
      const hour = url.searchParams.get("hour") || "";
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}$/.test(hour)) return new Response("bad hour", { status: 400, headers });
      if (!env.OBS) return new Response("OBS not bound", { status: 503, headers });
      const values = await listHour(env, url.pathname.slice(1) + ":", hour);
      return new Response(JSON.stringify(values), {
        status: 200,
        headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
      });
    }

    if (url.pathname === "/dgb") {
      const bs = url.searchParams.get("bs") || "";
      if (!ALLOWED_DGB_STOPS.has(bs)) return new Response("stop not allowed", { status: 403, headers });
      const r = await fetch("https://businfo.daegu.go.kr:8095/dbms_web_api/realtime/arr/" + bs, { headers: { "User-Agent": "Mozilla/5.0" } });
      return new Response(await r.text(), {
        status: r.status,
        headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
      });
    }

    return new Response("not found", { status: 404, headers });
  },
};
