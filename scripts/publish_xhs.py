#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""小红书发布器（专机专用，判据全部有阳性对照）。

用法：
  publish_xhs.py 方案.json --mode fill            # 填完就走，不发布
  publish_xhs.py 方案.json --mode publish         # 真发（定时）
  publish_xhs.py 方案.json --mode fill --times 10 # 稳定性连测
  可加 --video x.mp4 覆盖方案里的片子

—— 2026-08-20 实测得到的地基（改代码前先读，全是踩出来的）——
· 域名必须 creator.rednote.com（海外账号走大陆域名 401 踢回登录页）。
· 表单是 **light DOM**（和视频号的 wujie 完全不同），locator 可用，
  但发布按钮 `<xhs-publish-btn>` 的真按钮在**闭合 shadow** 里，只能按坐标点。
· 上传完成的唯一真判据：`xhs-publish-btn[submit-disabled]` 从 "true" 变 "false"。
  阳性对照已做：喂完文件 3 秒时 = true，传完 = false。
  ⛔ 别拿 body 里的「上传中 N%」当判据 —— 小片子 4 秒就没了，且不出「上传成功」。
· 定时：点 `.post-time-wrapper .d-switch`。成功的连带证据是宿主属性
  `submit-text` 从「发布」变成「定时发布」；时间框是 `.post-time-wrapper input.d-text`
  （非只读，默认已填北京时间的一小时后）。
· 原创：点 `.original-wrapper .d-switch` → 弹「原创声明须知」→ 点「声明原创」。
  回读 = wrapper 里的隐藏 checkbox value == 'true' 且弹窗已关。
· ⛔ 时区：一律 CDP 覆盖 Asia/Shanghai，否则时间框默认值和你填的值都按迪拜算，差 4 小时。
· 位置故意不填：POI 搜索按出口 IP 定位，搜「迪拜」出来的是阿布坵比的同名店，
  宁可不显示也不能给迪拜别墅标错城市（和视频号同一个结论）。
· 发布按钮栏实测 772px 宽，「暂存离开」在中心 -72、「发布」在 +71。
  ⛔ 不能按宽度比例算 —— 栏宽随版面变、按钮宽固定，比例一滑就点到「暂存离开」，
  那个会存草稿并跳走，等于没发。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.expanduser("~/NewMe/profiles/xiaohongshu")
HOME = "https://creator.rednote.com/publish/publish"
# 笔记列表的真地址（/publish/notes 是旧的，会跳走）
MANAGE = "https://creator.rednote.com/new/note-manager"
LOGIN_WORDS = [u"扫码登录", u"手机号登录", u"登录小红书"]

TITLE_SEL = "input.d-text[placeholder*='填写标题']"
BODY_SEL = "div.tiptap"
BTN = "xhs-publish-btn"


def log(m):
    if isinstance(m, bytes):
        m = m.decode("utf-8")
    sys.stdout.write(m + "\n")
    sys.stdout.flush()


def shot(pg, tag):
    try:
        p = os.path.join(ROOT, "_pipeline", "xhs_%s.png" % tag)
        pg.screenshot(path=p, full_page=True)
        log(u"       截图 %s" % os.path.basename(p))
    except Exception:
        pass


# ── 判据 ────────────────────────────────────────────────────────

