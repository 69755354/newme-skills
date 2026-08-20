#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""NewMe 三平台发布统一入口 —— 唯一该用的那个。

用法：
  newme_post.py 方案.json                          # 三平台都填、都不发（回归）
  newme_post.py 方案.json --mode publish           # 三平台真发（定时 北京 19:30）
  newme_post.py 方案.json --only douyin            # 只跑一个
  newme_post.py 方案.json --times 10               # 每个平台连跑 10 遍
  newme_post.py 方案.json --video 小样.mp4          # 覆盖方案里的片子

它只做调度：把活分给三个**经过 10 遍回归**的专用脚本，一个一个来
（本机只有 8 GB，同时开两个 Chrome 会把机器打死），最后汇总一张表。

⛔ 不要再用 newme_publish.py / publish_options.py：那两个是早期通用版，
   里面的回读判据有假阳性（详见各自文件头的 DEPRECATED 说明）。

退出码：全部平台成功 0；有平台失败 = 失败个数。
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "_pipeline")

# 平台 key -> (专用脚本, 中文名, profile 目录名)
PLATS = [
    ("weixin",      "publish_weixin.py", u"视频号",  "weixin"),
    ("xiaohongshu", "publish_xhs.py",    u"小红书",  "xiaohongshu"),
    ("douyin",      "publish_douyin.py", u"抖音",    "douyin"),
]


def kill_profile(name):
    u"""⛔ 只按 user-data-dir 精确杀，绝不 pkill -f chrome（会连人正在用的浏览器一起杀）。"""
    subprocess.call(["pkill", "-TERM", "-f",
                     "user-data-dir=%s" % os.path.expanduser(
                         "~/NewMe/profiles/%s" % name)])
    time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--mode", default="fill",
                    choices=["fill", "draft", "publish"])
    ap.add_argument("--video", default="")
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("--only", default="", help=u"weixin/xiaohongshu/douyin，逗号分隔")
    a = ap.parse_args()

    plan_path = os.path.abspath(os.path.expanduser(a.plan))
    if not os.path.isfile(plan_path):
        print(u"❌ 方案不存在：%s" % plan_path)
        return 90
    plan = json.load(io.open(plan_path, encoding="utf-8"))

    only = [x.strip() for x in a.only.split(",") if x.strip()]
    todo = [p for p in PLATS
            if (not only or p[0] in only) and p[0] in plan]
    if not todo:
        print(u"❌ 方案里没有可跑的平台（有 %s）"
              % ",".join(k for k in plan if k in dict((p[0], 1) for p in PLATS)))
        return 91

    if not os.path.isdir(PIPE):
        os.makedirs(PIPE)
    print(u"方案 %s · 模式 %s · 平台 %s · 每个跑 %d 遍"
          % (os.path.basename(plan_path), a.mode,
             "/".join(p[2] for p in todo), a.times))
    if a.mode == "draft":
        print(u"⚠️ draft 只有视频号支持，其他平台按 fill 跑")

    res = []
    for key, script, cn, prof in todo:
        mode = a.mode
        if mode == "draft" and key != "weixin":
            mode = "fill"
        log = os.path.join(PIPE, "post_%s.log" % key)
        cmd = [sys.executable, "-u", os.path.join(ROOT, script), plan_path,
               "--mode", mode, "--times", str(a.times)]
        if a.video:
            cmd += ["--video", a.video]
        print(u"\n══════ %s ══════" % cn)
        kill_profile(prof)                     # 一次只开一个浏览器
        t0 = time.time()
        with io.open(log, "w", encoding="utf-8") as f:
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=f,
                                 stderr=subprocess.STDOUT)
            rc = p.wait()
        dt = int(time.time() - t0)
        tail = u""
        try:
            lines = [l.rstrip() for l in
                     io.open(log, encoding="utf-8").read().splitlines() if l.strip()]
            tail = u" / ".join(lines[-3:])
        except Exception:
            pass
        res.append((cn, rc, dt, log, tail))
        print(u"%s %s 退出码 %d · %d 秒 · 日志 %s"
              % (u"✅" if rc == 0 else u"❌", cn, rc, dt,
                 os.path.relpath(log, ROOT)))
        if tail:
            print(u"   %s" % tail[:300])

    bad = [r for r in res if r[1] != 0]
    print(u"\n────── 汇总 ──────")
    for cn, rc, dt, log, tail in res:
        print(u"  %s %s（%d 秒）" % (u"✅" if rc == 0 else u"❌", cn, dt))
    print(u"%s %d/%d 个平台通过"
          % (u"✅" if not bad else u"❌", len(res) - len(bad), len(res)))
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())
