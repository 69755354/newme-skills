#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""视频号会话心跳 —— 目的只有一个：**让她别再反复扫码**。

调研结论（2026-08-20 实测，不是猜的）：
  · 视频号后台**只有扫码一条登录路径**，没有密码、没有「7天免登录」勾选、
    登录页上也没有任何「保持登录」选项（_wx_login_probe.py dump 过全文）。
  · profile 里 channels.weixin.qq.com 只有 2 个 cookie（sessionid / wxuin），
    **有效期到 2027-09-23** —— 所以掉线不是 cookie 过期，是**服务端把会话作废了**。
  · 上次扫码 08-19 16:46，08-20 18:xx 就已作废 ≈ 26 小时；期间跑过 10 遍回归，
    cookie 的 last_update 一直没变 —— 说明那些访问没有让服务端续期。
  · 对比：小红书 cookie 还有 363 天、抖音 58 天。**只有视频号这一个平台需要人操作。**

于是能动的只有两个变量，这个脚本把两个都占上：
  1. **频率**：每 20 分钟做一次轻量已登录访问。如果微信的会话是「滑动过期」
     （多数腾讯后台是），持续活动就能无限续期 → 一次扫码永久有效。
  2. **指纹**：⛔ 绝不用 headless（Chrome 的 headless UA 里带 HeadlessChrome，
     微信这种风控站完全可能因此判成异地新设备而作废会话）。这里用
     **屏幕外真窗口**（x=-3000，不抢焦点、看不见，等于最小化）+ 真 UA。

还有第三个变量不在脚本里，但同样重要：**用定时发布摊薄扫码**——
一次登录能把未来 N 天的视频号内容全排进定时队列，扫码次数除以 N。

判据（不许假绿）：
  在线 = frame URL 里**没有** login.html / qrconnect，**且**页面上有账号名或头像。
  只要出现扫码 frame 就判掉线（顶层文字「登录视频号助手」是常驻营销文案，
  已登录时也在，拿它当判据会永远误报 —— 这个坑踩过）。

⛔ 不点任何发布/登录按钮，不刷新二维码，不写 cookie。
输出：~/NewMe/logs/wx_heartbeat.jsonl（每次一行）+ 掉线时截图。
退出码：0 在线 · 2 掉线（需人工扫码）· 3 这次没测（内存不够/有别的浏览器在跑/MCP_OFF）
"""
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "_pipeline")
LOGD = os.path.expanduser("~/NewMe/logs")
JSONL = os.path.join(LOGD, "wx_heartbeat.jsonl")
PROF = os.path.expanduser("~/NewMe/profiles/weixin")
HOME = "https://channels.weixin.qq.com/platform"
LIST = "https://channels.weixin.qq.com/platform/post/list"
ACCOUNT = u"Newme-Tanya"    # 页面上出现它 = 已登录（弱一点的证据是头像）
# 单标签页的轻量访问，不用留 700 MB 那么宽（留宽了会天天跳过，等于没保活）
MIN_FREE_MB = int(os.environ.get("NEWME_MIN_FREE_MB", "420"))

# 真 Chrome 的 UA（去掉 Headless 字样）；启动时也会拿真 channel=chrome
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

PROBE = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const t=cut(document.body.innerText);
  const av=document.querySelectorAll(
      "img[class*=avatar],[class*=avatar] img,img[src*='wx.qlogo.cn']").length;
  return {text:t.slice(0,600), avatars:av, ua:navigator.userAgent};
}"""


def free_mb():
    try:
        out = subprocess.check_output(["vm_stat"]).decode()
        page = 4096
        d = {}
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                d[k.strip()] = v.strip().rstrip(".")
        free = int(d.get("Pages free", 0)) + int(d.get("Pages inactive", 0))
        return free * page // (1024 * 1024)
    except Exception:
        return 9999


def other_automation_running():
    u"""别的自动化在跑就让路（8 GB 机器不许双开）。判断实现在 profile_guard 一份。

    ⚠️ 老版本只看「别的 profile 有没有 Chrome」，漏了一大类：发布脚本**刚起来还没开
    浏览器**、或者正在 ffmpeg/上传阶段时，看起来没人在跑 —— 心跳就大摇大摆开一个
    Chrome，然后那遍回归被内存拖死。所以还要看有没有 publish_*.py 进程。
    """
    import profile_guard
    mine = os.path.basename(PROF)
    others = [k for k in profile_guard.running() if k != mine]
    return (others + profile_guard.publish_running()) or False