STATE_JS = r"""() => {
  const b = document.querySelector('xhs-publish-btn');
  const t = document.querySelector("input.d-text[placeholder*='填写标题']");
  const body = document.querySelector('div.tiptap');
  const hid = s => { const e = document.querySelector(s + " input[type=checkbox], "
                       + s + " input:not([type=text])");
                     return e ? String(e.value) : null; };
  const tin = document.querySelector('.post-time-wrapper input.d-text');
  const topics = body ? [...body.querySelectorAll('*')].filter(e =>
      /topic|mention|hash|tag/i.test(String(e.className||'')) ||
      e.getAttribute('data-topic') !== null ||
      e.getAttribute('data-type') !== null ||
      (e.tagName === 'A' && /topic/i.test(e.getAttribute('href')||''))
    ).map(e => (e.innerText||'').trim()).filter(t => t) : [];
  const modal = [...document.querySelectorAll('[class*=modal],[class*=dialog]')]
    .filter(x => { const r = x.getBoundingClientRect();
      return r.width > 200 && r.height > 100 &&
             getComputedStyle(x).display !== 'none'; })
    .map(x => (x.innerText||'').replace(/\s+/g,' ').trim().slice(0,160));
  const r = b ? b.getBoundingClientRect() : null;
  return {
    up: b ? b.getAttribute('submit-disabled') : null,
    submitText: b ? b.getAttribute('submit-text') : null,
    bar: r ? {x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width), h: Math.round(r.height)} : null,
    title: t ? t.value : null,
    bodyLen: body ? (body.innerText || '').replace(/\s+/g,'').length : null,
    bodyTxt: body ? (body.innerText || '').replace(/\s+/g,' ').slice(0, 200) : null,
    topics: topics,
    orig: hid('.original-wrapper'),
    sched: tin ? tin.value : null,
    perm: (document.querySelector('.permission-card-wrapper') || {}).innerText
          ? document.querySelector('.permission-card-wrapper').innerText
              .replace(/\s+/g,' ').trim().slice(0, 30) : null,
    modal: modal,
    bodyHtml: body ? body.innerHTML.replace(/\s+/g,' ').slice(-700) : null,
    pct: ((document.body.innerText||'').match(/上传中\s*\d{1,3}%/) || [''])[0],
  };
}"""


def state(pg):
    return pg.evaluate(STATE_JS)


def wait_form(pg, timeout=60):
    for _ in range(timeout):
        time.sleep(1)
        try:
            pg.evaluate("()=>1")
            if pg.query_selector("input.upload-input"):
                return True
        except Exception:
            pass
    return False


def upload(pg, video, timeout=900):
    u"""喂文件 + 等 submit-disabled 变 false（唯一真判据）。"""
    try:
        pg.set_input_files("input.upload-input", video)
    except Exception as e:
        return False, u"喂文件失败：%s" % str(e)[:90]
    t0 = time.time()
    saw_true = False
    last = ""
    while time.time() - t0 < timeout:
        time.sleep(2)
        try:
            s = state(pg)
        except Exception:
            continue
        last = u"submit-disabled=%s %s" % (s["up"], s["pct"])
        if s["up"] == "true":
            saw_true = True           # 阳性对照：真的经过"未就绪"这个状态
        if u"上传失败" in " ".join(s["modal"] or []):
            return False, u"平台报上传失败"
        if s["up"] == "false" and pg.query_selector(TITLE_SEL):
            return True, u"传完了（%.0f 秒 · 经过未就绪态=%s）" % (
                time.time() - t0, u"是" if saw_true else u"没看到")
    return False, u"上传超时（%s）" % last


def set_title(pg, title):
    if not title:
        return True, u"方案没给标题"
    e = pg.query_selector(TITLE_SEL)
    if e is None:
        return False, u"找不到标题输入框"
    e.click()
    pg.keyboard.press("Meta+a")
    pg.keyboard.press("Delete")
    pg.keyboard.type(title[:20], delay=25)
    time.sleep(0.6)
    got = state(pg)["title"] or ""
    return (got.strip() == title[:20].strip()), u"标题回读 %r" % got


def set_body(pg, body, topics):
    u"""正文 + 话题。话题必须点下拉候选才是真话题；点不出来如实报降级。"""
    e = pg.query_selector(BODY_SEL)
    if e is None:
        return False, u"找不到正文编辑器", {}
    e.click()
    pg.keyboard.press("Meta+a")
    pg.keyboard.press("Delete")
    for i, line in enumerate((body or "").split("\n")):
        if i:
            pg.keyboard.press("Enter")
        if line:
            pg.keyboard.type(line, delay=6)
    time.sleep(0.8)
    # 话题：另起一行，逐个打 # 再点候选
    picked, cand_dump = [], []
    if topics:
        pg.keyboard.press("Enter")
        for name in topics:
            nm = (name or "").lstrip("#").strip()
            if not nm:
                continue
            # ⛔ 「#」前必须有空白：紧贴上一个话题节点打 # 时 tiptap 不触发 suggestion，
            #   实测第 1 个话题成、第 2~5 个全军覆没就是这个原因。
            pg.keyboard.type(" ", delay=20)
            pg.keyboard.type("#" + nm, delay=45)
            hit, cands = pick_topic(pg, nm)
            cand_dump.append({"topic": nm, "hit": hit, "cands": cands[:6]})
            if hit:
                picked.append(nm)
            else:
                pg.keyboard.type(" ", delay=20)   # 收掉浮层，降级为纯文字
            time.sleep(0.6)
        # ⛔ 最后一个话题会**卡在 suggestion 态**（还是 span.suggestion，不是真话题 a）。
        #   前面几个之所以变成真话题，是因为下一轮打空格+# 时被顺带提交了。
        #   所以收尾必须再补一个空格，否则永远差最后一个。
        for _ in range(3):
            if not pg.query_selector("div.tiptap span.suggestion"):
                break
            pg.keyboard.type(" ", delay=20)
            time.sleep(1.0)
    s = state(pg)
    real = len(s["topics"] or [])
    ok = (s["bodyLen"] or 0) > 30 and real >= len(topics or [])
    return ok, u"正文 %s 字 · 真话题节点 %d/%d 点中 %s" % (
        s["bodyLen"], real, len(topics or []), picked), \
        {"cands": cand_dump, "nodes": s["topics"], "html": s["bodyHtml"]}


