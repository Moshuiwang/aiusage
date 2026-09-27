/** #126/#199：HTTP 响应工具（安全头 + json 包装）。叶子模块。网页看板删除后 html/text 已无调用者。 */

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

export {
  json,
};
