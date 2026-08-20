#!/bin/bash
# 通用后台跑：_run.sh <日志名> <python 脚本> [参数...]
# ⚠️ 必须走 detach.py（os.setsid），不能只用 nohup：桥的调用一超时就会清理进程组，
#    nohup 挡不住 —— 10 遍回归的第 6 遍就是这么在中途被收走的（日志停在「表单」）。
cd "$HOME/Movies/JianyingPro/User Data/Projects/com.lveditor.draft" || exit 9
LOG="_pipeline/$1"; shift
: > "$LOG"
( python3 detach.py "$LOG" python3 -u "$@" & )
sleep 1
echo "started -> $LOG"
