#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""量一下视频号「定时发表」最远能排到哪天 —— 这个数字决定一次扫码能顶几天。

思路：进发表页 → 勾「定时」→ 打开日期选择器 → 逐月点「下一月」，
每月统计**没有** weui-desktop-picker__disabled 的日期格子；
出现整月全灰的那一月，说明上限就在上一月里 → 取最后一个可选日。

⛔ 只读：不上传、不填字、绝不点「发表」/「保存草稿」。
⚠️ 时区：Mac 是迪拜(UTC+4)，视频号按浏览器时区渲染，所以先用 CDP 覆盖成上海，
   否则量出来的边界会差一天。
输出：stdout 一行结论 + _pipeline/wx_schedule_horizon.json
"""
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "_pipeline")
PROF = os.path.expanduser("~/NewMe/profiles/weixin")
HOME = "https://channels.weixin.qq.com/platform"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

# 面板里可选/不可选的日期格子。禁用态类名是 weui-desktop-picker__disabled。
# ⚠️ 日历表格里**混着上/下个月的日子**（8 月面板尾部还有 9/1~9/4）。
#    直接 max(数字) 会把「上个月的 31 号」当成本月上限 —— 9 月面板算出
#    2026-09-31 这种不存在的日期，程序当场崩（踩过）。
#    所以按格子顺序给每个日子标 monthIdx：每次数字回到 1 就进入下一个月，
#    -1=上月、0=本月、1=下月，之后按 (monthIdx, day) 比大小才对。
CELLS = r"""() => {
  const out={cells:[],disabled:0,label:''};
  const lab=document.querySelectorAll('span.weui-desktop-picker__panel__label');
  out.label=[...lab].map(e=>e.innerText.trim()).join(' ');
  const all=[...document.querySelectorAll('table.weui-desktop-picker__table a')]
      .map(a=>({d:parseInt((a.innerText||'').trim(),10),
                off:(a.className||'').includes('weui-desktop-picker__disabled')}))
      .filter(x=>!isNaN(x.d));
  let mi = (all.length && all[0].d===1) ? 0 : -1;
  all.forEach((x,i)=>{
    if(i && x.d===1) mi++;
    if(x.off) out.disabled++;
    else out.cells.push([mi, x.d]);
  });
  return out;
}"""


# 「下一月」箭头：⚠️ 页面上有好几个 .weui-desktop-btn__icon__right（年/月各一对，
# 还有别的隐藏面板里的同类按钮），Playwright 直接 click 选择器会挑到不可见的那个，
# 然后死等 60 秒可见性超时。所以在 JS 里自己筛：**带日期表格的那个可见面板**里的
# 第一个可见右箭头，用原生 click 派发。
NEXT_MONTH = r"""() => {
  const vis=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};
  const panels=[...document.querySelectorAll('.weui-desktop-picker__panel')]
      .filter(p=>vis(p) && p.querySelector('table.weui-desktop-picker__table'));
  if(!panels.length) return 'no-panel';
  const a=[...panels[0].querySelectorAll('.weui-desktop-btn__icon__right')].filter(vis);
  if(!a.length) return 'no-arrow';
  a[0].click();
  return 'ok';
}"""


def main():
    from playwright.sync_api import sync_playwright
    subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])
    time.sleep(2)
    res = {"months": [], "max_date": None, "days_ahead": None}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROF, channel="chrome", headless=False,
            no_viewport=True, user_agent=UA,
            args=["--window-position=-3000,0", "--window-size=1440,900",
                  "--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(60000)
        try:
            cdp = ctx.new_cdp_session(pg)
            cdp.send("Emulation.setTimezoneOverride",
                     {"timezoneId": "Asia/Shanghai"})
        except Exception as e:
            print(u"⚠️ 时区覆盖失败（结果可能差一天）：%s" % str(e)[:60])
        try:
            pg.goto(HOME, wait_until="domcontentloaded")
            time.sleep(8)
            if any(("login.html" in (f.url or "")) or ("qrconnect" in (f.url or ""))
                   for f in pg.frames):
                print(u"❌ 掉线了，先扫码")
                return 2
            # 首页可点的入口是 button.weui-desktop-btn，get_by_text 会命中隐藏的说明段
            pg.locator("button.weui-desktop-btn", has_text=u"发表视频").first.click()
            pg.wait_for_url("**/post/create", timeout=60000)
            try:
                pg.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                pass
            time.sleep(3)
            # ⚠️ 两个坑一起踩过：①表单在 micro/content/post/create 的 iframe 里，
            #    在主 frame 上 evaluate 永远 0 个格子；②「请选择发表时间」这个 input
            #    **只有切到「定时」之后才渲染**，所以不能拿它去找 frame。
            #    直接复用发布脚本里已验证的 wx_frame / click_xy，别另写一套。
            from publish_weixin import wx_frame, click_xy, PH_SCHED
            fr = wx_frame(pg)
            print(u"  表单 frame：%s" % (fr.url or "")[-50:])
            ok, why = click_xy(pg, fr,
                               "[...document.querySelectorAll('label')]"
                               ".find(l=>l.querySelector('input[value=\"1\"]')"
                               "&&(l.innerText||'').trim()==='定时')",
                               why=u"切定时", wait=1.5)
            if not ok:
                print(u"❌ 切定时失败：%s" % why)
                return 2
            ok, why = click_xy(pg, fr,
                               "[...document.querySelectorAll('input')]"
                               ".find(i=>(i.placeholder||'')==='%s')" % PH_SCHED,
                               dx=40, why=u"点开日期面板", wait=1.5)
            if not ok:
                print(u"❌ 打不开日期面板：%s" % why)
                return 2

            seen, last_ok = [], None
            for _ in range(8):
                d = fr.evaluate(CELLS)
                cells = [tuple(c) for c in d["cells"]]
                # 只认属于面板当月（monthIdx==0）的可选日子；面板年月来自 label
                nums = [int(s) for s in re.findall(r"\d+", d["label"])]
                y, m = (nums + [date.today().year, date.today().month])[:2]
                mine = sorted(c[1] for c in cells if c[0] == 0)
                seen.append({"label": d["label"], "enabled": len(mine),
                             "disabled": d["disabled"],
                             "days": mine, "last": mine[-1] if mine else None})
                # 边走边打：出错时至少知道走到哪一月了
                print(u"  %s｜本月可选 %d 天%s·灰 %d"
                      % (d["label"], len(mine),
                         (u"（%d~%d）" % (mine[0], mine[-1])) if mine else u"",
                         d["disabled"]))
                if mine:
                    last_ok = (y, m, mine[-1])
                elif last_ok:
                    break        # 整月全灰 → 上限在上一月
                r = fr.evaluate(NEXT_MONTH)
                if r != "ok":
                    print(u"  ⚠️ 翻月失败：%s，就到这" % r)
                    try:
                        pg.screenshot(path=os.path.join(
                            PIPE, "wx_horizon_stuck.png"), full_page=True)
                    except Exception:
                        pass
                    break
                time.sleep(1.2)
            res["months"] = seen
            if last_ok:
                y, m, dd = last_ok
                res["max_date"] = "%04d-%02d-%02d" % (y, m, dd)
                res["days_ahead"] = (date(y, m, dd) - date.today()).days
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])

    with io.open(os.path.join(PIPE, "wx_schedule_horizon.json"), "w",
                 encoding="utf-8") as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=2))
    print(u"✅ 定时最远可排到 %s（今天起 %s 天）"
          % (res["max_date"], res["days_ahead"]))
    return 0 if res["max_date"] else 2


if __name__ == "__main__":
    sys.exit(main())
