#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""抖音去重：删掉 08-20 00:44 那条重复的「整面墙只留一块屏」。
同一条片子在号里出现两次会互相抢流量，留 19:30 定时那条（选项齐全）。

⚠️ 这是**破坏性**操作，所以判据卡得很死：
   - 只认同时含标题 + '00:44' + '删除作品' 的**最小**容器，且必须唯一；
   - 含 '定时' 的行一律跳过（那是要留的）；
   - 删完回读：00:44 消失且定时那条还在，否则报错。
"""
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.expanduser("~/NewMe/profiles/douyin")
MANAGE = "https://creator.douyin.com/creator-micro/content/manage"
KEY = u"整面墙只留一块屏"
STAMP = u"00:44"

FIND = r"""([key, stamp]) => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  let best=null;
  document.querySelectorAll('div,li').forEach(e=>{
    const t=cut(e.innerText);
    if(!t.includes(key)) return;
    if(!t.includes(stamp)) return;
    if(t.includes('定时')) return;              // 要留的那条，绝不碰
    if(!t.includes('删除作品')) return;
    if(best && best.len<=t.length) return;
    const del=[...e.querySelectorAll('*')].filter(x=>cut(x.innerText)==='删除作品'
      && x.children.length<2)[0];
    if(!del) return;
    const r=del.getBoundingClientRect();
    best={len:t.length, txt:t.slice(0,90),
          x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
          inView:r.top>=0&&r.bottom<=innerHeight};
  });
  return best;
}"""

CONFIRM = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const mods=[...document.querySelectorAll('[class*=modal],[role=dialog]')]
    .filter(e=>{const r=e.getBoundingClientRect();
      return r.width>200&&r.height>80&&getComputedStyle(e).display!=='none';});
  const m=mods[mods.length-1];
  if(!m) return null;
  const b=[...m.querySelectorAll('button,div,span')]
    .filter(x=>/^(确定|删除|确认删除)$/.test(cut(x.innerText)) && x.children.length<2)
    .map(x=>{const r=x.getBoundingClientRect(); return {r:r,a:r.width*r.height};})
    .filter(o=>o.r.width>30&&o.r.height>16).sort((p,q)=>p.a-q.a)[0];
  return {txt:cut(m.innerText).slice(0,120),
          btn: b?{x:Math.round(b.r.x+b.r.width/2),
                  y:Math.round(b.r.y+b.r.height/2)}:null};
}"""

# ⚠️ 别按「文字短」找行：作品描述那层本身就 <300 字但**不含日期**，
# 按它判会得出 dup=False sched=False 的假阴性（第一版就这么骗过自己）。
# 行的真特征是文字里带操作按钮（删除作品 / 修改定时）。
STATE = r"""([key, stamp]) => {
  const rows=[...document.querySelectorAll('div,li')]
    .map(e=>(e.innerText||'').replace(/\s+/g,' '))
    .filter(t=>t.includes(key) && t.length<3000
               && (t.includes('删除作品')||t.includes('修改定时')));
  return {dup: rows.some(t=>t.includes(stamp)),
          sched: rows.some(t=>t.includes('19:30')),
          n: rows.length,
          sample: (rows[rows.length-1]||'').slice(0,160)};
}"""


def wait_list(pg):
    for _ in range(25):
        time.sleep(2)
        try:
            if pg.evaluate(STATE, [KEY, STAMP])["n"]:
                return True
        except Exception:
            pass
    return False


def main():
    subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROFILE])
    time.sleep(2)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE, channel="chrome", headless=False,
            no_viewport=True,
            args=["--start-maximized",
                  "--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(25000)
        try:
            ctx.new_cdp_session(pg).send("Emulation.setTimezoneOverride",
                                         {"timezoneId": "Asia/Shanghai"})
            pg.goto(MANAGE, wait_until="domcontentloaded")
            if not wait_list(pg):
                print(u"❌ 列表没加载出来")
                return 3
            before = pg.evaluate(STATE, [KEY, STAMP])
            print(u"删之前：%s" % before)
            if not before["dup"]:
                print(u"没有 00:44 那条，不用删")
                return 0
            tgt = pg.evaluate(FIND, [KEY, STAMP])
            if not tgt:
                print(u"❌ 找不到那条的「删除作品」")
                return 4
            print(u"目标行 %r · 删除键 @(%d,%d) inView=%s"
                  % (tgt["txt"], tgt["x"], tgt["y"], tgt["inView"]))
            if not tgt["inView"]:
                print(u"❌ 删除键不在视口，不敢点")
                return 5
            pg.mouse.click(tgt["x"], tgt["y"])
            time.sleep(2)
            c = pg.evaluate(CONFIRM)
            print(u"确认框：%s" % (c["txt"] if c else None))
            if not c or not c["btn"]:
                print(u"❌ 没有确认按钮")
                return 6
            pg.mouse.click(c["btn"]["x"], c["btn"]["y"])
            time.sleep(4)
            pg.goto(MANAGE, wait_until="domcontentloaded")
            wait_list(pg)
            after = pg.evaluate(STATE, [KEY, STAMP])
            print(u"删之后：%s" % after)
            pg.screenshot(path=os.path.join(OUT, "_pipeline", "dy_dedup.png"))
            ok = (not after["dup"]) and after["sched"]
            print(u"%s 重复的没了=%s · 19:30 定时还在=%s"
                  % (u"✅" if ok else u"❌", not after["dup"], after["sched"]))
            return 0 if ok else 7
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
