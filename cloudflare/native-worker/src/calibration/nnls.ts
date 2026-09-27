/**
 * #183-a：非负最小二乘（NNLS）。
 *
 * 族数 ≤6，样本数最多几百条区间，用不上完整 Lawson–Hanson——用坐标下降（投影梯度的
 * 一种）在正规方程 `A x = b`（`A = XᵀWX`，`b = XᵀWy`）上迭代，每一步把新解投影回 `x ≥ 0`。
 * 这是加权最小二乘的标准做法：每次只优化一个坐标，其余固定，直到收敛或到达迭代上限。
 * 对角线加一点岭回归（ridge）防止某个族全程为零导致对角线本身为零、除零。
 */

export interface NnlsOptions {
  ridge?: number;
  maxIterations?: number;
  tolerance?: number;
}

/**
 * @param rows 每行是一个样本的特征向量（长度 = keys 数）
 * @param targets 每个样本的目标值（ΔU）
 * @param weights 每个样本的权重（近期加权等），默认全 1
 * @returns 每个特征对应的非负系数
 */
export function nonNegativeLeastSquares(
  rows: number[][],
  targets: number[],
  weights?: number[],
  options: NnlsOptions = {},
): number[] {
  const n = rows.length > 0 ? rows[0].length : 0;
  const w = weights ?? rows.map(() => 1);
  const ridge = options.ridge ?? 1e-6;
  const maxIterations = options.maxIterations ?? 4000;
  const tolerance = options.tolerance ?? 1e-12;

  const A: number[][] = Array.from({ length: n }, () => new Array(n).fill(0));
  const b: number[] = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      let sum = 0;
      for (let s = 0; s < rows.length; s++) sum += w[s] * rows[s][i] * rows[s][j];
      A[i][j] = sum;
    }
    let sum = 0;
    for (let s = 0; s < rows.length; s++) sum += w[s] * rows[s][i] * targets[s];
    b[i] = sum;
  }
  for (let i = 0; i < n; i++) A[i][i] += ridge * (A[i][i] + 1e-9) + 1e-12;

  const x = new Array(n).fill(0);
  for (let iter = 0; iter < maxIterations; iter++) {
    let maxDelta = 0;
    for (let i = 0; i < n; i++) {
      if (A[i][i] <= 0) continue;
      let dot = 0;
      for (let j = 0; j < n; j++) dot += A[i][j] * x[j];
      const gradient = b[i] - dot + A[i][i] * x[i];
      const next = Math.max(0, gradient / A[i][i]);
      maxDelta = Math.max(maxDelta, Math.abs(next - x[i]));
      x[i] = next;
    }
    if (maxDelta < tolerance) break;
  }
  return x;
}

/** 用系数向量预测某一行样本的目标值（Σ feature_i × coef_i）。 */
export function predictRow(row: number[], coef: number[]): number {
  let sum = 0;
  for (let i = 0; i < row.length; i++) sum += row[i] * coef[i];
  return sum;
}
