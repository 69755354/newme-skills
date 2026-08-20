#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""视频号发布器（wujie frame 版）—— 唯一能稳定跑通的写法。

为什么要单独一个脚本（而不是继续修 newme_publish.py 的视频号分支）
------------------------------------------------------------------
视频号发布页是 wujie 微前端：**表单 DOM 只存在于沙箱 iframe 的代理 document 里**。
2026-08-20 实测三条硬结论：
  · 顶层文档 querySelectorAll('input') = 0 个；连 shadowRoot 深度遍历（2591 个元素）
    也找不到「将于」「请选择发表时间」这些字 —— 所以老代码里的 deepAll(document) 全是瞎的。
  · `page.locator("text=将于")`.count() = 0；`frame.locator(...)` 也是 0。
    Playwright 的选择器引擎查的是 iframe 的**真实** document（空的），
    而表单节点挂在 wujie 代理的 document 上。⇒ 定位器在视频号上一律不可用，
    以前那些"点到了"的日志有相当一部分是假阳性。
  · 唯一可行的三件套：
        fr = 找到 url 含 /micro/content/post/create 的 frame
        fr.evaluate(...)             读 DOM / 取坐标
        fr.evaluate_handle(...)      拿 ElementHandle，再用 handle.fill / set_input_files
        pg.mouse.click / pg.keyboard 做真实输入（坐标就是页面坐标，frameElement 是 0×0）

其它硬规则
----------
  · ⛔ 浏览器必须先把时区覆盖成 Asia/Shanghai：定时控件把输入当本地时间存成绝对
    时间戳，Mac 在迪拜的话打 19:30 存的是北京 23:30（已实测：同一条内容在
    Dubai/Shanghai/UTC 三种时区下列表页分别显示 15:30 / 19:30 / 11:30）。
  · 每个选项都必须有**能区分好坏状态的回读判据**，"我点了"不算。
    定时的真判据是 mp-date-picker 组件的 __vue__.pick 时间戳。
  · 位置只能选「不显示位置」：POI 按出口 IP 定位，搜迪拜出来的全是阿布坐比同名店，
    setGeolocationOverride 也没用。挂着「阿布扎比」是内容错误。

用法
----
  publish_weixin.py 方案.json --mode fill      # 填完就走，不留草稿（跑测试用）
  publish_weixin.py 方案.json --mode draft     # 填完存草稿
  publish_weixin.py 方案.json --mode publish   # 填完 + 过体检 + 真发表 + 列表页回读
  publish_weixin.py 方案.json --mode fill --times 10 --video 小样.mp4   # 稳定性测试
"""
import argparse
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.expanduser("~/NewMe/profiles/weixin")
CREATE = "https://channels.weixin.qq.com/platform/post/create"
LIST = "https://channels.weixin.qq.com/platform/post/list"
FRAME_MARK = "/micro/content/post/create"
LOGIN_WORDS = (u"扫码登录", u"登录视频号助手", u"请使用微信扫码", u"二维码登录")

PH_SHORT = u"填写短标题有机会获得更多流量"
PH_SCHED = u"请选择发表时间"
PH_TIME = u"请选择时间"
PH_POI = u"搜索附近位置"


def log(m):
    print(m)
    sys.stdout.flush()


# ── 基础三件套 ────────────────────────────────────────────────

def wx_frame(pg, timeout=120):
    u"""等到沙箱 frame 里真的有**能收视频的表单**再返回。

    坑一：goto 之后前 7~10 秒 pg.frames 里根本没有这个 frame（顶层文档只有侧栏
    那 20 个字），所以"找不到表单"多半只是等得不够。
    坑二：frame 刚出现时 input 数量已经够了，但视频 file input 还没挂上 ——
    第一次跑就栽在这：wx_frame 8 秒返回，紧接着报"找不到视频 file input"。
    所以判据直接用"我下一步真正要用的那个元素"：accept 含 video 的 file input。

    坑三（2026-08-20 复现三次）：**光看 pg.frames 会永远等不到。**
    同步版 Playwright 只在真正发起 API 调用时才去泵 CDP 事件队列，
    `pg.frames` 读的是本地那份 frame 树快照 —— 循环里只有 sleep + pg.frames 的话，
    frameAttached 事件一直没被处理，浏览器里 iframe 早就在了，脚本却看不见。
    所以每轮必须先打一次真调用（下面那句 pg.evaluate）把事件泵出来。"""
    t0 = time.time()
    last = "还没出现"
    while time.time() - t0 < timeout:
        try:
            pg.evaluate("()=>1")     # 泵事件，别删
        except Exception:
            pass
        for f in pg.frames:
            if FRAME_MARK in f.url:
                try:
                    d = f.evaluate("""()=>({n:document.querySelectorAll('input').length,
                        v:[...document.querySelectorAll('input[type=file]')]
                          .some(i=>(i.accept||'').includes('video'))})""")
                except Exception as e:
                    last = u"frame 在重建（%s）" % str(e)[:40]
                    continue
                last = u"%d 个 input，视频 input=%s" % (d["n"], d["v"])
                if d["n"] >= 10 and d["v"]:
                    return f
        time.sleep(1)
    raise RuntimeError(u"等不到能收视频的表单 frame（%s）" % last)


def wx_frame_any(pg, timeout=60):
    u"""上传完之后再取 frame（此时 file input 已被替换成封面预览，不能再拿它当判据）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            pg.evaluate("()=>1")     # 泵事件，别删（同上）
        except Exception:
            pass
        for f in pg.frames:
            if FRAME_MARK in f.url:
                try:
                    if f.evaluate("()=>document.querySelectorAll('input').length") >= 10:
                        return f
                except Exception:
                    pass
        time.sleep(1)
    raise RuntimeError(u"表单 frame 不见了")