def rec(d):
    d["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not os.path.isdir(LOGD):
        os.makedirs(LOGD)
    with io.open(JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + u"\n")
    return d


def hours_since_last_online():
    u"""上一次在线距今多久 —— 这是我们唯一能拿到的「会话活了多久」的度量。"""
    if not os.path.exists(JSONL):
        return None
    last = None
    for line in io.open(JSONL, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("ok"):
            last = r.get("ts")
    if not last:
        return None
    try:
        dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        return round((datetime.now() - dt).total_seconds() / 3600.0, 2)
    except Exception:
        return None


def main():
    if os.path.exists(os.path.expanduser("~/NewMe/MCP_OFF")):
        print(u"⏭ MCP_OFF 在，这次不测")
        return 3
    fm = free_mb()
    if fm < MIN_FREE_MB:
        rec({"platform": "weixin", "skipped": u"内存只剩 %d MB" % fm, "ok": None})
        print(u"⏭ 可用内存只有 %d MB（阈值 %d），这次不测" % (fm, MIN_FREE_MB))
        return 3
    if other_automation_running():
        rec({"platform": "weixin", "skipped": u"别的平台浏览器在跑", "ok": None})
        print(u"⏭ 有别的自动化浏览器在跑，让路")
        return 3

    from playwright.sync_api import sync_playwright
    subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])
    time.sleep(2)
    d = {"platform": "weixin", "ok": False, "free_mb": fm}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROF, channel="chrome", headless=False,
            no_viewport=True, user_agent=UA,
            args=["--window-position=-3000,0", "--window-size=1440,900",
                  "--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(30000)
        try:
            pg.goto(HOME, wait_until="domcontentloaded")
            # ⚠️ 不能只等 8 秒就下结论：二维码 frame 有时十几秒才挂上，
            #    页面还会出现「加载失败，点击重试」。等到**有结论**为止，
            #    否则会得到「既没扫码 frame 也没账号名」这种什么都没测出来的空结果。
            qr, info, strong = False, {"text": "", "avatars": 0, "ua": ""}, []
            for _ in range(12):
                time.sleep(3)
                furls = " ".join((f.url or "") for f in pg.frames)
                qr = ("login.html" in furls) or ("qrconnect" in furls)
                try:
                    info = pg.evaluate(PROBE)
                except Exception as e:
                    d["probe_err"] = str(e)[:80]
                    continue
                strong = []
                if ACCOUNT in info["text"]:
                    strong.append(u"账号名")
                if info["avatars"]:
                    strong.append(u"头像×%d" % info["avatars"])
                if qr or strong:
                    break
            d["headless_ua"] = "Headless" in (info.get("ua") or "")
            d["ok"] = (not qr) and bool(strong)
            d["reason"] = (u"挂着扫码 frame" if qr else
                           (u"命中 " + u"/".join(strong) if strong
                            else u"既没扫码 frame 也没账号名/头像"))
            if d["ok"]:
                # 轻量活动：打开作品列表 + 滚一下，让服务端看到"这个会话在用"
                try:
                    pg.goto(LIST, wait_until="domcontentloaded")
                    time.sleep(6)
                    pg.mouse.wheel(0, 1200)
                    time.sleep(2)
                    d["activity"] = u"打开作品列表并滚动"
                except Exception as e:
                    d["activity"] = u"活动失败：%s" % str(e)[:60]
            else:
                try:
                    pg.screenshot(path=os.path.join(PIPE, "wx_heartbeat_offline.png"))
                except Exception:
                    pass
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])
    d["hours_since_last_ok"] = hours_since_last_online()
    rec(d)
    print(u"%s 视频号 %s（距上次在线 %s 小时·UA带Headless=%s）"
          % (u"✅" if d["ok"] else u"❌", d["reason"],
             d.get("hours_since_last_ok"), d.get("headless_ua")))
    return 0 if d["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
