/** #126：HTTP 响应工具（安全头 + json/text/html 包装）。叶子模块。 */

function securityHeaders(): Record<string, string> {
  return {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
  };
}

function json(payload: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

function text(payload: string, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(payload, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

function html(payload: string, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(payload, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

export {
  html,
  json,
  securityHeaders,
  text,
};