def hnd(fr, js):
    u"""在 frame 里取 ElementHandle。定位器瞎，但 evaluate_handle 拿到的
    句柄照样能用 handle.fill / set_input_files / click —— 这是唯一的通路。"""
    h = fr.evaluate_handle(js)
    e = h.as_element()
    return e


def by_ph(fr, ph):
    return hnd(fr, "() => [...document.querySelectorAll('input,textarea')]"
                   ".find(i => (i.placeholder||'') === %s) || null"
                   % json.dumps(ph))


def xy(fr, js, dx=None):
    u"""取元素中心坐标（顺手 scrollIntoView）。dx 给定时就用左侧偏移点。"""
    return fr.evaluate("""(a) => { const e = (%s); if (!e) return null;
        e.scrollIntoView({block:'center'});
        const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return {w:0};
        return {x: Math.round(a===null? r.x + r.width/2 : r.x + a),
                y: Math.round(r.y + r.height/2), w: Math.round(r.width)};}""" % js,
                       dx)


def click_xy(pg, fr, js, dx=None, why="", wait=1.0):
    p = xy(fr, js, dx)
    if not p or not p.get("w"):
        return False, u"%s：元素不可见（%s）" % (why, p)
    pg.mouse.click(p["x"], p["y"])
    time.sleep(wait)
    return True, u"%s：点了 (%d,%d)" % (why, p["x"], p["y"])


def shot(pg, tag):
    try:
        pg.screenshot(path=os.path.join(ROOT, "wx_%s.png" % tag))
    except Exception:
        pass


# ── 各个字段：写 + 回读判据 ───────────────────────────────────

UP_AREA_JS = """(()=>{const i=[...document.querySelectorAll('input[type=file]')]
  .find(x=>(x.accept||'').includes('video')); if(!i) return null;
  let n=i; for(let k=0;k<5&&n;k++){const r=n.getBoundingClientRect();
    if(r.width>80&&r.height>40) return n; n=n.parentElement;} return null;})()"""


# ⛔ 上传完成的**真判据**在网络层，不在 DOM 里（2026-08-20 实测）：
#   · 页面上没有任何"上传中/百分比/上传成功"的字，`发表`按钮也永不禁用；
#   · `.cover-preview-wrap/.finder-tag-wrap` 3 秒就出现 —— 那只是本地解出了首帧。
#     45 MB 的片子照着它判"传完了"，紧接着点发表，平台静默不动、40 秒不跳页
#     （已复现：wx_publish_v4 第一次就死在这）。
#   · 字节走 Worker POST 到 finderassistancea.video.qq.com 的分片接口，
#     传完最后打一发 **completepartuploaddfs**。这个才是完成信号。
#     ⚠️ Worker 的请求 page 级事件收不到，必须挂在 **context** 上。
UP_HOST = "video.qq.com"
UP_DONE = "completepartupload"


def watch_upload(ctx):
    u"""在 context 上挂请求计数器，返回一个读快照的函数。"""
    st = {"live": 0, "done": 0, "last": 0.0}

    def req(r):
        if UP_HOST in r.url and ("partupload" in r.url or "upload" in r.url):
            st["live"] += 1
            st["last"] = time.time()

    def fin(r):
        if UP_HOST in r.url and ("partupload" in r.url or "upload" in r.url):
            st["live"] = max(0, st["live"] - 1)
            st["last"] = time.time()
            if UP_DONE in r.url:
                st["done"] += 1

    ctx.on("request", req)
    ctx.on("requestfinished", fin)
    ctx.on("requestfailed", fin)
    return st


