type Row = Record<string, unknown>;
type Model = { id: string; label: string; tokens: number; status: "available" | "missing" };
type Agent = Model & { models: Model[] };

function tokens(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

function agentID(value: unknown): string {
  const id = String(value || "unknown").toLowerCase();
  if (id.includes("claude")) return "claude";
  if (id.includes("codex") || id.includes("openai") || id.includes("gpt")) return "codex";
  return id;
}

/** Read-model projection: clients receive every source/Agent/model subtotal. */
export function sourceAgents(items: Row[]): Agent[] {
  const grouped = new Map<string, { total: number; seen: boolean; models: Map<string, number> }>();
  for (const id of ["claude", "codex"]) grouped.set(id, { total: 0, seen: false, models: new Map() });
  for (const item of items) {
    const id = agentID(item.agent);
    const group = grouped.get(id) ?? { total: 0, seen: false, models: new Map<string, number>() };
    const total = tokens(item.total_tokens);
    group.total += total;
    group.seen = true;
    const inputModels = Array.isArray(item.model_breakdowns) ? item.model_breakdowns as Row[] : [];
    const modelTotal = inputModels.reduce((sum, model) => sum + tokens(model.total_tokens), 0);
    // Inconsistent details cannot be presented as trustworthy model allocation.
    const validModels = modelTotal <= total ? inputModels : [];
    for (const model of validModels) {
      const name = String(model.model_name || "unknown");
      group.models.set(name, (group.models.get(name) ?? 0) + tokens(model.total_tokens));
    }
    const unknown = total - (modelTotal <= total ? modelTotal : 0);
    if (unknown > 0) group.models.set("unknown", (group.models.get("unknown") ?? 0) + unknown);
    grouped.set(id, group);
  }
  return [...grouped].map(([id, group]) => ({
    id, label: id === "claude" ? "Claude" : id === "codex" ? "Codex" : id,
    tokens: group.total, status: group.seen ? "available" : "missing",
    models: [...group.models].filter(([, amount]) => amount > 0)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, amount]) => ({ id: name, label: name === "unknown" ? "模型未知" : name,
        tokens: amount, status: name === "unknown" ? "missing" : "available" })),
  }));
}

export function sourceBreakdown(items: Row[], identities: Row[]): Row[] {
  const groups = new Map<string, Row[]>();
  for (const item of items) {
    const id = String(item.source_id || "unknown");
    const rows = groups.get(id) ?? [];
    rows.push(item);
    groups.set(id, rows);
  }
  return [...groups].map(([id, rows]) => {
    const identity = identities.find(row => row.source_id === id) ?? {};
    const machine = String(identity.machine || identity.host || rows[0].machine || id);
    const osUser = String(identity.os_user || rows[0].account || "unknown");
    const total = rows.reduce((sum, row) => sum + tokens(row.total_tokens), 0);
    return { id, label: `${osUser} / ${machine}`, machine, os_user: osUser,
      tokens: total, source_ids: [id], contributions: [{ source_id: id, tokens: total }], agents: sourceAgents(rows) };
  }).sort((a, b) => Number(b.tokens) - Number(a.tokens) || String(a.id).localeCompare(String(b.id)));
}
