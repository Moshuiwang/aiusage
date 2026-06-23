import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "../../aiusage-api-worker.js";

type RecordedRequest = {
  body: string;
  headers: Headers;
  method: string;
  url: string;
};

type ShadowBehavior = "ok" | "throw" | "status500";

const originBase = "https://vpn2.test:8443";
const shadowBase = "https://shadow.test";

describe("aiusage-api proxy shadow writes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the /ingest main response from VPN2 unchanged", async () => {
    const calls = installFetchMock();
    const response = await dispatchProxyRequest("/ingest", {
      body: JSON.stringify({ source_id: "mac-main" }),
      shadowUrl: "",
    });

    expect(response.status).toBe(207);
    expect(response.statusText).toBe("Origin Accepted");
    expect(response.headers.get("x-origin-result")).toBe("vpn2");
    expect(await response.text()).toBe("vpn2-main");
    expect(calls.map((call) => call.url)).toEqual([`${originBase}/ingest`]);
  });

  it("sends a shadow /ingest request with the same body and Authorization", async () => {
    const calls = installFetchMock();
    const waits: Promise<unknown>[] = [];
    const body = JSON.stringify({ source_id: "mac-shadow", daily: [{ tokens: 12 }] });

    const response = await dispatchProxyRequest("/ingest", {
      body,
      shadowUrl: shadowBase,
      waits,
      authorization: "Bearer test-token",
    });
    await Promise.all(waits);

    expect(response.status).toBe(207);
    expect(await response.text()).toBe("vpn2-main");
    expect(calls.map((call) => call.url)).toEqual([`${originBase}/ingest`, `${shadowBase}/ingest`]);
    expect(calls[1].method).toBe("POST");
    expect(calls[1].body).toBe(body);
    expect(calls[1].headers.get("authorization")).toBe("Bearer test-token");
  });

  it("keeps the main response unaffected when the shadow target throws or returns 500", async () => {
    await expectMainResponseWithShadowFailure("throw");
    await expectMainResponseWithShadowFailure("status500");
  });

  it("does not send a shadow request when SHADOW_INGEST_URL is unset", async () => {
    const calls = installFetchMock();
    const waits: Promise<unknown>[] = [];

    const response = await dispatchProxyRequest("/ingest", {
      body: JSON.stringify({ source_id: "mac-no-shadow" }),
      waits,
    });
    await Promise.all(waits);

    expect(response.status).toBe(207);
    expect(await response.text()).toBe("vpn2-main");
    expect(waits).toHaveLength(0);
    expect(calls.map((call) => call.url)).toEqual([`${originBase}/ingest`]);
  });

  it("never shadows GET requests", async () => {
    const calls = installFetchMock();
    const waits: Promise<unknown>[] = [];

    const response = await dispatchProxyRequest("/api/mobile/summary?period=today", {
      method: "GET",
      shadowUrl: shadowBase,
      waits,
    });
    await Promise.all(waits);

    expect(response.status).toBe(207);
    expect(await response.text()).toBe("vpn2-main");
    expect(waits).toHaveLength(0);
    expect(calls.map((call) => call.url)).toEqual([
      `${originBase}/api/mobile/summary?period=today`,
    ]);
  });
});

async function expectMainResponseWithShadowFailure(shadowBehavior: ShadowBehavior) {
  const calls = installFetchMock(shadowBehavior);
  const waits: Promise<unknown>[] = [];

  const response = await dispatchProxyRequest("/ingest", {
    body: JSON.stringify({ source_id: `mac-shadow-${shadowBehavior}` }),
    shadowUrl: shadowBase,
    waits,
  });
  await Promise.all(waits);

  expect(response.status).toBe(207);
  expect(response.headers.get("x-origin-result")).toBe("vpn2");
  expect(await response.text()).toBe("vpn2-main");
  expect(calls.map((call) => call.url)).toEqual([`${originBase}/ingest`, `${shadowBase}/ingest`]);
}

async function dispatchProxyRequest(
  path: string,
  options: {
    authorization?: string;
    body?: string;
    method?: string;
    shadowUrl?: string;
    waits?: Promise<unknown>[];
  } = {},
) {
  const method = options.method ?? "POST";
  const headers = new Headers();
  if (options.body !== undefined) headers.set("content-type", "application/json");
  if (options.authorization) headers.set("authorization", options.authorization);

  return worker.fetch(
    new Request(`https://aiusage.example${path}`, {
      method,
      headers,
      body: options.body,
    }),
    {
      ORIGIN_BASE_URL: originBase,
      SHADOW_INGEST_URL: options.shadowUrl,
    },
    {
      waitUntil(promise: Promise<unknown>) {
        options.waits?.push(Promise.resolve(promise));
      },
    },
  );
}

function installFetchMock(shadowBehavior: ShadowBehavior = "ok") {
  const calls: RecordedRequest[] = [];

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      calls.push({
        body: await request.text(),
        headers: new Headers(request.headers),
        method: request.method,
        url: request.url,
      });

      if (request.url.startsWith(originBase)) {
        return new Response("vpn2-main", {
          status: 207,
          statusText: "Origin Accepted",
          headers: {
            "x-origin-result": "vpn2",
          },
        });
      }

      if (request.url.startsWith(shadowBase)) {
        if (shadowBehavior === "throw") throw new Error("shadow unavailable");
        if (shadowBehavior === "status500") return new Response("shadow failed", { status: 500 });
        return new Response("shadow ok", { status: 202 });
      }

      throw new Error(`unexpected fetch URL: ${request.url}`);
    }),
  );

  return calls;
}