def upload(pg, fr, video, up=None):
    u"""上传视频。

    ⛔ 不能用 handle.set_input_files：wujie 代理 document 里的节点，Playwright
    认成 detached element（"Cannot set input files to detached element"）。
    正解是真点上传区，用 file chooser 事件喂文件 —— 走的是浏览器原生通路，
    不依赖节点归属。"""
    p = xy(fr, UP_AREA_JS)
    if not p or not p.get("w"):
        return False, u"找不到可点的上传区（%s）" % p
    try:
        with pg.expect_file_chooser(timeout=20000) as fc:
            pg.mouse.click(p["x"], p["y"])
        fc.value.set_files(video)
    except Exception as e:
        return False, u"没等到文件选择器：%s" % str(e)[:80]
    t0 = time.time()
    seen_cover = 0.0
    while time.time() - t0 < 900:
        time.sleep(2)
        st = fr.evaluate(r"""() => {
          const t = document.body.innerText || '';
          return {done: !!document.querySelector('.finder-tag-wrap, .cover-preview-wrap'),
                  err: /上传失败|格式不支持|文件过大/.test(t)};}""")
        if st["err"]:
            return False, u"平台报上传失败"
        if st["done"] and not seen_cover:
            seen_cover = time.time()
        if not st["done"]:
            continue
        if up is None:
            # 没挂网络监听时退回旧行为（只对小样有效，真片会误判）
            return True, u"首帧就位（%.0f 秒，没有网络判据）" % (time.time() - t0)
        idle = time.time() - (up["last"] or t0)
        if up["done"] >= 1 and up["live"] == 0 and idle > 4:
            return True, u"传完了（%.0f 秒 · complete×%d · 首帧 %.0f 秒）" % (
                time.time() - t0, up["done"], seen_cover - t0)
    return False, u"上传超时（complete×%d 在飞 %d）" % (
        (up or {}).get("done", -1), (up or {}).get("live", -1))


DESC_JS = ("(document.querySelector('div.input-editor[contenteditable]')"
           " || document.querySelector('[contenteditable=\"true\"]'))")


def set_desc(pg, fr, text, topics):
    ok, why = click_xy(pg, fr, DESC_JS, why=u"点描述框", wait=0.4)
    if not ok:
        return False, why, 0
    pg.keyboard.type(text, delay=4)
    time.sleep(0.6)
    # 话题：**根本不需要下拉**。实测视频号是"打 #名字 再打一个空格"就地把文字
    # 变成真话题节点 <span class="hl topic" data-type="topic">#智能家居</span>。
    # 早先在等一个不存在的候选浮层，等不到就报"下拉命中 0/3"，白等 5 秒还误判。
    for t in (topics or []):
        pg.keyboard.type(u"\n#" + t, delay=40)
        time.sleep(0.5)
        pg.keyboard.type(u" ", delay=40)
        time.sleep(0.5)
    got = fr.evaluate("""() => {const e=document.querySelector('div.input-editor[contenteditable]')
        || document.querySelector('[contenteditable="true"]');
        if (!e) return null;
        return {len: e.innerText.length,
                topics: [...e.querySelectorAll('span[data-type="topic"]')]
                   .map(s=>s.innerText.trim().replace(/^#/,''))};}""")
    n = (got or {}).get("len", 0)
    tp = (got or {}).get("topics", [])
    want = topics or []
    ok = (n >= max(20, int(len(text) * 0.8))
          and len([x for x in want if x in tp]) == len(want))
    return ok, u"描述 %d 字（写了 %d）· 真话题节点 %d/%d %s" % (
        n, len(text), len([x for x in want if x in tp]), len(want), tp), n


def set_short_title(pg, fr, title):
    u"""短标题。先用原生 setter 清空（这一步是必须的：位置搜索那次把「迪拜」打进了
    短标题框，页面直接报「标题至少6个字」），再真键盘补一遍保证模型也更新。"""
    ok, why = click_xy(pg, fr, "[...document.querySelectorAll('input')]"
                               ".find(i=>(i.placeholder||'')===%s)" % json.dumps(PH_SHORT),
                       why=u"点短标题框", wait=0.3)
    if not ok:
        return False, why
    pg.keyboard.press("Meta+a")
    pg.keyboard.press("Backspace")
    pg.keyboard.type(title, delay=25)
    time.sleep(0.5)
    got = fr.evaluate("""() => {const e=[...document.querySelectorAll('input')]
        .find(i=>(i.placeholder||'')===%s); return e? e.value : '';}""" % json.dumps(PH_SHORT))
    return (got == title), u"短标题回读 %r" % got


