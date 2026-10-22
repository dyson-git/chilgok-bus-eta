// Cloudflare Worker: 서비스키를 숨긴 채 TAGO 도착정보를 중계한다.
// 키는 Worker 비밀값 TAGO_SERVICE_KEY 로만 존재하고, 코드·페이지에는 없다.
// 등록된 정류장만 허용해 남이 이 중계를 다른 용도로 쓰지 못하게 한다.
//
//   GET /arrivals?city=37390&node=CGB2479   → TAGO 원본 JSON
//   GET /all                                → 허용된 모든 정류소를 한 번에 조회 {fetched_at, results}
//   GET /bis?stop=2479                      → 칠곡 BIS 정류장 도착정보 HTML (비교용)

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

// 칠곡 BIS STOP_ID: 학명리 건너2, 학명동, 동명면우체국, 동명면행정복지센터, 동명교통
const ALLOWED_BIS_STOPS = new Set(["2479", "2481", "2141", "2142", "4870", "4871"]);

function cors(origin) {
  const h = { "Cache-Control": "no-store", "Vary": "Origin" };
  if (ALLOWED_ORIGINS.includes(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

const TAGO_URL = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList";

const ATTEMPTS = 3;
const ATTEMPT_TIMEOUT_MS = 3500;
const BACKOFF_MS = [250, 500];
const MAX_INFLIGHT = 6;
const BUDGET_MS = 9000;
const CACHE_TTL_S = 20;
const CACHE_MIN_OK = 12;
const CACHE_KEY = "https://chilgok-bus-relay.internal/all-cache-v1";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// TAGO 게이트웨이는 HTTP 200 + 오류 봉투(returnReasonCode 04 등)로 실패를 돌려주는 일이 잦다.
// "response" 키가 없거나 resultCode 가 00 이 아니면 실패로 보고 재시도한다.
function isGoodTago(body) {
  return !!(body && body.response && (!body.response.header || !body.response.header.resultCode || body.response.header.resultCode === "00"));
}

async function fetchNode(key, id, deadline) {
  const [city, node] = id.split(":");
  const q = new URLSearchParams({
    serviceKey: key.trim(), cityCode: city, nodeId: node, numOfRows: "100", _type: "json",
  });
  let lastErr = "unknown";
  for (let i = 0; i < ATTEMPTS; i++) {
    if (i > 0) {
      const wait = BACKOFF_MS[i - 1];
      if (Date.now() + wait >= deadline) break;
      await sleep(wait);
    }
    if (Date.now() >= deadline) break;
    try {
      const r = await fetch(TAGO_URL + "?" + q, { signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS) });
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

// 동시에 MAX_INFLIGHT 개까지만 TAGO 로 보낸다 (버스트에 게이트웨이가 약함).
async function fetchAllNodes(key) {
  const ids = [...ALLOWED_NODES];
  const deadline = Date.now() + BUDGET_MS;
  const results = {};
  let next = 0;
  async function worker() {
    while (next < ids.length) {
      const id = ids[next++];
      try {
        results[id] = { ok: true, body: await fetchNode(key, id, deadline) };
      } catch (e) {
        results[id] = { ok: false, error: String((e && e.message) || e) };
      }
    }
  }
  await Promise.all(Array.from({ length: MAX_INFLIGHT }, worker));
  return results;
}

export default {
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
      const hit = await cache.match(CACHE_KEY);
      if (hit) return new Response(await hit.text(), { status: 200, headers: { ...jsonHeaders, "X-Relay-Cache": "hit" } });
      const results = await fetchAllNodes(env.TAGO_SERVICE_KEY);
      const okCount = Object.values(results).filter((r) => r.ok).length;
      const text = JSON.stringify({ fetched_at: new Date().toISOString(), results });
      if (okCount >= CACHE_MIN_OK) {
        const toCache = new Response(text, { headers: { "Content-Type": "application/json", "Cache-Control": "max-age=" + CACHE_TTL_S } });
        ctx.waitUntil(cache.put(CACHE_KEY, toCache));
      }
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

    return new Response("not found", { status: 404, headers });
  },
};