PICK_JS = r"""(name) => {
  const cut = s => (s||'').replace(/\s+/g,' ').trim();
  const out = [];
  document.querySelectorAll('[class*=topic],[class*=mention],[class*=dropdown],'
    + '[class*=suggest],[class*=option],li').forEach(e => {
    if (e.children.length > 3) return;
    const r = e.getBoundingClientRect();
    if (r.width < 40 || r.height < 12) return;
    const t = cut(e.innerText);
    if (!t || t.length > 30) return;
    out.push({t: t, cls: String(e.className||'').slice(0,40),
              x: Math.round(r.x + 40), y: Math.round(r.y + r.height/2)});
  });
  return out;
}"""


def pick_topic(pg, name, tries=10):
    u"""等 tiptap 的 suggestion 浮层出来，用**回车**采纳第一条。

    ⛔ 别用鼠标点候选：实测点下去会把焦点带出编辑器，后面 4 个话题连字都打不进去
    （现象是正文里只剩第 1 个话题、后面全空）。suggestion 是 tiptap 的键盘列表，
    Enter 就是采纳，焦点始终留在编辑器里。"""
    cands = []
    for _ in range(tries):
        time.sleep(0.6)
        try:
            cands = pg.evaluate(PICK_JS, name)
        except Exception as e:
            return None, [{"err": str(e)[:60]}]
        sug = [c for c in cands if "suggestion" in c["cls"]]
        hit = None
        for c in sug:
            t = c["t"].lstrip("#").strip()
            if t == name or t.startswith(name):
                hit = c["t"]
                break
        if hit:
            pg.keyboard.press("Enter")
            time.sleep(0.8)
            return hit, cands
    return None, cands


def switch_on(pg, wrapper, want_true=True):
    u"""点 .d-switch，回读 wrapper 里隐藏 checkbox 的 value。"""
    sel = "%s .d-switch" % wrapper
    e = pg.query_selector(sel)
    if e is None:
        e = pg.query_selector("%s .custom-switch-wrapper" % wrapper)
        if e is None:
            return False, u"找不到开关 %s" % wrapper
    e.click()
    time.sleep(1.5)
    return True, u"点了 %s" % sel


# ⛔ 「声明原创」按钮一开始是**禁用**的（浅粉色，悬浮提示「请先阅读并同意原创声明须知」）。
#   必须先勾弹窗底部那个 checkbox「我已阅读并同意《原创声明须知》」。
#   只点按钮 = 什么都不发生 = 弹窗一直盖着 = 体检挂在「有弹窗盖着」（已踩）。
#   勾的时候只点 checkbox 本体，别点到《原创声明须知》那个链接（会开新页）。
ORIG_BTN_JS = r"""() => {
  const boxes = [...document.querySelectorAll('[class*=modal],[class*=dialog]')]
    .filter(x => { const r = x.getBoundingClientRect();
      return r.width > 200 && r.height > 100 &&
             getComputedStyle(x).display !== 'none'; });
  if (!boxes.length) return null;
  const m = boxes[boxes.length - 1];
  const mid = e => { const r = e.getBoundingClientRect();
    return {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2),
            w: Math.round(r.width), h: Math.round(r.height)}; };
  let agree = null, checked = null;
  const cb = [...m.querySelectorAll("input[type=checkbox]")];
  if (cb.length) {
    checked = !!cb[0].checked;
    // 真正可点的是包着 input 的那个方框（input 常是 0×0 或被盖住）
    let host = cb[0];
    for (let i = 0; i < 4 && host.parentElement; i++) {
      const r = host.getBoundingClientRect();
      if (r.width >= 12 && r.height >= 12) break;
      host = host.parentElement;
    }
    agree = mid(host);
  }
  const btn = [...m.querySelectorAll('button,div,span')].filter(e => {
    const t = (e.innerText||'').replace(/\s+/g,' ').trim();
    const r = e.getBoundingClientRect();
    return t === '声明原创' && r.width > 40 && r.height > 16 && e.children.length < 2;
  });
  return {txt: (m.innerText||'').replace(/\s+/g,' ').slice(0,60),
          agree: agree, checked: checked,
          btn: btn.length ? mid(btn[btn.length-1]) : null};
}"""


