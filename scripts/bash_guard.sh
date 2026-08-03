#!/usr/bin/env bash
# Claude Code PreToolUse(Bash) 门禁：只拦 #68 里重复踩过 3 次以上的两种手法。
# 判据故意收窄——这是给自己人用的小项目，宁可漏拦也不要误伤日常命令。
#
# 退出码语义：0 = 放行；2 = 拦截，stderr 回传给 Claude 作为替代做法提示。
set -uo pipefail

# stdin 是 hook 的 JSON 输入；解析失败一律放行，不能让门禁本身卡住工作
CMD="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)" || exit 0
[ -z "$CMD" ] && exit 0

# 1) pkill -f：按命令行关键字杀进程，历史上三次把自己杀掉（#68 第二节第 2 条）
# 锚定到命令位置（行首或 ;&|( 之后），否则提交信息/注释里「提及」这个词也会被误拦
if printf '%s' "$CMD" | grep -qE '(^|[;&|(])[[:space:]]*pkill[[:space:]][^|;&]*-f'; then
  {
    echo "【bash_guard 拦截】pkill -f 按命令行关键字匹配，会把自己或无关进程一起杀掉（#68 三次记录）。"
    echo "改用：fuser -k <port>/tcp 或按 PID kill。杀完必须回读确认（再查一次进程/端口），"
    echo "父进程链没清干净就按 PID 逐个 kill -TERM → kill -KILL。"
  } >&2
  exit 2
fi

# 2) until/while + pgrep 等待循环：pgrep -f 会匹配到循环自身，条件永真（#68 七个僵尸循环）
if printf '%s' "$CMD" | grep -qE '(^|[;&|(])[[:space:]]*(until|while)\b.*\bpgrep\b'; then
  {
    echo "【bash_guard 拦截】用 pgrep 做等待条件的循环会匹配到自身，条件永真、永不退出（#68 留下过 7 个僵尸循环）。"
    echo "等待判据只用：文件状态 / 端口 / 退出码，并写成 for i in \$(seq 1 N) 有限重试。"
    echo "更省事的做法：长任务用 run_in_background 跑，结束时会自动唤醒，根本不需要手写轮询。"
  } >&2
  exit 2
fi

# 3) 裸 gh pr merge：免费私有仓库无服务端 branch protection，「CI 全绿才能合并」的
# 强制性由 scripts/merge_pr.sh 承担（PM 2026-08-03 决策 A 方案）。锚定到命令位置，
# 提及该词组的文本（echo / 提交信息 / Issue 评论）不拦；merge_pr.sh 内部的 gh 调用
# 不经过本 hook（hook 只扫 Bash 工具的命令文本），不会拦到唯一入口自己。
if printf '%s' "$CMD" | grep -qE '(^|[;&|(])[[:space:]]*gh[[:space:]]+pr[[:space:]]+merge\b'; then
  {
    echo "【bash_guard 拦截】裸 gh pr merge 可以在 CI 红着的时候合并成功——本仓库没有服务端 branch protection。"
    echo "改用唯一入口：scripts/merge_pr.sh <PR号> [--merge --delete-branch 等参数]"
    echo "它会先核对四个必需 check 全部 SUCCESS 再执行合并，红/缺席/进行中都会拒绝。"
  } >&2
  exit 2
fi

exit 0