def location_off(pg, fr):
    u"""选「不显示位置」。默认会挂出口 IP 所在地（阿布扎比），必须改掉。"""
    ok, why = click_xy(pg, fr, "document.querySelector('.position-display-wrap')",
                       why=u"展开位置", wait=1.4)
    if not ok:
        return False, why
    ok2, _ = click_xy(pg, fr, "[...document.querySelectorAll('input')]"
                              ".find(i=>(i.placeholder||'')===%s)" % json.dumps(PH_POI),
                      why=u"点搜索框", wait=0.3)
    if ok2:
        pg.keyboard.press("Meta+a")
        pg.keyboard.press("Backspace")
        time.sleep(1.4)
    ok, why = click_xy(pg, fr,
                       "[...document.querySelectorAll('.location-item')]"
                       ".find(x=>(x.innerText||'').trim()==='不显示位置')",
                       dx=40, why=u"点不显示位置", wait=1.4)
    if not ok:
        return False, why
    got = fr.evaluate("""() => {const e=document.querySelector('.position-display-wrap');
        return e? e.innerText.replace(/\\s+/g,' ').trim().slice(0,20) : '';}""")
    return (u"不显示位置" in got), u"位置回读 %r" % got


PICK_JS = """() => {const e=[...document.querySelectorAll('input')]
  .find(i=>(i.placeholder||'')==='%s'); if(!e) return null;
  let n=e; for(let i=0;i<8&&n;i++){
    if(n.__vue__ && n.__vue__.$options.name==='mp-date-picker') return n.__vue__.pick;
    n=n.parentElement;} return null;}""" % PH_SCHED


def set_schedule(pg, fr, bj_epoch_ms, hhmm, ymd):
    u"""定时。写法见文件头；判据是 mp-date-picker.pick 时间戳。"""
    ok, why = click_xy(pg, fr,
                       "[...document.querySelectorAll('label')]"
                       ".find(l=>l.querySelector('input[value=\"1\"]')"
                       "&&(l.innerText||'').trim()==='定时')",
                       why=u"切定时", wait=1.5)
    if not ok:
        return False, why
    if not fr.evaluate("""() => [...document.querySelectorAll('.form-item > .label')]
            .some(e=>e.innerText.trim()==='发表时间')"""):
        return False, u"切了定时但「发表时间」那行没渲染"
    ok, why = click_xy(pg, fr,
                       "[...document.querySelectorAll('input')]"
                       ".find(i=>(i.placeholder||'')==='%s')" % PH_SCHED,
                       dx=40, why=u"点开时间面板", wait=1.3)
    if not ok:
        return False, why
    d = xy(fr, "[...document.querySelectorAll('.weui-desktop-picker__table-row a')]"
               ".filter(a=>!/disabled/.test(a.className))"
               ".find(a=>a.innerText.trim()===%s)" % json.dumps(str(int(ymd[-2:]))))
    if not d or not d.get("w"):
        return False, u"日历里点不到 %s 号（%s）" % (ymd[-2:], d)
    pg.mouse.click(d["x"], d["y"])
    time.sleep(1.2)
    t = xy(fr, "[...document.querySelectorAll('input')]"
               ".find(i=>(i.placeholder||'')==='%s')" % PH_TIME)
    if not t or not t.get("w"):
        return False, u"内层时间小框没出来（%s）" % t
    # ⛔ 只能真键盘：往外层 readonly 框写值只改显示，模型还是默认 03:00
    pg.mouse.click(t["x"], t["y"])
    time.sleep(0.4)
    pg.keyboard.press("Meta+a")
    pg.keyboard.type(hhmm, delay=90)
    time.sleep(0.5)
    pg.keyboard.press("Enter")
    time.sleep(1.0)
    fr.evaluate("()=>{const l=document.querySelector('.form-item > .label'); if(l) l.click();}")
    time.sleep(0.8)
    pick = fr.evaluate(PICK_JS)
    disp = fr.evaluate("""() => {const e=[...document.querySelectorAll('input')]
        .find(i=>(i.placeholder||'')===%s); return e? e.value:'';}""" % json.dumps(PH_SCHED))
    ok = (pick == bj_epoch_ms)
    return ok, u"定时模型 pick=%s（期望 %s）显示 %r" % (pick, bj_epoch_ms, disp)