def declare_original(pg):
    ok, why = switch_on(pg, ".original-wrapper")
    if not ok:
        return False, why
    trail = []
    for _ in range(5):
        d = pg.evaluate(ORIG_BTN_JS)
        if d is None:
            break
        trail.append(u"勾=%s" % d["checked"])
        if d["agree"] and not d["checked"]:
            pg.mouse.click(d["agree"]["x"], d["agree"]["y"])
            time.sleep(0.8)
            continue
        if d["btn"]:
            pg.mouse.click(d["btn"]["x"], d["btn"]["y"])
            time.sleep(1.5)
            continue
        pg.keyboard.press("Escape")
        time.sleep(1)
    s = state(pg)
    return (s["orig"] == "true" and not s["modal"]), \
        u"原创=%s 残留弹窗=%s（%s）" % (s["orig"], s["modal"] or u"无",
                                 " ".join(trail))


def set_schedule(pg, stamp):
    ok, why = switch_on(pg, ".post-time-wrapper")
    if not ok:
        return False, why
    s = state(pg)
    if s["submitText"] != u"定时发布":
        return False, u"开关没生效（submit-text 还是 %r）" % s["submitText"]
    e = pg.query_selector(".post-time-wrapper input.d-text")
    if e is None:
        return False, u"找不到时间输入框"
    e.click()
    time.sleep(0.5)
    pg.keyboard.press("Meta+a")
    pg.keyboard.type(stamp, delay=60)
    pg.keyboard.press("Enter")
    time.sleep(1)
    pg.keyboard.press("Escape")
    time.sleep(0.8)
    got = state(pg)
    return (got["sched"] or "").strip() == stamp, \
        u"时间框回读 %r（期望 %r）· submit-text=%r" % (got["sched"], stamp,
                                                got["submitText"])


def preflight(pg, want):
    s = state(pg)
    bad = []
    if s["up"] != "false":
        bad.append(u"上传未就绪 submit-disabled=%s" % s["up"])
    if not (s["title"] or "").strip():
        bad.append(u"标题空")
    if (s["bodyLen"] or 0) < 30:
        bad.append(u"正文只有 %s 字" % s["bodyLen"])
    if want.get("sched") and (s["sched"] or "").strip() != want["sched"]:
        bad.append(u"定时 %r ≠ %r" % (s["sched"], want["sched"]))
    if want.get("sched") and s["submitText"] != u"定时发布":
        bad.append(u"按钮还是「%s」" % s["submitText"])
    if want.get("orig") and s["orig"] != "true":
        bad.append(u"原创没勾上（%s）" % s["orig"])
    if s["modal"]:
        bad.append(u"有弹窗盖着：%s" % s["modal"][0][:40])
    if not s["bar"] or s["bar"]["w"] < 300:
        bad.append(u"发布按钮栏异常 %s" % s["bar"])
    return (not bad), bad, s


