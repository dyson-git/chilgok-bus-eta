// Cloudflare Worker: 서비스키를 숨긴 채 TAGO 도착정보를 중계한다.
// 키는 Worker 비밀값 TAGO_SERVICE_KEY 로만 존재하고, 코드·페이지에는 없다.
// 등록된 정류장만 허용해 남이 이 중계를 다른 용도로 쓰지 못하게 한다.
//
//   GET /arrivals?city=37390&node=CGB2479   → TAGO 원본 JSON
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

export default {
  async fetch(request, env) {
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
      const q = new URLSearchParams({
        serviceKey: env.TAGO_SERVICE_KEY.trim(),
        cityCode: city, nodeId: node, numOfRows: "100", _type: "json",
      });
      const r = await fetch("https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPrearngeInfoList?" + q);
      return new Response(await r.text(), {
        status: r.status,
        headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
      });
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
