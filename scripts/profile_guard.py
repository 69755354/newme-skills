#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""Chrome profile 的开场/收尾守卫 —— 三个发布脚本共用**这一份**。

为什么要有它（2026-08-21 被打出来的）
------------------------------------
`ctx.close()` **不保证浏览器进程真的死**。publish_weixin.py ×10 跑完退出后，
它那个 `user-data-dir=~/NewMe/profiles/weixin` 的 Chrome 在后台活了 14 分钟；
接着跑的小红书 ×10 就是被这个「第二个 Chrome」拖死的：
  · 第一次：第 1 遍全绿，第 2 遍打字打到一半 `TargetClosedError`（浏览器被系统杀）
    → 后面 8 遍连带全红，日志里像是脚本坏了，其实是内存。
  · 第二次：上传卡了 6 分钟没动（900 秒超时都没到），机器在疯狂换页。
这台机器只有 8 GB、swap 常年 7 GB —— **同时两个 Chrome 就是这个后果**。
所以每个脚本必须：开跑前清掉自己 profile 的残留 + 发现别的平台在跑就**停手**，
收尾时**再确认杀掉自己**（不能只靠 ctx.close()）。

⛔ 铁律：只按 `user-data-dir=<自己那个 profile>` 精确杀。
   `pkill -f chrome` 会连用户日常浏览器一起杀掉 —— 永远不许出现。
   selftest 里有阴性对照盯着这条（模式里出现裸 chrome 就红）。

用法（三个 publish_*.py 各两行）：
    import profile_guard
    profile_guard.solo(PROFILE)        # 开跑前：清残留；别人在跑就抛 BusyError
    ...
    finally:
        profile_guard.kill(PROFILE)    # 收尾：确认这个 profile 的 Chrome 真死了