def do_publish(pg):
    u"""⛔ 按坐标点：栏中心右移 71px 是「发布」，左移 72 是「暂存离开」（会存草稿跳走）。"""
    s = state(pg)
    bar = s["bar"]
    if not bar or bar["w"] < 300:
        return False, u"按钮栏异常 %s" % bar
    if s["up"] != "false":
        return False, u"submit-disabled=%s，不敢点" % s["up"]
    cx = bar["x"] + bar["w"] / 2.0
    cy = bar["y"] + bar["h"] / 2.0
    x, y = cx + 71, cy
    pg.evaluate("()=>document.querySelector('xhs-publish-btn')"
                ".scrollIntoView({block:'center'})")
    time.sleep(0.6)
    s = state(pg)
    bar = s["bar"]
    x, y = bar["x"] + bar["w"] / 2.0 + 71, bar["y"] + bar["h"] / 2.0
    log(u"       点发布 @(%.0f,%.0f)（栏 %dx%d @%d,%d）"
        % (x, y, bar["w"], bar["h"], bar["x"], bar["y"]))
    pg.mouse.click(x, y)
    seen = ""
    for i in range(60):
        time.sleep(1)
        try:
            t = pg.inner_text("body", timeout=4000) or ""
        except Exception:
            t = ""
        if re.search(u"发布成功|定时发布成功|发布任务已创建", t):
            return True, u"平台回「发布成功」（%d 秒）" % (i + 1)
        if "/publish/publish" not in pg.url:
            return True, u"跳走了 URL=%s（%d 秒）" % (pg.url, i + 1)
        m = re.findall(u"暂存|失败|请填写|不能为空|违规|审核", t)
        if m and str(m) != seen:
            seen = str(m)
    return False, u"60 秒没有成功信号（页面提示 %s，URL=%s）" % (seen, pg.url)


def verify_manage(pg, title, stamp, tries=3):
    u"""最终判据：笔记管理列表里能看到这条 + 定时时间。"""
    for _ in range(tries):
        try:
            pg.goto(MANAGE, wait_until="domcontentloaded")
        except Exception:
            pass
        for _ in range(12):
            time.sleep(2)
            try:
                pg.evaluate("()=>1")
                t = (pg.inner_text("body", timeout=6000) or "").replace("\n", " ")
            except Exception:
                continue
            if title[:8] in t:
                hit = re.findall(u"[^ ]*%s[^ ]{0,40}" % re.escape(stamp[5:16]), t)
                return True, u"列表里有「%s…」%s" % (title[:10],
                                                (u" · 时间 %s" % hit[0]) if hit
                                                else u"（没读到时间戳）")
    return False, u"笔记管理里没读到这条"


# ── 一轮 ────────────────────────────────────────────────────────

def one_round(pg, plan, video, mode, stamp):
    cfg = plan.get("xiaohongshu") or {}
    steps = []

    def rec(name, ok, why):
        steps.append({"step": name, "ok": bool(ok), "why": why})
        log(u"    %s %-6s %s" % (u"✅" if ok else u"❌", name, why))
        return ok

    pg.goto(HOME, wait_until="domcontentloaded")
    if not wait_form(pg):
        body = ""
        try:
            body = pg.inner_text("body", timeout=6000) or ""
        except Exception:
            pass
        if [w for w in LOGIN_WORDS if w in body]:
            return False, [{"step": u"登录", "ok": False, "why": u"掉登录了，要扫码"}]
        return False, [{"step": u"表单", "ok": False, "why": u"等不到上传区"}]
    rec(u"表单", True, u"上传区就绪")

    if not rec(u"上传", *upload(pg, video)):
        shot(pg, "90_upload")
        return False, steps
    rec(u"标题", *set_title(pg, cfg.get("title") or ""))
    ok, why, diag = set_body(pg, cfg.get("body") or "", cfg.get("topics") or [])
    rec(u"正文", ok, why)
    try:
        with io.open(os.path.join(ROOT, "_pipeline", "xhs_topics.json"), "w",
                     encoding="utf-8") as f:
            f.write(json.dumps(diag, ensure_ascii=False, indent=1))
    except Exception:
        pass
    if cfg.get("schedule", True):
        rec(u"定时", *set_schedule(pg, stamp))
    if cfg.get("declare_original"):
        rec(u"原创", *declare_original(pg))
    rec(u"位置", True, u"故意不填（POI 按出口 IP 定位，会标成阿布扎比）")

    want = {"sched": stamp if cfg.get("schedule", True) else None,
            "orig": bool(cfg.get("declare_original"))}
    ok, bad, s = preflight(pg, want)
    rec(u"体检", ok, u"通过" if ok else u" / ".join(bad))
    log(u"       现场：%s" % json.dumps(
        {k: s[k] for k in ("up", "submitText", "title", "bodyLen", "topics",
                           "orig", "sched", "perm")}, ensure_ascii=False))
    if not ok:
        shot(pg, "91_preflight")
        return False, steps

    if mode == "fill":
        shot(pg, "filled")
        return rec(u"收尾", True, u"fill 模式：填好不发（会留一条草稿）"), steps

    if not rec(u"发布", *do_publish(pg)):
        shot(pg, "92_publish")
        return False, steps
    shot(pg, "published")
    return rec(u"回读", *verify_manage(pg, cfg.get("title") or "", stamp)), steps


