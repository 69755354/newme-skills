#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""量小红书「定时发布」最远能排到哪天 —— 这个数字决定一批内容能不能一次排完。
（视频号那把尺子是 wx_schedule_horizon.py；两边的结论都冻结进 schedule_target.py。）

⛔ 只读：不点「发布」/「暂存离开」/「保存草稿」。
⚠️ 和视频号不一样的两件事（实测 2026-08-21）：
  1) 小红书**没有文件时整张表单不渲染** —— 未上传时 `.post-time-wrapper` /
     `.d-switch` / `input.d-text` 全是 0 个，页面上只有拖拽区。所以量它必须先喂一个
     小样片（回归专用的 `_pipeline/wx_probe12.mp4`），喂完只碰定时控件。
     小红书会自动存草稿，量完请跑 `_xhs_clean_drafts.py` 清掉。
  2) 时间框**自己不校验上界**：键入 +64 天（'2026-10-24 19:30'）照单收下、回读一致，
     而且面板**不会跟着跳月**。所以「键入后回读一致」是**假判据**，拿它当上限探测器
     会得出「没有上限」的错误结论（第一版就是这么错的）。

真判据只有一个：日期面板里的格子有没有 `disabled`。
  面板 `.d-datepicker-calendar`：头 `.d-datepicker-header-main` = 「2026年 8月」，
  格子 `.d-datepicker-cell`（禁用态 class 带 disabled），
  翻月靠 `.d-datepicker-header` 里的 4 个 `span.d-icon.d-clickable`
  （顺序 ≪年 ‹月 月› 年≫，所以「下一月」= 倒数第二个），**每翻一次都要回读头部
  确认真的只前进了一个月**，别信「我点了」。
  ⚠️ 和视频号同一个坑：一屏里混着上/下月的日子（8 月面板头部有 7/27~7/31、
  尾部有 9/1~9/6），必须按「数字回到 1」切 monthIdx，直接 max(数字) 会算出
  2026-09-31 这种不存在的日期。

对照（缺一不可，不成立就报错退出、不给数字）：
  阴性 昨天必须是灰的；阳性 明天必须是亮的；
  另外上限那一月里，最后一个亮日**后面必须紧跟灰日** —— 否则说明只是没翻够月份。

