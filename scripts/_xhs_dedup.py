#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""小红书去重：号里同一条片子出现了两次 —— 08-19 23:55 已发布那条 +
08-20 19:30 定时那条。留定时那条（选项齐全），删已发布那条。

--probe 只看结构。判据同抖音：目标行必须唯一、必须含时间戳且不含「定时发布」，
删完回读：23:55 那条消失且 19:30 定时那条还在。
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
MANAGE = "https://creator.rednote.com/new/note-manager"
KEY = u"墙上只留了一块屏"
STAMP = u"2026-08-19 23:55"
KEEP = u"19:30"

# 行的真特征：含标题 + 含日期时间；操作键（删除/更多）可能藏在 hover 里
ROWS = r"""([key]) => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const out=[];
  document.querySelectorAll('div,li,tr').forEach(e=>{
    const t=cut(e.innerText);
    if(!t.includes(key)) return;
    if(t.length>300) return;
    if(!/\d{4}-\d{2}-\d{2}/.test(t)) return;
    const r=e.getBoundingClientRect();
    if(r.height<40||r.width<300) return;
    out.push({txt:t.slice(0,160), len:t.length,
              x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
              w:Math.round(r.width), h:Math.round(r.height),
              inView:r.top>=0&&r.bottom<=innerHeight});
  });
  return out;
}"""

# ⚠️ 操作键没有文字：hover 才出现，是行右上角四个 svg 图标
#    （合作 / 置顶 / 编辑 / 垃圾桶），垃圾桶是**最右**那个。
#    按文字找「删除」永远是空数组 —— 第一版就这么以为没入口。
ACTIONS = r"""([key, stamp]) => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  let row=null;
  document.querySelectorAll('div,li').forEach(e=>{
    const t=cut(e.innerText);
    if(!t.includes(key) || !t.includes(stamp)) return;
    if(t.includes('定时发布')) return;
    const r=e.getBoundingClientRect();
    if(r.height<60||r.width<300) return;
    if(row && cut(row.innerText).length<=t.length) return;
    row=e;
  });
  if(!row) return {row:null, icons:[]};
  const rr=row.getBoundingClientRect();
  const seen=new Set(); const icons=[];
  row.querySelectorAll('svg').forEach(s=>{
    const p=s.closest('[class*=icon],button,span,div')||s;
    const r=p.getBoundingClientRect();
    if(r.width<12||r.width>48||r.height<12||r.height>48) return;
    if(r.top-rr.top>rr.height/2) return;          // 只要行上半部那排
    const k=Math.round(r.x)+'_'+Math.round(r.y);
    if(seen.has(k)) return; seen.add(k);
    icons.push({x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
                w:Math.round(r.width), h:Math.round(r.height)});
  });
  icons.sort((a,b)=>a.x-b.x);
  return {row:{txt:cut(row.innerText).slice(0,120),
               y:Math.round(rr.y+rr.height/2), h:Math.round(rr.height)},
          icons:icons};
}"""

CONFIRM = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  let pop=null;
  document.querySelectorAll('div,section').forEach(e=>{
    const t=cut(e.innerText);
    if(!/删除|不可/.test(t)) return;
    if(!/取消/.test(t)) return;
    if(t.length>120) return;
    if(pop && cut(pop.innerText).length<=t.length) return;
    pop=e;
  });
  if(!pop) return null;
  const b=[...pop.querySelectorAll('button,span,div')]
    .filter(x=>/^(删除|确定|确认)$/.test(cut(x.innerText)) && x.children.length<2)
    .map(x=>{const r=x.getBoundingClientRect(); return {r:r,a:r.width*r.height};})
    .filter(o=>o.r.width>28&&o.r.height>14).sort((p,q)=>p.a-q.a)[0];
  return {txt:cut(pop.innerText).slice(0,140),
          btn: b?{x:Math.round(b.r.x+b.r.width/2),
                  y:Math.round(b.r.y+b.r.height/2)}:null};
}"""

STATE = r"""([key, stamp, keep]) => {
  const b=(document.body.innerText||'').replace(/\s+/g,' ');
  return {dup: b.includes(stamp), sched: b.includes(keep),
          n:(b.match(new RegExp(key,'g'))||[]).length};
}"""


def wait_list(pg):
    for _ in range(20):
        time.sleep(2)
        try:
            if pg.evaluate(STATE, [KEY, STAMP, KEEP])["n"]:
                return True
        except Exception:
            pass
    return False


def main():
    probe = "--probe" in sys.argv
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
            pg.goto(MANAGE, wait_until="domcontentloaded")
            if not wait_list(pg):
                print(u"❌ 列表没加载")
                return 3
            before = pg.evaluate(STATE, [KEY, STAMP, KEEP])
            print(u"删之前：%s" % before)
            rows = pg.evaluate(ROWS, [KEY])
            tgt = [r for r in rows if STAMP in r["txt"]
                   and u"定时发布" not in r["txt"]]
            tgt.sort(key=lambda r: r["len"])
            print(u"命中行 %d 个 · 目标候选 %d 个" % (len(rows), len(tgt)))
            for r in rows:
                print(u"  · [%d] %s" % (r["len"], r["txt"][:120]))
            if probe:
                if tgt:
                    pg.mouse.move(tgt[0]["x"], tgt[0]["y"])
                    time.sleep(2)
                    acts = pg.evaluate(ACTIONS, [KEY, STAMP])
                    print(u"hover 后图标：%s"
                          % json.dumps(acts, ensure_ascii=False))
                pg.screenshot(path=os.path.join(PIPE, "xhs_dedup_probe.png"))
                return 0
            if not before["dup"]:
                print(u"没有 %s 那条，不用删" % STAMP)
                return 0
            if not tgt:
                print(u"❌ 找不到目标行")
                return 4
            row = tgt[0]
            pg.mouse.move(row["x"], row["y"])
            time.sleep(2)
            d = pg.evaluate(ACTIONS, [KEY, STAMP])
            icons = d["icons"]
            print(u"hover 行 %r · 图标 %d 个" % (d["row"], len(icons)))
            if len(icons) < 3:
                print(u"❌ hover 后图标不足（%d 个），不敢点" % len(icons))
                pg.screenshot(path=os.path.join(PIPE, "xhs_dedup_fail.png"))
                return 5
            a = icons[-1]          # 最右那个是垃圾桶
            pg.mouse.click(a["x"], a["y"])
            time.sleep(2)
            c = pg.evaluate(CONFIRM)
            print(u"确认：%s" % (c["txt"] if c else None))
            if not c or not c["btn"]:
                print(u"❌ 没有确认按钮")
                pg.screenshot(path=os.path.join(PIPE, "xhs_dedup_fail.png"))
                return 6
            pg.mouse.click(c["btn"]["x"], c["btn"]["y"])
            time.sleep(4)
            pg.goto(MANAGE, wait_until="domcontentloaded")
            wait_list(pg)
            after = pg.evaluate(STATE, [KEY, STAMP, KEEP])
            print(u"删之后：%s" % after)
            pg.screenshot(path=os.path.join(PIPE, "xhs_dedup.png"))
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
