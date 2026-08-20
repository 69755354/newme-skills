#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""视频号远程扫码：把二维码推到她手机上，她**不用坐在 Mac 前**。

为什么能行：微信「扫一扫」右上角支持**从相册选图**，所以二维码只要能到手机
相册就能扫。流程：这里截二维码 → 传腾讯云 COS → 打印一条 1 小时有效的签名链接
→ 她在手机上打开、长按存图 → 微信扫一扫 → 相册选那张图 → 确认登录。

二维码本身大约 5 分钟过期，所以脚本会**守在这里**轮询登录结果，
过期就重新出码、重新推一次（最多 3 次），登录一成功立刻落盘退出。

⛔ 不点任何发布按钮；⛔ 不往 profile 灌 cookie；只做登录这一件事。
用法：wx_login_remote.py [--rounds 3] [--minutes 6]
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "_pipeline")
PROF = os.path.expanduser("~/NewMe/profiles/weixin")
COS_CONF = os.path.expanduser("~/NewMe/.secrets/cos.json")
HOME = "https://channels.weixin.qq.com/platform"
ACCOUNT = u"Newme-Tanya"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

PROBE = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  return {text:cut(document.body.innerText).slice(0,600),
          avatars:document.querySelectorAll(
            "img[class*=avatar],[class*=avatar] img,img[src*='wx.qlogo.cn']").length};
}"""


def push_cos(path):
    u"""传 COS 并给一条 1 小时有效的签名链接（桶是私有的，不能公开读）。"""
    if not os.path.exists(COS_CONF):
        return None, u"缺 %s" % COS_CONF
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except Exception as e:
        return None, u"没装 qcloud_cos：%s" % str(e)[:60]
    c = json.load(io.open(COS_CONF, encoding="utf-8"))
    cli = CosS3Client(CosConfig(Region=c["region"], SecretId=c["secret_id"],
                                SecretKey=c["secret_key"], Scheme="https"))
    key = "login-qr/wx_%s.png" % datetime.now().strftime("%m%d_%H%M%S")
    cli.put_object(Bucket=c["bucket"], Key=key,
                   Body=io.open(path, "rb").read(), EnableMD5=False)
    url = cli.get_presigned_url(Bucket=c["bucket"], Key=key,
                                Method="GET", Expired=3600)
    return url, None


QR_BOX = r"""() => {
  // 二维码是登录 frame 里 150~400 px 见方的那个 img/canvas
  let best=null;
  document.querySelectorAll('img,canvas').forEach(e=>{
    const r=e.getBoundingClientRect();
    if(r.width<140||r.width>420) return;
    if(Math.abs(r.width-r.height)>40) return;
    if(best && best.width>r.width) return;
    best={x:r.x, y:r.y, width:r.width, height:r.height};
  });
  return best;
}"""


def shoot_qr(pg, path):
    u"""只截二维码那一块（手机相册扫图时越大越好截，整页图里的码太小容易扫不出）。

    找不到就退回整页截图 —— 宁可图糙也不能没有码。
    """
    for f in pg.frames:
        if "login.html" not in (f.url or "") and "qrconnect" not in (f.url or ""):
            continue
        try:
            box = f.evaluate(QR_BOX)
        except Exception:
            box = None
        if not box:
            continue
        # ⚠️ 坐标是**相对所在 frame** 的：如果码在嵌套 iframe（open.weixin 的
        #    qrconnect）里，必须加上那个 iframe 在页面里的偏移，否则截到别处。
        if f is not pg.main_frame:
            try:
                fb = f.frame_element().bounding_box() or {"x": 0, "y": 0}
                box["x"] += fb["x"]
                box["y"] += fb["y"]
            except Exception:
                pass
        pad = 24
        clip = {"x": max(box["x"] - pad, 0), "y": max(box["y"] - pad, 0),
                "width": box["width"] + pad * 2, "height": box["height"] + pad * 2}
        try:
            pg.screenshot(path=path, clip=clip)
            return u"只截了二维码（%dx%d）" % (int(clip["width"]), int(clip["height"]))
        except Exception:
            break
    pg.screenshot(path=path)
    return u"没定位到码，截了整页"


def logged_in(pg):
    u"""判据：**正面证据优先**（账号名 / 头像），扫码 frame 只作为反面证据的兜底。

    ⚠️ 2026-08-20 踩过：她明明扫成功了（heartbeat 立刻判定在线），这里却一直不认，
    傻等到超时。原因是「先看有没有 qrconnect frame，有就 return False」——
    登录成功后 SPA 并不会把那个 iframe 从 DOM 里摘掉，URL 一直挂着，
    于是永远 False。所以顺序必须反过来：**先找账号名/头像**。
    """
    try:
        d = pg.evaluate(PROBE)
    except Exception:
        return False
    if (ACCOUNT in d["text"]) or d["avatars"]:
        return True
    furls = " ".join((f.url or "") for f in pg.frames)
    return not (("login.html" in furls) or ("qrconnect" in furls))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3, help=u"最多出几次码")
    ap.add_argument("--minutes", type=float, default=6, help=u"每张码等多久")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])
    time.sleep(2)
    shot = os.path.join(PIPE, "wx_login_qr.png")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROF, channel="chrome", headless=False,
            no_viewport=True, user_agent=UA,
            args=["--window-position=-3000,0", "--window-size=1440,900",
                  "--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(40000)
        try:
            for rd in range(1, a.rounds + 1):
                pg.goto(HOME, wait_until="domcontentloaded")
                time.sleep(10)
                if logged_in(pg):
                    print(u"✅ 本来就还是登录态，不用扫")
                    return 0
                shoot_qr(pg, shot)
                url, err = push_cos(shot)
                print(u"\n第 %d 张二维码（约 5 分钟内有效）：" % rd)
                if url:
                    print(u"  手机上打开这条链接 → 长按存图 → 微信「扫一扫」→ "
                          u"右上角相册 → 选那张图：\n  %s" % url)
                else:
                    print(u"  ⚠️ 推到手机失败（%s），码在这张图里：%s" % (err, shot))
                t0 = time.time()
                while time.time() - t0 < a.minutes * 60:
                    time.sleep(5)
                    try:
                        if logged_in(pg):
                            # 登录一成功立刻落盘（Playwright 主动写，不靠优雅退出）
                            try:
                                ctx.storage_state(
                                    path=os.path.join(ROOT, "weixin_state.json"))
                            except Exception:
                                pass
                            print(u"\n✅ 视频号登录成功（第 %d 张码）" % rd)
                            return 0
                    except Exception:
                        pass
                print(u"  ⌛ 这张码超时了，换一张")
            print(u"\n❌ %d 张码都没扫成功" % a.rounds)
            return 2
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])


if __name__ == "__main__":
    sys.exit(main())
