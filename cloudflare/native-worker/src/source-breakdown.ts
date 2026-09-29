type Row = Record<string, unknown>;
type QuotaEstimate = { percent: number; grade: string; basis: string };
type Model = { id: string; label: string; tokens: number; status: "available" | "missing"; quota_estimate?: QuotaEstimate };
type Agent = Model & { models: Model[] };

function quotaEstimateOf(model: Row): QuotaEstimate | undefined {
  const qe = model.quota_estimate;
  if (qe === null || typeof qe !== "object") return undefined;
  const { percent, grade, basis } = qe as Row;
  if (typeof percent !== "number" || typeof grade !== "string" || typeof basis !== "string") return undefined;
  return { percent, grade, basis };
}

/** #207 每个云端会话一个 `claude-cloud-<session_id>` 来源；展示层统一归并成这一个来源。 */
export const CLOUD_SOURCE_ID = "claude-cloud";
export const CLOUD_SOURCE_LABEL = "云端";
const CLOUD_SOURCE_PREFIX = "claude-cloud-";

export function displaySourceId(sourceId: unknown): string {
  const id = String(sourceId ?? "");
  return id === CLOUD_SOURCE_ID || id.startsWith(CLOUD_SOURCE_PREFIX) ? CLOUD_SOURCE_ID : id;
}

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
  type ModelGroup = { total: number; seen: boolean; models: Map<string, number>; quota: Map<string, QuotaEstimate> };
  const grouped = new Map<string, ModelGroup>();
  for (const id of ["claude", "codex"]) grouped.set(id, { total: 0, seen: false, models: new Map(), quota: new Map() });
  for (const item of items) {
    const id = agentID(item.agent);
    const group = grouped.get(id) ?? { total: 0, seen: false, models: new Map<string, number>(), quota: new Map<string, QuotaEstimate>() };
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
      // #183-b：quota_estimate 的 percent 对 token 数是线性的（同一族价格加权系数固定），
      // 同一模型名跨多条 model_breakdowns 的 percent 可以直接相加——但只在 grade/basis
      // 一致时才相加（正常情况下同一批次同一模型的 quota_estimate 必然来自同一条
      // quota_calibration 行，grade/basis 恒定；不一致就是数据反常，整个撤销不猜）。
      const qe = quotaEstimateOf(model);
      if (qe) {
        const existing = group.quota.get(name);
        if (!existing) group.quota.set(name, { ...qe });
        else if (existing.grade === qe.grade && existing.basis === qe.basis) existing.percent += qe.percent;
        else group.quota.delete(name);
      }
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
      .map(([name, amount]) => {
        const status: Model["status"] = name === "unknown" ? "missing" : "available";
        const model: Model = { id: name, label: name === "unknown" ? "模型未知" : name, tokens: amount, status };
        // 只在 status === "available"（真实模型名，不是撤销分摊的 "unknown" 占位）时附加。
        const quota = status === "available" ? group.quota.get(name) : undefined;
        if (quota) model.quota_estimate = quota;
        return model;
      }),
  }));
}

export function sourceBreakdown(items: Row[], identities: Row[]): Row[] {
  const groups = new Map<string, Row[]>();
  for (const item of items) {
    const id = displaySourceId(item.source_id || "unknown");
    const rows = groups.get(id) ?? [];
    rows.push(item);
    groups.set(id, rows);
  }
  return [...groups].map(([id, rows]) => {
    const identity = identities.find(row => displaySourceId(row.source_id) === id) ?? {};
    const machine = String(identity.machine || identity.host || rows[0].machine || id);
    const osUser = String(identity.os_user || rows[0].account || "unknown");
    const total = rows.reduce((sum, row) => sum + tokens(row.total_tokens), 0);
    const label = id === CLOUD_SOURCE_ID ? CLOUD_SOURCE_LABEL : `${osUser} / ${machine}`;
    return { id, label, machine, os_user: osUser,
      tokens: total, source_ids: [id], contributions: [{ source_id: id, tokens: total }], agents: sourceAgents(rows) };
  }).sort((a, b) => Number(b.tokens) - Number(a.tokens) || String(a.id).localeCompare(String(b.id)));
}