输出：stdout 结论 + _pipeline/xhs_schedule_horizon.json
"""
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "_pipeline")
PROF = os.path.expanduser("~/NewMe/profiles/xiaohongshu")
HOME = "https://creator.rednote.com/publish/publish"
PROBE_MP4 = os.path.join(PIPE, "wx_probe12.mp4")
HHMM = "19:30"
FAR_DAYS = 64          # 用来揭穿「键入回读」这个假判据的远日期

PANEL_JS = r"""() => {
  const cut = s => (s||'').replace(/\s+/g,' ').trim();
  const pop = [...document.querySelectorAll('.d-datepicker-calendar')]
      .filter(e => { const r = e.getBoundingClientRect();
                     return r.width > 100 && r.height > 100; })[0];
  if (!pop) return {found: false};
  const head = pop.querySelector('.d-datepicker-header-main');
  const cells = [...pop.querySelectorAll('.d-datepicker-cell')].map(c => ({
      d: parseInt(cut(c.innerText), 10),
      off: /(^|\s)disabled(\s|$)/.test(String(c.className || ''))
  })).filter(x => !isNaN(x.d));
  const out = {found: true, head: head ? cut(head.innerText) : '',
               on: [], off: [], nCells: cells.length,
               icons: [...pop.querySelectorAll('.d-datepicker-header span.d-icon')]
                   .length};
  let mi = (cells.length && cells[0].d === 1) ? 0 : -1;
  cells.forEach((x, i) => {
    if (i && x.d === 1) mi++;
    if (mi !== 0) return;                 // 只认属于面板当月的格子
    (x.off ? out.off : out.on).push(x.d);
  });
  return out;
}"""

# 翻月：header 里第 idx 个可点图标，用原生 click（坐标点在浮层里不稳）
CLICK_ICON_JS = r"""(idx) => {
  const pop = [...document.querySelectorAll('.d-datepicker-calendar')]
      .filter(e => { const r = e.getBoundingClientRect();
                     return r.width > 100 && r.height > 100; })[0];
  if (!pop) return 'no-panel';
  const ic = [...pop.querySelectorAll('.d-datepicker-header span.d-icon')];
  if (idx >= ic.length) return 'no-icon(' + ic.length + ')';
  ic[idx].click();
  return 'ok';
}"""


def log(m):
    sys.stdout.write(m + "\n")
    sys.stdout.flush()


def bj_today():
    return (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()


def head_ym(panel):
    nums = [int(x) for x in re.findall(r"\d+", (panel or {}).get("head") or "")]
    if len(nums) < 2:
        return None
    return nums[0], nums[1]


def open_panel(pg):
    e = pg.query_selector(".post-time-wrapper input.d-text")
    if e is None:
        return None
    e.click()
    time.sleep(1.4)
    return pg.evaluate(PANEL_JS)


def next_month(pg, panel):
    u"""前进一个月。返回 (新面板, 说明)。判据 = 头部年月真的 +1 个月。"""
    cur = head_ym(panel)
    if not cur:
        return None, u"读不到面板头"
    want = (cur[0] + 1, 1) if cur[1] == 12 else (cur[0], cur[1] + 1)
    n_icon = panel.get("icons") or 0
    # 正常是 4 个图标（≪年 ‹月 月› 年≫）→ 下一月 = 倒数第二个；不对就把候选都试一遍
    order = [n_icon - 2] + [i for i in range(n_icon) if i != n_icon - 2]
    for idx in order:
        if idx < 0:
            continue
        r = pg.evaluate(CLICK_ICON_JS, idx)
        if r != "ok":
            continue
        time.sleep(1.2)
        p2 = pg.evaluate(PANEL_JS)
        if head_ym(p2) == want:
            return p2, u"图标 #%d" % idx
        # 点错了（翻年/翻反）→ 用同一个 idx 的镜像退回去，退不回就重开面板
        back = pg.evaluate(CLICK_ICON_JS, n_icon - 1 - idx)
        time.sleep(1.0)
        p3 = pg.evaluate(PANEL_JS)
        if head_ym(p3) != cur:
            pg.keyboard.press("Escape")
            time.sleep(0.5)
            p3 = open_panel(pg)
            if head_ym(p3) != cur:
                return None, u"翻月翻乱了（现在 %s）" % (p3 or {}).get("head")
        _ = back
    return None, u"没找到能前进一个月的图标（共 %d 个）" % n_icon


def typed_echo(pg, day):
    u"""键入 day 19:30 后回读 —— 只为留证：这条路**不校验上界**，是假判据。"""
    stamp = "%s %s" % (day.isoformat(), HHMM)
    e = pg.query_selector(".post-time-wrapper input.d-text")
    if e is None:
        return u"找不到时间框"
    e.click()
    time.sleep(0.4)
    pg.keyboard.press("Meta+a")
    pg.keyboard.type(stamp, delay=40)
    pg.keyboard.press("Enter")
    time.sleep(1.0)
    got = pg.evaluate("()=>{const e=document.querySelector"
                      "('.post-time-wrapper input.d-text');return e?e.value:'';}")
    pg.keyboard.press("Escape")
    time.sleep(0.5)
    return got


def main():
    from playwright.sync_api import sync_playwright
    import publish_xhs as xhs
    if not os.path.isfile(PROBE_MP4):
        log(u"❌ 小样片不在：%s" % PROBE_MP4)
        return 2
    subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])
    time.sleep(3)
    today = bj_today()
    res = {"today_bj": today.isoformat(), "months": [], "max_date": None,
           "days_ahead": None, "controls": {}, "note": ""}
    rc = 2
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROF, channel="chrome", headless=False, no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(45000)
        ctx.new_cdp_session(pg).send("Emulation.setTimezoneOverride",
                                     {"timezoneId": "Asia/Shanghai"})
        log(u"时区已覆盖：%s" % pg.evaluate("()=>new Date().toString().slice(0,33)"))
        try:
            pg.goto(HOME, wait_until="domcontentloaded")
            time.sleep(6)
            body = pg.evaluate("()=>document.body.innerText.slice(0,400)")
            if any(w in body for w in xhs.LOGIN_WORDS):
                log(u"❌ 掉线了，先登录")
                return 2
            if not xhs.wait_form(pg):
                log(u"❌ 上传区没出来")
                return 2
            ok, why = xhs.upload(pg, PROBE_MP4)
            log(u"喂小样片：%s %s" % (u"✅" if ok else u"❌", why))
            if not ok:
                return 2
            xhs.switch_on(pg, ".post-time-wrapper")
            s = xhs.state(pg)
            log(u"定时开关：submit-text=%r · 默认值=%r" % (s["submitText"], s["sched"]))
            if s["submitText"] != u"定时发布":
                log(u"❌ 定时开关没生效")
                return 2

            # 假判据留证：键入 +64 天，看它收不收
            far = today + dt.timedelta(days=FAR_DAYS)
            echo = typed_echo(pg, far)
            res["typed_far"] = {"date": far.isoformat(), "echo": echo,
                                "accepted": echo == "%s %s" % (far.isoformat(), HHMM)}
            log(u"键入 +%d 天（%s）→ 回读 %r%s"
                % (FAR_DAYS, far.isoformat(), echo,
                   u"  ⛔ 收下了 = 时间框不校验上界，别拿它当判据"
                   if res["typed_far"]["accepted"] else u""))
            # 把值改回近期，免得面板从远处的月份开始
            typed_echo(pg, today + dt.timedelta(days=1))

            panel = open_panel(pg)
            if not panel or not panel.get("found"):
                log(u"❌ 打不开日期面板")
                return 2
            log(u"面板首屏：%s｜图标 %d 个｜亮 %s｜灰 %s"
                % (panel.get("head"), panel.get("icons"), panel.get("on"),
                   panel.get("off")))
            # ── 对照：昨天必须灰、明天必须亮（都在首屏这一月里）──
            y, t = today - dt.timedelta(days=1), today + dt.timedelta(days=1)
            ctl = {}
            if head_ym(panel) == (y.year, y.month):
                ctl["yesterday_off"] = y.day in (panel.get("off") or [])
            if head_ym(panel) == (t.year, t.month):
                ctl["tomorrow_on"] = t.day in (panel.get("on") or [])
            res["controls"] = ctl
            log(u"对照：昨天灰=%s · 明天亮=%s"
                % (ctl.get("yesterday_off"), ctl.get("tomorrow_on")))
            if ctl.get("yesterday_off") is not True or ctl.get("tomorrow_on") is not True:
                log(u"❌ 对照不成立，判据本身有问题，不给数字")
                res["note"] = u"对照不成立"
                return 2

            # ── 逐月前进，找「最后一个亮日 + 后面紧跟灰日」的那一月 ──
            last_ok, bounded = None, False
            for _ in range(8):
                ym = head_ym(panel)
                on = sorted(panel.get("on") or [])
                off = sorted(panel.get("off") or [])
                res["months"].append({"head": panel.get("head"), "on": on, "off": off})
                log(u"  %s｜亮 %s｜灰 %s" % (panel.get("head"), on, off))
                if on:
                    last_ok = (ym[0], ym[1], on[-1])
                    # 本月最后一个亮日之后还有灰日 → 上界就在本月（阴性对照）
                    if [d for d in off if d > on[-1]]:
                        bounded = True
                        break
                elif last_ok:
                    bounded = True          # 整月全灰 → 上界在上一月的最后一个亮日
                    break
                panel, why2 = next_month(pg, panel)
                log(u"  翻下一月：%s" % why2)
                if not panel:
                    res["note"] += u"翻月失败(%s)；" % why2
                    break
            if last_ok and bounded:
                yy, mm, dd = last_ok
                res["max_date"] = "%04d-%02d-%02d" % (yy, mm, dd)
                res["days_ahead"] = (dt.date(yy, mm, dd) - today).days
                rc = 0
            else:
                res["note"] += u"没看到上界（最后一个亮日 %s）；" % (last_ok,)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROF])
            with io.open(os.path.join(PIPE, "xhs_schedule_horizon.json"), "w",
                         encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False, indent=2))
    log(u"—— 结论 ——")
    log(u"%s 定时最远可排到 %s（北京今天 %s 起 %s 天）"
        % (u"✅" if rc == 0 else u"⚠️", res["max_date"], res["today_bj"],
           res["days_ahead"]))
    log(u"备注：%s" % (res["note"] or u"无"))
    log(u"⚠️ 记得跑 _xhs_clean_drafts.py 清掉这次留下的草稿")
    return rc


if __name__ == "__main__":
    sys.exit(main())