# ⚠️ 假判据订正（2026-08-20 实测）：创建页一加载就预渲染了 **48 个**
# .weui-desktop-dialog__wrp（切换视频号、商品、绑定、原创权益…），全部 display:none。
# 所以「有没有 wrp 的 display!=='none'」看着像个判据，其实随便一个别的壳子
# 被平台设成 block 就会误报。真正的可见弹窗必须**同时**有面积。
VIS_DIALOG_JS = r"""() => {
  const xs = [...document.querySelectorAll('.weui-desktop-dialog__wrp')]
    .filter(x => {
      const r = x.getBoundingClientRect();
      return getComputedStyle(x).display !== 'none' && r.width > 200 && r.height > 100;
    });
  if (!xs.length) return null;
  const x = xs[xs.length - 1], r = x.getBoundingClientRect();
  return {txt: (x.innerText||'').replace(/\s+/g,' ').trim().slice(0,120),
          x: Math.round(r.x), y: Math.round(r.y),
          w: Math.round(r.width), h: Math.round(r.height),
          html: x.outerHTML.slice(0, 6000),
          btns: [...x.querySelectorAll('button,a.weui-desktop-btn')].map(b => {
            const q = b.getBoundingClientRect();
            return {t: (b.innerText||'').replace(/\s+/g,' ').trim(),
                    cls: (b.className||'').toString().slice(0,60),
                    dis: !!b.disabled,
                    x: Math.round(q.x + q.width/2), y: Math.round(q.y + q.height/2),
                    vis: q.width > 2 && q.height > 2};
          }).filter(b => b.vis),
          boxes: [...x.querySelectorAll('input[type=checkbox]')].map(c => {
            const q = c.getBoundingClientRect();
            const lab = c.closest('label');
            return {checked: c.checked, dis: !!c.disabled,
                    lab: (lab? lab.innerText : '').replace(/\s+/g,' ').trim().slice(0,40),
                    x: Math.round(q.x + q.width/2) || Math.round(q.x),
                    y: Math.round(q.y + q.height/2) || Math.round(q.y),
                    vis: q.width > 2 && q.height > 2};
          })};
}"""


def vis_dialog(fr):
    try:
        return fr.evaluate(VIS_DIALOG_JS)
    except Exception:
        return None


def dump_dialog(d, tag):
    u"""把挡路的弹窗原样存盘，下一轮不用再猜它长什么样。"""
    if not d:
        return
    p = os.path.join(ROOT, "_pipeline", "wx_dialog_%s.html" % tag)
    try:
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(u"<!-- %s -->\n%s" % (d.get("txt", ""), d.get("html", "")))
    except Exception:
        pass


# 关掉一个挡路的弹窗：优先点「我知道了/确定/同意/关闭」，再退而求其次点 ×。
CLOSE_BTN_RE = u"我知道了|知道了|确定|确认|好的|同意|完成|关闭"


def close_dialog(pg, fr, tries=3):
    u"""把当前可见弹窗关掉。返回 (关掉了吗, 说明)。"""
    why = []
    for _ in range(tries):
        d = vis_dialog(fr)
        if not d:
            return True, u"没有弹窗" if not why else u" / ".join(why)
        why.append(u"弹窗 %r" % d["txt"][:24])
        hit = None
        for b in d["btns"]:
            if b["dis"]:
                continue
            if re.search(CLOSE_BTN_RE, b["t"] or ""):
                hit = b
                break
        if hit is None:
            x = fr.evaluate(r"""() => {const c=[...document.querySelectorAll(
                '.weui-desktop-dialog__wrp .weui-desktop-dialog__close-btn,'
                +'.weui-desktop-dialog__wrp .weui-desktop-icon__close')]
                .find(e=>{const r=e.getBoundingClientRect();
                          return r.width>2 && r.height>2;});
              if(!c) return null; const r=c.getBoundingClientRect();
              return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};}""")
            if x:
                hit = {"t": u"×", "x": x["x"], "y": x["y"]}
        if hit is None:
            pg.keyboard.press("Escape")
            time.sleep(1.2)
            continue
        pg.mouse.click(hit["x"], hit["y"])
        why.append(u"点了 %r" % hit["t"])
        time.sleep(1.5)
    return (vis_dialog(fr) is None), u" / ".join(why)


