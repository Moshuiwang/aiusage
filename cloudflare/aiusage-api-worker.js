const DEFAULT_ORIGIN_BASE_URL = "https://vpn2.chunbai.com:8443";

const WEB_PATH_MARKERS = [
  "dashboard",
  "login",
  "static/dashboard.css",
  "static/dashboard.js",
];

const BUSINESS_PATH_MARKERS = [
  "api/summary",
  "api/mobile/summary",
  "api/health",
  "ingest",
  "ingest-limits",
];

export default {
  async fetch(request, env) {
    const incomingURL = new URL(request.url);

    if (!isHandledPath(incomingURL.pathname)) {
      return jsonError(404, "not_found", "Cloudflare Worker only handles AI Usage web, API, and ingest paths.");
    }

    return proxyToOrigin(request, env, incomingURL);
  },
};

async function proxyToOrigin(request, env, incomingURL) {
  const originURL = buildOriginURL(env.ORIGIN_BASE_URL, incomingURL);
  const init = await buildProxyInit(request, incomingURL);

  const response = await fetch(new Request(originURL, init));
  const responseHeaders = new Headers(response.headers);
  applyNoStoreHeaders(responseHeaders);

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders,
  });
}

async function buildProxyInit(request, incomingURL) {
  const headers = buildForwardHeaders(request.headers, incomingURL);
  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    const body = await request.arrayBuffer();
    init.body = body;
    headers.delete("transfer-encoding");
    headers.set("content-length", String(body.byteLength));
  }

  return init;
}

function buildOriginURL(configuredOrigin, incomingURL) {
  const origin = new URL(configuredOrigin || DEFAULT_ORIGIN_BASE_URL);
  origin.pathname = incomingURL.pathname;
  origin.search = incomingURL.search;
  return origin;
}

function buildForwardHeaders(sourceHeaders, incomingURL) {
  const headers = new Headers(sourceHeaders);
  headers.delete("host");
  headers.set("X-Forwarded-Host", incomingURL.host);
  headers.set("X-Forwarded-Proto", incomingURL.protocol.replace(":", ""));
  return headers;
}

function isHandledPath(pathname) {
  return (
    pathname === "/" ||
    pathname === "/dashboard" ||
    pathname === "/login" ||
    pathname.startsWith("/static/") ||
    pathname.startsWith("/api/") ||
    pathname === "/ingest" ||
    pathname === "/ingest-limits"
  );
}

function jsonError(status, errorType, message) {
  const headers = new Headers({
    "Content-Type": "application/json; charset=utf-8",
  });
  applyNoStoreHeaders(headers);
  return new Response(
    JSON.stringify({
      status: "error",
      error_type: errorType,
      message,
      known_paths: WEB_PATH_MARKERS.concat(BUSINESS_PATH_MARKERS),
    }),
    { status, headers },
  );
}

function applyNoStoreHeaders(headers) {
  headers.set("Cache-Control", "no-store, max-age=0");
  headers.set("CDN-Cache-Control", "no-store");
  headers.set("Cloudflare-CDN-Cache-Control", "no-store");
  headers.set("Vary", mergeVary(headers.get("Vary"), ["Authorization", "Cookie"]));
}

function mergeVary(current, requiredValues) {
  const values = new Set();
  for (const item of String(current || "").split(",")) {
    const normalized = item.trim();
    if (normalized) values.add(normalized);
  }
  for (const item of requiredValues) values.add(item);
  return Array.from(values).join(", ");
}