def bj_stamp(hhmm, min_ahead=45):
    u"""目标北京时间字符串 YYYY-MM-DD HH:MM（不够 45 分钟就顺延到明天）。"""
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    h, m = [int(x) for x in (hhmm or "19:30").split(":")]
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if (t - now).total_seconds() < min_ahead * 60:
        t += dt.timedelta(days=1)
    return t.strftime("%Y-%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--mode", default="fill", choices=["fill", "publish"])
    ap.add_argument("--video", default="")
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "_pipeline", "xhs_test.json"))
    a = ap.parse_args()

    with io.open(os.path.expanduser(a.plan), encoding="utf-8") as f:
        plan = json.load(f)
    video = os.path.expanduser(a.video or plan.get("video") or "")
    if not os.path.isfile(video):
        log(u"❌ 视频不在：%s" % video)
        return 1
    cfg = plan.get("xiaohongshu") or {}
    stamp = bj_stamp(cfg.get("schedule_bj_time") or plan.get("schedule_bj_time"))
    log(u"视频 %s（%.1f MB）· 模式 %s · 跑 %d 遍"
        % (os.path.basename(video), os.path.getsize(video) / 1e6, a.mode, a.times))
    log(u"定时目标 北京 %s" % stamp)

    # ⛔ 上一轮的 Chrome 没退干净时，Playwright 会拿到「正在现有的浏览器会话中打开」
    #   然后直接失败。所以开跑前**只**杀这个 profile 的进程（绝不 pkill chrome）。
    import subprocess
    subprocess.call(["pkill", "-TERM", "-f", "user-data-dir=%s" % PROFILE])
    time.sleep(3)

    from playwright.sync_api import sync_playwright
    rounds = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE, channel="chrome", headless=False,
            no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled",
                  "--remote-debugging-port=9223"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(45000)
        # ⛔ 不覆盖时区，时间框默认值和填进去的值都按迪拜算，差 4 小时
        ctx.new_cdp_session(pg).send("Emulation.setTimezoneOverride",
                                     {"timezoneId": "Asia/Shanghai"})
        log(u"时区已覆盖：%s" % pg.evaluate("()=>new Date().toString().slice(0,33)"))
        try:
            for i in range(a.times):
                log(u"\n── 第 %d/%d 遍 ────────────────────" % (i + 1, a.times))
                t0 = time.time()
                try:
                    ok, steps = one_round(pg, plan, video, a.mode, stamp)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    ok, steps = False, [{"step": "fatal", "ok": False,
                                         "why": str(e)[:200]}]
                rounds.append({"i": i + 1, "ok": ok,
                               "sec": round(time.time() - t0, 1), "steps": steps})
                log(u"   → 第 %d 遍 %s（%.0f 秒）"
                    % (i + 1, u"通过" if ok else u"失败", time.time() - t0))
                if a.mode == "publish":
                    break
        finally:
            try:
                with io.open(a.out, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"mode": a.mode, "video": video,
                                        "stamp": stamp, "rounds": rounds},
                                       ensure_ascii=False, indent=1))
            except Exception:
                pass
            if not a.keep:
                try:
                    ctx.close()
                except Exception:
                    pass
            else:
                log(u"🖐 --keep：浏览器留着（9223），记得手动关")
                time.sleep(600)
    good = len([r for r in rounds if r["ok"]])
    log(u"\n%s %d/%d 遍通过" % (u"✅" if good == len(rounds) else u"⚠️",
                             good, len(rounds)))
    fails = {}
    for r in rounds:
        for s in r["steps"]:
            if not s["ok"]:
                fails[s["step"]] = fails.get(s["step"], 0) + 1
    if fails:
        log(u"失败分布：%s" % json.dumps(fails, ensure_ascii=False))
    return 0 if good == len(rounds) else 2


if __name__ == "__main__":
    sys.exit(main())