自检：`python3 profile_guard.py --selftest`（含真起一个假进程的阳性对照）
"""
import os
import re
import subprocess
import sys
import time

PROFILES = os.path.expanduser("~/NewMe/profiles")


class BusyError(RuntimeError):
    u"""别的平台的自动化 Chrome 正在跑 —— 8 GB 机器不许双开。"""


def pattern(profile):
    u"""精确到 profile 的 pkill 模式。⛔ 绝不能退化成裸 'chrome'。"""
    # 只允许 ~/NewMe/profiles/<平台> 这一种形状：空串会被 abspath 变成 cwd、
    # 相对路径会拼出别人的目录，都可能扩大杀伤面 —— 一律拒。
    p = os.path.abspath(os.path.expanduser(profile)).rstrip("/")
    if not p.startswith(PROFILES + os.sep) or os.path.basename(p) == "":
        raise ValueError(u"profile 路径不对：%r（只收 %s/<平台>，别的会杀掉一大片）"
                         % (profile, PROFILES))
    return "user-data-dir=%s" % p


def running():
    u"""现在有哪些 profile 的自动化 Chrome 活着 → {profile 名: 进程数}。"""
    try:
        ps = subprocess.check_output(["ps", "-axww", "-o", "command"])
    except Exception:
        return {}
    ps = ps.decode("utf-8", "ignore")
    out = {}
    for m in re.finditer(r"user-data-dir=%s/([^/\s]+)" % re.escape(PROFILES), ps):
        out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


PUBLISH_SCRIPTS = ("publish_weixin.py", "publish_xhs.py", "publish_douyin.py",
                   "newme_post.py", "stats_pull.py")


def publish_running():
    u"""发布/回归/回读脚本在跑吗 —— 后台任务（心跳、保活）必须给它们让路，
    否则心跳那个 Chrome 就是「第二个 Chrome」，直接把正在跑的那遍拖死。

    ⚠️ 判据不能是「ps 输出里出现过这个文件名」：那样
    `python3 -m py_compile publish_xhs.py`、`tail publish_xhs.py`、甚至这条命令自己
    都会命中（第一版就是这么假阳性的）。真判据 = 有个 **python 进程**把这个脚本
    当**参数**在跑，且不是 py_compile / -c 里顺口提到。
    ⚠️ 剩下的边角（某条 shell 命令恰好把文件名当独立参数）会判成「在跑」——
    这个方向是**安全的**：心跳多让一次路没损失，漏判才会把正在跑的那遍拖死。
    """
    try:
        out = subprocess.check_output(["ps", "-axww", "-o", "command"])
    except Exception:
        return []
    hit = []
    for line in out.decode("utf-8", "ignore").splitlines():
        args = line.split()
        if not args or "python" not in os.path.basename(args[0]).lower():
            continue
        if "py_compile" in line or "pyflakes" in line:
            continue
        rest = args[1:]
        if "-c" in rest:          # python3 -c "...里面提到文件名..." 不算在跑
            rest = rest[:rest.index("-c")]
        for s in PUBLISH_SCRIPTS:
            if s in rest or any(a.endswith("/" + s) for a in rest):
                if s not in hit:
                    hit.append(s)
    return hit


def kill(profile, wait=2.0):
    u"""杀掉这个 profile 的 Chrome（收尾必调；ctx.close() 之后也要再来一遍）。"""
    subprocess.call(["pkill", "-TERM", "-f", pattern(profile)])
    time.sleep(wait)
    name = os.path.basename(os.path.abspath(os.path.expanduser(profile)))
    left = running().get(name, 0)
    if left:                      # TERM 没走干净再补一刀，还是只按这个 profile
        subprocess.call(["pkill", "-KILL", "-f", pattern(profile)])
        time.sleep(1.0)
        left = running().get(name, 0)
    return left == 0


def solo(profile, allow_others=False):
    u"""开跑前：清掉自己的残留；别的平台还在跑就抛 BusyError（⛔ 不硬上）。"""
    name = os.path.basename(os.path.abspath(os.path.expanduser(profile)))
    others = dict((k, v) for k, v in running().items() if k != name)
    if others and not allow_others:
        raise BusyError(
            u"%s 的 Chrome 还在跑（%s）—— 8 GB 机器同时两个 Chrome 会把这次跑挂掉"
            u"（实测：上传卡死 6 分钟 / 浏览器被系统杀）。先等它跑完，"
            u"或 pkill -TERM -f \"user-data-dir=%s/<平台>\"。"
            % (u"、".join(others), others, PROFILES))
    kill(profile)
    return True


# ── 自检 ──────────────────────────────────────────────────────────
def _selftest():
    bad = []

    def ck(name, cond, extra=""):
        print(u"  %s %s %s" % (u"✅" if cond else u"❌", name, extra if not cond else ""))
        if not cond:
            bad.append(name)

    print(u"── 1. 阴性对照：模式必须精确到 profile，绝不能是裸 chrome ──")
    pat = pattern(os.path.join(PROFILES, "weixin"))
    ck(u"模式含完整 profile 路径", pat.endswith("/NewMe/profiles/weixin"), pat)
    ck(u"模式里没有裸 chrome", "chrome" not in pat.lower(), pat)
    for bad_p in (PROFILES, "/", ""):
        try:
            pattern(bad_p)
            ck(u"%r 应该被拒" % bad_p, False)
        except ValueError:
            ck(u"%r 被拒了（阴性对照命中）" % bad_p, True)

    print(u"── 2. 阳性对照：真起一个挂着假 profile 的进程，必须被认出来 ──")
    fake = os.path.join(PROFILES, "__selftest_fake")
    ck(u"开跑前它不在", "__selftest_fake" not in running())
    p = subprocess.Popen(["/bin/sh", "-c",
                          "exec -a 'fake-chrome --user-data-dir=%s' sleep 30" % fake])
    time.sleep(1.5)
    seen = running()
    ck(u"running() 认出了它", seen.get("__selftest_fake", 0) >= 1, seen)
    print(u"── 3. solo() 看见别人在跑必须抛 BusyError（不许硬上）──")
    try:
        solo(os.path.join(PROFILES, "weixin"))
        ck(u"solo 应该抛 BusyError", False)
    except BusyError as e:
        ck(u"solo 抛了 BusyError（阴性对照命中：%s）" % str(e)[:40], True)
    ck(u"kill() 能把它杀干净", kill(fake))
    p.wait()
    ck(u"杀完 running() 里没有它", "__selftest_fake" not in running(), running())
    print(u"── 4. publish_running()：真起一个叫 publish_xhs.py 的进程要被认出来 ──")
    ck(u"现在没有发布脚本在跑", publish_running() == [], publish_running())
    q = subprocess.Popen(["/bin/sh", "-c",
                          "exec -a 'python3 publish_xhs.py fake' sleep 20"])
    time.sleep(1.5)
    ck(u"认出了 publish_xhs.py", "publish_xhs.py" in publish_running(),
       publish_running())
    q.terminate()
    q.wait()
    time.sleep(0.5)
    ck(u"它退了就不再报", "publish_xhs.py" not in publish_running())

    print(u"── 5. 空场时 solo() 必须放行（不然阴性全是白给）──")
    ck(u"没人跑的时候 solo 通过", solo(os.path.join(PROFILES, "__selftest_none")))

    print(u"\n%s profile_guard selftest %s"
          % (u"✅" if not bad else u"❌",
             u"全绿" if not bad else u"红了 %d 条：%s" % (len(bad), bad)))
    return 0 if not bad else 2


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
    print(u"现在活着的 profile Chrome：%s" % (running() or u"无"))
