/** #183-a：非负最小二乘（坐标下降版）的基本正确性。 */
import { describe, expect, it } from "vitest";
import { nonNegativeLeastSquares, predictRow } from "../src/calibration/nnls";

describe("nonNegativeLeastSquares", () => {
  it("单特征精确解：y = 3x 时系数应恢复到 3 附近", () => {
    const rows = [[1], [2], [3], [4]];
    const targets = [3, 6, 9, 12];
    const coef = nonNegativeLeastSquares(rows, targets);
    expect(coef[0]).toBeCloseTo(3, 3);
  });

  it("系数永远非负：即使数据暗示负相关，也不会解出负系数", () => {
    // y 随 x 增大而减小，最小二乘的无约束解会是负数，NNLS 必须投影到 0。
    const rows = [[1], [2], [3], [4]];
    const targets = [10, 8, 6, 4];
    const coef = nonNegativeLeastSquares(rows, targets);
    expect(coef[0]).toBeGreaterThanOrEqual(0);
  });

  it("两特征能分别恢复出接近真实的系数（无共线性时）", () => {
    // y = 2*x1 + 5*x2，两组正交设计点。
    const rows = [
      [1, 0],
      [0, 1],
      [2, 0],
      [0, 2],
    ];
    const targets = [2, 5, 4, 10];
    const coef = nonNegativeLeastSquares(rows, targets);
    expect(coef[0]).toBeCloseTo(2, 2);
    expect(coef[1]).toBeCloseTo(5, 2);
  });

  it("权重更高的样本对拟合结果影响更大", () => {
    const rows = [[1], [1]];
    const withoutWeight = nonNegativeLeastSquares(rows, [10, 2]);
    const withWeight = nonNegativeLeastSquares(rows, [10, 2], [10, 1]);
    // 加权后结果应更靠近权重更高的那条样本（目标值 10）。
    expect(withWeight[0]).toBeGreaterThan(withoutWeight[0]);
  });
});

describe("predictRow", () => {
  it("独立复算：Σ feature_i × coef_i", () => {
    expect(predictRow([2, 3, 4], [1, 0, 0.5])).toBeCloseTo(2 * 1 + 3 * 0 + 4 * 0.5, 6);
  });
});