def declare_original(pg, fr):
    u"""声明原创。第一次会弹「原创声明须知」，必须在**弹窗内部**找同意勾选和按钮 ——
    早先按"y>300 的可见 checkbox"选，选到的是弹窗背后那个页面勾选框，
    点它等于又把弹窗打开一次，然后回读同一个框，报成功 —— 一个自己造的假阳性。"""
    st = fr.evaluate("""() => {const c=document.querySelector('.ant-checkbox-input');
        if(!c) return null; const lab=c.closest('label');
        return {checked:c.checked, disabled:c.disabled,
                why:(lab? lab.innerText:'').replace(/\\s+/g,' ').trim().slice(0,40)};}""")
    if st is None:
        return False, u"找不到原创勾选框"
    if st["checked"]:
        return True, u"原创已经是勾上的"
    if st["disabled"]:
        # 实测：4 秒的测试片会让整行变灰，写着「视频时长小于5秒，不能使用原创声明」。
        # 这不是脚本的错，是素材不合格 —— 必须原样报出来，别让它变成"点不到"。
        return False, u"平台禁用了原创声明：%s" % st["why"]
    ok, why = click_xy(pg, fr, "document.querySelector('.ant-checkbox-input')",
                       why=u"点原创勾选", wait=1.0)
    if not ok:
        return False, why
    # 弹窗不是马上出来的（实测有时 3 秒后才渲染）。早先 1.6 秒就去找，
    # 找不到就 break，结果既没勾上也没弹窗，报"原创没勾上"。改成轮询 12 秒。
    ck = "() => {const c=document.querySelector('.ant-checkbox-input');" \
         " return c? c.checked : null;}"
    note = []
    for _ in range(12):
        checked = fr.evaluate(ck)
        d = vis_dialog(fr)
        if checked or d:
            break
        time.sleep(1)
    for i in range(4):
        d = vis_dialog(fr)
        if not d:
            break
        note.append(u"弹窗%r" % d["txt"][:18])
        dump_dialog(d, "orig%d" % i)
        # 弹窗里若有「我已阅读并同意/不再提醒」之类的勾选，先勾（只在弹窗范围内找，
        # 早先按"y>300 的可见 checkbox"选，选到的是弹窗背后页面上的那个，
        # 点它等于又把弹窗打开一遍，然后回读同一个框报成功 —— 自造的假阳性）。
        for b in d["boxes"]:
            if b["vis"] and not b["checked"] and not b["dis"] \
                    and u"不再提醒" not in b["lab"]:
                pg.mouse.click(b["x"], b["y"])
                note.append(u"勾了%r" % b["lab"][:12])
                time.sleep(0.6)
        hit = None
        for pat in (u"^(声明原创|确定|确认|同意|好的)$", u"声明原创|确定|同意",
                    CLOSE_BTN_RE):
            for b in d["btns"]:
                if b["dis"]:
                    continue
                if re.search(pat, b["t"] or ""):
                    hit = b
                    break
            if hit:
                break
        if hit is None:
            pg.keyboard.press("Escape")
            note.append(u"没找到按钮→Esc")
            time.sleep(1.2)
            continue
        pg.mouse.click(hit["x"], hit["y"])
        note.append(u"点%r" % hit["t"][:10])
        time.sleep(1.8)
    checked = fr.evaluate(ck)
    left = vis_dialog(fr)
    if left:
        dump_dialog(left, "orig_left")
    ok = bool(checked) and left is None
    return ok, u"原创=%s 残留弹窗=%s · %s" % (
        checked, (left["txt"][:24] if left else u"无"), u" ".join(note))


# ── 起飞前体检 + 发表 + 列表页回读 ───────────────────────────

def preflight(fr, want):
    got = fr.evaluate(r"""(phs) => {
      const q=s=>document.querySelector(s);
      const inp=ph=>{const e=[...document.querySelectorAll('input')]
        .find(i=>(i.placeholder||'')===ph); return e? e.value : null;};
      const d=q('div.input-editor[contenteditable]')||q('[contenteditable="true"]');
      const cb=q('.ant-checkbox-input');
      const pos=q('.position-display-wrap');
      const btn=[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='发表');
      return {desc_len: d? d.innerText.length : 0,
              short: inp(phs[0]), sched: inp(phs[1]),
              orig: cb? cb.checked : null,
              loc: pos? pos.innerText.replace(/\s+/g,' ').trim().slice(0,12) : '',
              cover: !!q('.cover-img-vertical'),
              modal: !![...document.querySelectorAll('.weui-desktop-dialog__wrp')]
                 .find(x=>{const r=x.getBoundingClientRect();
                   return getComputedStyle(x).display!=='none' &&
                          r.width>200 && r.height>100;}),
              btn: !!btn};}""", [PH_SHORT, PH_SCHED])
    got["pick"] = fr.evaluate(PICK_JS)
    bad = []
    if not got["cover"]:
        bad.append(u"视频/封面没就位")
    if got["desc_len"] < 50:
        bad.append(u"描述只有 %d 字" % got["desc_len"])
    if not got["short"] or len(got["short"]) < 6:
        bad.append(u"短标题 %r 不足 6 字" % got["short"])
    if want.get("pick") and got["pick"] != want["pick"]:
        bad.append(u"定时模型 %s ≠ 期望 %s" % (got["pick"], want["pick"]))
    if want.get("orig") and not got["orig"]:
        bad.append(u"原创没勾上")
    if got["modal"]:
        bad.append(u"有弹窗盖着")
    if not got["btn"]:
        bad.append(u"找不到发表按钮")
    return (not bad), bad, got


