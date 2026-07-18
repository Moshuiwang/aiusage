# TP-V2-114 Hermetic Fact Check Tests

Version: V2
ID: TP-V2-114
Status: done
Type: implementation
Depends on: none
Parallel with: TP-V2-115

## Goal

让仓库全量 Python 测试在没有个人 `~/.codex` skill 的 GitHub Runner 上可判定通过，同时在本机
skill 存在时继续执行真实集成合同。

## Context

`tests/test_usage_fact_check_skill.py` 当前硬编码个人绝对路径，GitHub Runner 缺少该仓库外文件时
产生 9 个 error。这些测试验证个人 skill 集成，不应让仓库 CI 依赖某台 Mac 的目录结构。

## Scope

- 移除用户名硬编码，使用可配置或用户目录相对的 skill 路径。
- 外部 skill 不存在时，把整组测试明确报告为 skipped，而不是 error 或伪通过。
- 外部 skill 存在时保持现有 9 项行为断言全部执行。
- 增加仓库内合同测试，防止重新引入个人绝对路径依赖。

## Out of Scope

- 不把个人 skill 或其生产数据复制进仓库。
- 不访问生产 API、设备、凭据或原始 usage 日志。
- 不改变 fact-check 产品口径。

## Red Test

先增加“测试文件不得硬编码个人绝对路径、外部 skill 缺失时整组 skip”的合同断言；在当前实现
下必须失败。

## Implementation

1. 提供稳定的路径解析与 availability 判断。
2. 在 class 级别使用显式 skip reason，确保缺失环境依赖不表现为错误。
3. 保持 skill 存在时原有断言不变并实际运行。

## Acceptance Criteria

- GitHub Runner 不需要个人 `~/.codex` 目录即可完成全量 discovery。
- 缺失外部 skill 时显示明确 skipped 原因，不出现 9 个 error。
- 本机 skill 存在时原有 9 项测试仍执行并通过。
- 仓库不包含个人 skill 副本、凭据或原始数据。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_usage_fact_check_skill -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

## Handoff

- 汇报本机 skill 存在与缺失两种路径的判定结果。
- 证据写回 Parent Epic #32 的单一证据评论和对应 Fix Issue。
