#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""小红书草稿箱清理：把 fill 回归留下的草稿删干净。

草稿不在「笔记管理」里（那页只有已发布/审核中/未通过），入口在发布页顶部的
「草稿箱 N」。--probe 只 dump 结构不删，不带就真删。

判据：删之前草稿数 n0 > 0；每删一条 n 必须真的 -1（否则说明点空了，立刻停）；
收尾 n == 0 或降到 --keep 指定条数。
"""
import io
import json
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(OUT, "_pipeline")
PROFILE = os.path.expanduser("~/NewMe/profiles/xiaohongshu")
HOME = "https://creator.rednote.com/publish/publish"

# 草稿箱入口：文字形如「草稿箱 12」/「草稿箱(12)」
ENTRY = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const c=[...document.querySelectorAll('div,span,button,a')]
    .filter(x=>/^草稿箱\s*[（(]?\d*[)）]?$/.test(cut(x.innerText))
               && x.children.length<3)
    .map(x=>{const r=x.getBoundingClientRect();
      return {t:cut(x.innerText), a:r.width*r.height,
              x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
              w:r.width, h:r.height};})
    .filter(o=>o.w>20&&o.h>10).sort((p,q)=>p.a-q.a)[0];
  return c||null;
}"""

# 草稿列表状态。
# ⚠️ 草稿条数不能按「删除」按钮个数算：确认气泡里也有一个「删除」，会多算一条。
#    真计数 = 文字里「保存于YYYY-MM-DD」出现几次。
# ⚠️ 要点的那个「删除」也必须排掉气泡里那个（祖先文字含「删除后不可找回」的不要）。
LIST = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const mods=[...document.querySelectorAll('[class*=modal],[class*=drawer],[role=dialog]')]
    .filter(e=>{const r=e.getBoundingClientRect();
      return r.width>300&&r.height>150&&getComputedStyle(e).display!=='none';});
  const scope=mods.length?mods[mods.length-1]:document.body;
  const all=cut(scope.innerText);
  const n=(all.match(/保存于\d{4}-\d{2}-\d{2}/g)||[]).length;
  const inPop=x=>{let p=x;for(let i=0;i<6&&p;i++,p=p.parentElement){
      if(/不可找回/.test(p.innerText||'')) return true;} return false;};
  const dels=[...scope.querySelectorAll('button,span,div,a')]
    .filter(x=>/^删除$/.test(cut(x.innerText)) && x.children.length<2 && !inPop(x))
    .map(x=>{const r=x.getBoundingClientRect();
      return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
              w:r.width, h:r.height, top:r.top,
              inView:r.top>=0&&r.bottom<=innerHeight};})
    .filter(o=>o.w>20&&o.h>10)
    .sort((p,q)=>p.top-q.top);
  return {n:n, nBtn:dels.length, first:dels[0]||null,
          inModal:mods.length>0,
          txt:all.slice(0,400)};
}"""

# ⚠️ 确认不是 modal 也不是 dialog，是个 popover 气泡：「草稿删除后不可找回 / 取消 / 删除」。
#    按 [class*=modal],[role=dialog] 找永远找不到 → 点了没反应，草稿数不变。
CONFIRM = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  let pop=null;
  document.querySelectorAll('div,section,span').forEach(e=>{
    const t=cut(e.innerText);
    if(!/不可找回/.test(t)) return;
    if(t.length>80) return;
    if(!/取消/.test(t)) return;      // 必须是带按钮的那层，只有提示文字的那层没有「取消」
    if(pop && cut(pop.innerText).length<=t.length) return;
    pop=e;
  });
  if(!pop) return null;
  const b=[...pop.querySelectorAll('button,span,div')]
    .filter(x=>/^(删除|确定|确认)$/.test(cut(x.innerText)) && x.children.length<2)
    .map(x=>{const r=x.getBoundingClientRect();
      return {r:r, a:r.width*r.height};})
    .filter(o=>o.r.width>28&&o.r.height>14).sort((p,q)=>p.a-q.a)[0];
  return {txt:cut(pop.innerText).slice(0,140),
          btn: b?{x:Math.round(b.r.x+b.r.width/2),
                  y:Math.round(b.r.y+b.r.height/2)}:null};
}"""


def open_box(pg):
    pg.goto(HOME, wait_until="domcontentloaded")
    for _ in range(15):
        time.sleep(2)
        e = pg.evaluate(ENTRY)
        if e:
            pg.mouse.click(e["x"], e["y"])
            time.sleep(3)
            return e["t"]
    return None


def main():
    probe = "--probe" in sys.argv
    keep = 0
    if "--keep" in sys.argv:
        keep = int(sys.argv[sys.argv.index("--keep") + 1])
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
            tab = open_box(pg)
            if not tab:
                print(u"❌ 找不到「草稿箱」入口")
                pg.screenshot(path=os.path.join(PIPE, "xhs_box_fail.png"))
                return 3
            st = pg.evaluate(LIST)
            print(u"入口 %r · 草稿里「删除」键 %d 个 · 在弹层=%s"
                  % (tab, st["n"], st["inModal"]))
            pg.screenshot(path=os.path.join(PIPE, "xhs_box.png"))
            if probe:
                with io.open(os.path.join(PIPE, "xhs_box.json"), "w",
                             encoding="utf-8") as f:
                    f.write(json.dumps(st, ensure_ascii=False, indent=1))
                print(st["txt"][:400])
                return 0
            n0 = st["n"]
            if n0 <= keep:
                print(u"✅ 草稿 %d 条 ≤ 保留 %d 条，不用删" % (n0, keep))
                return 0
            n = n0
            while n > keep:
                st = pg.evaluate(LIST)
                if st["n"] != n:
                    n = st["n"]
                    if n <= keep:
                        break
                tgt = st["first"]
                if not tgt:
                    print(u"❌ 还剩 %d 条但读不到删除键" % n)
                    return 4
                if not tgt["inView"]:
                    pg.mouse.wheel(0, -400)
                    time.sleep(1)
                    st = pg.evaluate(LIST)
                    tgt = st["first"]
                    if not tgt or not tgt["inView"]:
                        print(u"❌ 删除键不在视口，不敢点")
                        return 5
                pg.mouse.click(tgt["x"], tgt["y"])
                time.sleep(2)
                c = pg.evaluate(CONFIRM)
                if not c or not c["btn"]:
                    print(u"❌ 没弹「删除后不可找回」确认气泡：%s" % (c or {}))
                    pg.screenshot(path=os.path.join(PIPE, "xhs_box_stuck.png"))
                    return 6
                pg.mouse.click(c["btn"]["x"], c["btn"]["y"])
                time.sleep(3)
                after = pg.evaluate(LIST)["n"]
                print(u"  删掉一条：%d → %d%s"
                      % (n, after, u"" if after < n else u"（没减少！）"))
                if after >= n:
                    print(u"❌ 点了没减少，停手（判据失效）")
                    pg.screenshot(path=os.path.join(PIPE, "xhs_box_stuck.png"))
                    return 6
                n = after
            print(u"✅ 草稿从 %d 条清到 %d 条" % (n0, n))
            pg.screenshot(path=os.path.join(PIPE, "xhs_box_done.png"))
            return 0
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