def do_publish(pg, fr):
    ok, why = click_xy(pg, fr,
                       "[...document.querySelectorAll('button')]"
                       ".find(b=>b.innerText.trim()==='发表')",
                       why=u"点发表", wait=0)
    if not ok:
        return False, why
    # 点了不跳页时，平台通常在弹窗里写了原因（视频还在传 / 内容待补全 / 风控）。
    # 之前只报「40 秒没跳页」，等于把唯一的线索扔了。
    seen = u""
    for i in range(90):
        time.sleep(1)
        if "/post/list" in pg.url:
            return True, u"跳到列表页（%d 秒）" % (i + 1)
        if i % 3 == 0:
            for f in (fr, pg):
                try:
                    d = vis_dialog(f)
                except Exception:
                    d = None
                if d and d["txt"] and d["txt"] != seen:
                    seen = d["txt"]
                    dump_dialog(d, "publish")
                    log(u"       发表后弹窗：%s" % seen[:100])
    return False, u"90 秒没跳页%s，URL=%s" % (
        (u"（弹窗说：%s）" % seen[:80]) if seen else u"", pg.url)


def verify_list(pg, want_text, tries=3):
    u"""唯一算数的最终判据：列表页那行「将于…发表」。
    ⛔ 列表页也在 wujie frame 里，body 文字要遍历 frame 才读得到。"""
    for _ in range(tries):
        for f in pg.frames:
            try:
                t = f.evaluate("()=>document.body.innerText||''")
            except Exception:
                continue
            if u"将于" in t:
                import re
                m = re.findall(u"将于[^\n]{0,30}", t)
                return (want_text in (m[0] if m else "")), (m[0] if m else "")
        time.sleep(3)
    return False, u"列表页读不到「将于…」"


# ── 一次完整流程 ──────────────────────────────────────────────

def one_round(pg, plan, video, mode, target, up=None):
    cfg = plan.get("weixin") or {}
    steps = []

    def rec(name, ok, why):
        steps.append({"step": name, "ok": bool(ok), "why": why})
        log(u"    %s %-8s %s" % (u"✅" if ok else u"❌", name, why))
        return ok

    pg.goto(CREATE, wait_until="domcontentloaded")
    time.sleep(2)
    body = ""
    try:
        body = pg.inner_text("body", timeout=8000) or ""
    except Exception:
        pass
    if "login" in pg.url.lower() or [w for w in LOGIN_WORDS if w in body]:
        rec(u"登录", False, u"掉登录了，需要手机扫码")
        return False, steps
    fr = wx_frame(pg)
    rec(u"表单", True, u"沙箱 frame 就绪")

    if up is not None:                 # 每轮重新计数，别把上一轮的 complete 算进来
        up["live"] = 0
        up["done"] = 0
        up["last"] = 0.0
    if not rec(u"上传", *upload(pg, fr, video, up)):
        shot(pg, "90_upload")
        return False, steps
    ok, why, _ = set_desc(pg, fr, cfg.get("desc") or "", cfg.get("topics") or [])
    rec(u"描述", ok, why)
    rec(u"短标题", *set_short_title(pg, fr, cfg.get("short_title") or ""))
    rec(u"位置", *location_off(pg, fr))
    if cfg.get("schedule", True) and target:
        rec(u"定时", *set_schedule(pg, fr, target["pick"], target["hhmm"], target["ymd"]))
    if cfg.get("declare_original"):
        rec(u"原创", *declare_original(pg, fr))

    # 体检前扫一遍弹窗：平台会在填表过程中随机弹「以下事项需注意」「原创权益」这类
    # 壳子，盖住发表按钮。留着它去点发表 = 静默失败。
    if vis_dialog(fr):
        rec(u"清弹窗", *close_dialog(pg, fr))

    want = {"pick": target["pick"] if (target and cfg.get("schedule", True)) else None,
            "orig": bool(cfg.get("declare_original"))}
    ok, bad, got = preflight(fr, want)
    rec(u"体检", ok, u"通过" if ok else u" / ".join(bad))
    log(u"       现场：%s" % json.dumps(got, ensure_ascii=False))
    if not ok:
        shot(pg, "91_preflight")
        return False, steps

    if mode == "fill":
        pg.once("dialog", lambda d: d.accept())
        pg.goto(LIST, wait_until="domcontentloaded")
        time.sleep(2)
        rec(u"收尾", True, u"fill 模式：不发表、不留草稿")
        return True, steps
    if mode == "draft":
        ok2, why2 = click_xy(pg, fr, "[...document.querySelectorAll('button')]"
                                     ".find(b=>b.innerText.trim()==='保存草稿')",
                             why=u"存草稿", wait=3)
        return rec(u"草稿", ok2, why2), steps

    if not rec(u"发表", *do_publish(pg, fr)):
        shot(pg, "92_publish")
        return False, steps
    want_txt = u"%s发表" % target["hhmm"] if target else u"发表"
    ok3, txt = verify_list(pg, want_txt)
    rec(u"回读", ok3, u"列表页：%s" % txt)
    shot(pg, "99_done")
    return ok3, steps


