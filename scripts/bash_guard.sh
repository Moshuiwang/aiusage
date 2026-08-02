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

exit 0
