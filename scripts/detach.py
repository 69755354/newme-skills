#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真·脱离启动器：os.setsid() 之后再 exec 目标命令。

为什么要它（2026-08-19 第二次被同一件事咬）：
桥的每次 bash 调用最长 120 秒。`nohup ... & disown` **挡不住**调用超时时的
进程组清理 —— 20:13 启动的抖音发布跑到第 75 秒，我这边一个 sleep 100 的
调用超时，整个发布进程连浏览器一起被收走了，一次 72 MB 上传白费。
setsid 会新建会话，进程彻底不在桥那条进程组里，怎么超时都杀不到。

用法: detach.py <日志路径> <命令> [参数...]
"""
import os
import sys

if len(sys.argv) < 3:
    sys.exit(__doc__)
log, cmd, args = sys.argv[1], sys.argv[2], sys.argv[2:]
os.setsid()
f = open(os.path.expanduser(log), "ab", 0)
os.dup2(f.fileno(), 1)
os.dup2(f.fileno(), 2)
os.close(0)
os.open(os.devnull, os.O_RDONLY)
os.execvp(cmd, args)