def bj_target(hhmm, min_ahead=45):
    u"""目标发表时刻（北京钟点）。浏览器时区会被覆盖成上海，所以这里直接算上海时间。
    不够 min_ahead 分钟就顺延到明天 —— 定时时间太近平台会静默拒绝。"""
    import datetime
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    hh, mm = [int(x) for x in (hhmm or "19:30").split(":")]
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if (t - now).total_seconds() < min_ahead * 60:
        t += datetime.timedelta(days=1)
    epoch = int((t - datetime.datetime(1970, 1, 1)).total_seconds() - 8 * 3600) * 1000
    return {"pick": epoch, "hhmm": t.strftime("%H:%M"), "ymd": t.strftime("%Y-%m-%d"),
            "text": t.strftime(u"%Y年%m月%d日 %H:%M")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--mode", default="fill", choices=["fill", "draft", "publish"])
    ap.add_argument("--video", default="")
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("--keep", action="store_true",
                    help=u"跑完不关浏览器，留着用 CDP 9222 接进去查 DOM")
    ap.add_argument("--out", default=os.path.join(ROOT, "_pipeline", "wx_test.json"))
    a = ap.parse_args()

    with io.open(os.path.expanduser(a.plan), encoding="utf-8") as f:
        plan = json.load(f)
    video = os.path.expanduser(a.video or plan.get("video") or "")
    if not os.path.isfile(video):
        log(u"❌ 视频不在：%s" % video)
        return 1
    target = bj_target((plan.get("weixin") or {}).get("schedule_bj_time")
                       or plan.get("schedule_bj_time"))
    log(u"视频 %s（%.1f MB）· 模式 %s · 跑 %d 遍"
        % (os.path.basename(video), os.path.getsize(video) / 1e6, a.mode, a.times))
    log(u"定时目标 北京 %s（pick=%s）" % (target["text"], target["pick"]))

    from playwright.sync_api import sync_playwright
    rounds = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE, channel="chrome", headless=False, no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled",
                  "--remote-debugging-port=9222"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(45000)
        # ⛔ 这一行不能省：不覆盖时区，定时会差 4 小时（迪拜→北京）
        cdp = ctx.new_cdp_session(pg)
        cdp.send("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
        log(u"时区已覆盖：%s" % pg.evaluate("()=>new Date().toString().slice(0,33)"))
        # 字节是 Worker 传的，只有 context 级事件收得到；这是"传完了"的唯一真判据
        up = watch_upload(ctx)
        try:
            for i in range(a.times):
                log(u"\n── 第 %d/%d 遍 ─────────────────────" % (i + 1, a.times))
                t0 = time.time()
                try:
                    ok, steps = one_round(pg, plan, video, a.mode, target, up)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    ok, steps = False, [{"step": "fatal", "ok": False,
                                         "why": str(e)[:200]}]
                rounds.append({"i": i + 1, "ok": ok, "sec": round(time.time() - t0, 1),
                               "steps": steps})
                log(u"   → 第 %d 遍 %s（%.0f 秒）"
                    % (i + 1, u"通过" if ok else u"失败", time.time() - t0))
                if a.mode == "publish":
                    break
        finally:
            try:
                with io.open(a.out, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"mode": a.mode, "video": video,
                                        "target": target, "rounds": rounds},
                                       ensure_ascii=False, indent=1))
            except Exception:
                pass
            if a.mode != "publish" and not a.keep:
                try:
                    ctx.close()
                except Exception:
                    pass
            elif a.keep:
                log(u"🖐 --keep：浏览器留着，用 9222 接进来查（记得手动关）")
                time.sleep(600)
    good = len([r for r in rounds if r["ok"]])
    log(u"\n%s %d/%d 遍通过" % (u"✅" if good == len(rounds) else u"⚠️", good, len(rounds)))
    # 哪一步最爱掉
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
