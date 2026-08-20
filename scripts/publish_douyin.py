#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""抖音发布器（专机专用，判据全部有阳性对照）。

用法：
  publish_douyin.py 方案.json --mode fill             # 填完就走，不发布
  publish_douyin.py 方案.json --mode publish          # 真发（定时）
  publish_douyin.py 方案.json --mode fill --times 10  # 稳定性连测
  可加 --video x.mp4 覆盖方案里的片子

—— 2026-08-20 四轮探针实测得到的地基（改代码前先读）——
· 表单是 **light DOM**（semi-design + 自研 editor-kit），locator 可用。
  喂片后 URL 从 /content/upload 跳到 /content/post/video。
· ⛔ 上传完成的判据必须三条一起看：
  真片 43 MB 的实测轨迹是
    0~19s   「已上传：x MB/43.3MB」百分比往上走
    19.8s   进度文字消失、**「重新上传」出现**，但同时开始「检测中 N%」
    ~200s   「检测中」才消失
  所以「重新上传出现」= **假判据**（19.8 秒就为真，字节其实还在转码检测）。
  真判据 = 无「已上传 x/y MB」 且 无「检测中 N%」 且 有「重新上传」 且 标题框在。
  阳性对照：小片子也一定先经过「检测中」，脚本会记录有没有见到未就绪态。
· ⛔ 抖音表单很长（页高 1474 / 视口 879），`getBoundingClientRect().y` 常是
  1200+ 这种**视口外**的值。直接 `mouse.click(x, y)` 等于点空气（已踩：
  定时单选点了没反应）。抖音是 light DOM，一律先 `scroll_into_view_if_needed()`
  或 JS `scrollIntoView`，点之前必须验 `inView`。
· 定时：点 `[class*=radio]:has-text('定时发布')` → 出现
  `input.semi-input[placeholder='日期和时间']`（**非只读**，默认值 = 现在+2 小时）。
  Meta+a → 真键盘打 `YYYY-MM-DD HH:MM` → Enter → 失焦，回读一致，滚动后也不回滚。
  平台规则：只支持 **2 小时后 ~ 14 天内**。
· ⛔ 时区：一律 CDP 覆盖 Asia/Shanghai（Mac 在迪拜，差 4 小时）。
  自检：`new Date()` 必须是 GMT+0800。
· 话题：正文里打 `#名字` → 浮层 `[class*=mention-suggest-mount-dom]`，
  条目名在 `[class*=tag-hash-view-name]`。用**回车**采纳（和小红书同理，
  鼠标点会把焦点带出编辑器）。采纳后正文里出现 `#名字` 节点。
· 抖音**没有**「声明原创」这种开关。「自主声明」下拉是「内容由 AI 生成/虚构演绎」
  之类的风险声明，勾了反而降权 —— 所以方案里的 declare_original 在抖音**故意不执行**，
  如实记为「平台无此项」，不算失败。
· 发布按钮 `button.button-dhlUZE.primary-cECiOJ`（文字正好是「发布」），
  旁边紧挨着「暂存离开」（存草稿跳走）。所以只认文字完全等于「发布」的那个 button，
  且滚进视口、验 inView 之后再点。⚠️ 这个按钮**任何时候都可点**，平台零保险，
  体检不过绝不能点。
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import sys
import time

import profile_guard            # Chrome profile 开场/收尾的唯一实现（禁双开、防残留）
import schedule_target          # 定时时刻的唯一实现（三平台共用，含各自上限）

ROOT = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.expanduser("~/NewMe/profiles/douyin")
HOME = "https://creator.douyin.com/creator-micro/content/upload"
MANAGE = "https://creator.douyin.com/creator-micro/content/manage"
LOGIN_WORDS = [u"扫码登录", u"手机号登录", u"登录抖音"]

FILE_SEL = "input[type=file][accept*=video]"
TITLE_SEL = "input.semi-input[placeholder*='填写作品标题']"
BODY_SEL = "div.zone-container"
DT_SEL = "input.semi-input[placeholder='日期和时间']"


def log(m):
    if isinstance(m, bytes):
        m = m.decode("utf-8")
    sys.stdout.write(m + "\n")
    sys.stdout.flush()


def shot(pg, tag):
    try:
        p = os.path.join(ROOT, "_pipeline", "dy_%s.png" % tag)
        pg.screenshot(path=p, full_page=True)
        log(u"       截图 %s" % os.path.basename(p))
    except Exception:
        pass


# ── 判据 ────────────────────────────────────────────────────────

STATE_JS = r"""() => {
  const cut=(s,n)=>(s||'').toString().replace(/\s+/g,' ').trim().slice(0,n||60);
  const b=(document.body.innerText||'').replace(/\s+/g,' ');
  const m=s=>(b.match(s)||[''])[0];
  const t=document.querySelector("input.semi-input[placeholder*='填写作品标题']");
  const ed=document.querySelector('div.zone-container');
  const dtin=document.querySelector("input.semi-input[placeholder='日期和时间']");
  // 定时/立即 两个单选的状态
  const radios={};
  [...document.querySelectorAll('[class*=radio]')].forEach(e=>{
    const tx=cut(e.innerText,10);
    if((tx==='定时发布'||tx==='立即发布'||tx==='公开'||tx==='好友可见')
        && e.children.length<4 && e.getAttribute('data-checked')!==null)
      radios[tx]=e.getAttribute('data-checked');
  });
  // 话题节点的真形态（实测 HTML）：
  //   <span data-fake-text=" " contenteditable="false">
  //     <div data-mention="#"> #全屋智能 </div></span>
  // 所以判据 = 正文里 div[data-mention] 的文本集合。纯文字 #xxx 没有这层壳。
  let topics=[];
  if(ed){
    const seen=new Set();
    [...ed.querySelectorAll('div[data-mention]')].forEach(e=>{
      const tx=(e.innerText||'').replace(/\s+/g,'').trim();
      if(!/^#\S/.test(tx)||tx.length>24||seen.has(tx)) return;
      seen.add(tx); topics.push(tx);
    });
  }
  const modal=[...document.querySelectorAll('[class*=semi-modal-content],[class*=modal-content],[role=dialog]')]
    .filter(x=>{const r=x.getBoundingClientRect();
      return r.width>200&&r.height>100&&getComputedStyle(x).display!=='none';})
    .map(x=>cut(x.innerText,140));
  let pub=null;
  const pb=[...document.querySelectorAll('button')]
    .filter(e=>(e.innerText||'').replace(/\s+/g,'')==='发布')[0];
  if(pb){const r=pb.getBoundingClientRect();
    pub={dis:!!pb.disabled, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
         w:Math.round(r.width), h:Math.round(r.height),
         inView:r.top>=0&&r.bottom<=innerHeight};}
  return {
    url: location.href,
    up: m(/已上传[：:]?\s*[\d.]+\s*MB\s*\/\s*[\d.]+\s*MB/),
    det: m(/检测中\s*\d+\s*%/),
    reup: b.includes('重新上传'),
    fail: b.includes('上传失败')||b.includes('视频审核不通过'),
    title: t?t.value:null,
    hasForm: !!t,
    bodyLen: ed?(ed.innerText||'').replace(/\s+/g,'').replace(/​/g,'').length:null,
    bodyTxt: ed?cut(ed.innerText,220):null,
    bodyHtml: ed?ed.innerHTML.replace(/\s+/g,' ').slice(-800):null,
    topics: topics,
    sched: dtin?dtin.value:null,
    radios: radios,
    // 位置的**值**在「添加标签」那一行右边的输入框里（左边 select 显示的是标签类型「位置」，
    // 拿它当回读判据永远读到「位置」两个字 —— 已踩）。那个输入框没有 placeholder。
    poi: (()=>{const i=[...document.querySelectorAll('input.semi-input')]
            .filter(e=>!e.placeholder)[0]; return i?cut(i.value,40):null;})(),
    modal: modal,
    pub: pub,
  };
}"""


def state(pg):
    return pg.evaluate(STATE_JS)


def wait_upload_area(pg, timeout=60):
    for _ in range(timeout):
        time.sleep(1)
        try:
            pg.evaluate("()=>1")
            if pg.query_selector(FILE_SEL):
                return True
        except Exception:
            pass
    return False


def upload(pg, video, timeout=900):
    u"""喂文件，等「已上传 x/y」和「检测中 N%」都消失、且「重新上传」在。

    ⛔「重新上传」单独出现不算传完（43 MB 实测 19.8 秒就出现了，此时检测中 1%）。"""
    try:
        pg.set_input_files(FILE_SEL, video)
    except Exception as e:
        return False, u"喂文件失败：%s" % str(e)[:90]
    t0 = time.time()
    saw_busy = False
    last = ""
    while time.time() - t0 < timeout:
        time.sleep(2)
        try:
            s = state(pg)
        except Exception:
            continue
        last = u"up=%r det=%r 重新上传=%s" % (s["up"], s["det"], s["reup"])
        if s["up"] or s["det"]:
            saw_busy = True            # 阳性对照：确实经过了未就绪态
        if s["fail"]:
            return False, u"平台报上传失败/审核不通过"
        if s["hasForm"] and s["reup"] and not s["up"] and not s["det"]:
            return True, u"传完了（%.0f 秒 · 经过未就绪态=%s）" % (
                time.time() - t0, u"是" if saw_busy else u"没看到")
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
    pg.keyboard.type(title[:30], delay=25)
    time.sleep(0.6)
    got = state(pg)["title"] or ""
    return (got.strip() == title[:30].strip()), u"回读 %r" % got


SUG_JS = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const mount=[...document.querySelectorAll("[class*=mention-suggest-mount-dom]")]
    .filter(e=>{const r=e.getBoundingClientRect();return r.width>80&&r.height>20;})[0];
  if(!mount) return null;
  const items=[...mount.querySelectorAll("[class*=tag-hash-view-name]")]
    .map(e=>cut(e.innerText)).filter(t=>t);
  return {n: items.length, items: items.slice(0, 10)};
}"""


def pick_topic(pg, name, tries=12):
    u"""等 mention 浮层出来，用回车采纳。名字不在第一条时先 ArrowDown 走过去。

    ⛔ 别用鼠标点候选（小红书那边实测会把焦点带出编辑器，后面的话题全打不进去）。"""
    for _ in range(tries):
        time.sleep(0.5)
        try:
            d = pg.evaluate(SUG_JS)
        except Exception as e:
            return None, [str(e)[:60]]
        if not d or not d["items"]:
            continue
        items = d["items"]
        idx = None
        for i, t in enumerate(items):
            if t == name:
                idx = i
                break
        if idx is None:
            for i, t in enumerate(items):
                if t.startswith(name):
                    idx = i
                    break
        if idx is None:
            # ⛔ 别在这里 return：浮层常先显示**上一次查询的残留候选**
            #   （实测打 #智能家居 时列表里还是「别墅…」那一批），
            #   直接放弃 = 白白降级。要继续等它刷新成本次查询的结果。
            continue
        for _ in range(idx):
            pg.keyboard.press("ArrowDown")
            time.sleep(0.15)
        pg.keyboard.press("Enter")
        time.sleep(0.8)
        return items[idx], items
    return None, []


def set_body(pg, body, topics):
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
    picked, dump = [], []
    if topics:
        pg.keyboard.press("Enter")
        for name in topics:
            nm = (name or "").lstrip("#").strip()
            if not nm:
                continue
            pg.keyboard.type(" ", delay=20)
            pg.keyboard.type("#" + nm, delay=60)
            hit, cands = pick_topic(pg, nm)
            dump.append({"topic": nm, "hit": hit, "cands": cands[:6]})
            if hit:
                picked.append(nm)
            else:
                pg.keyboard.type(" ", delay=20)
            time.sleep(0.5)
    s = state(pg)
    real = len(s["topics"] or [])
    want = len([t for t in (topics or []) if (t or "").strip()])
    ok = (s["bodyLen"] or 0) > 30 and real >= want
    return ok, u"正文 %s 字 · 真话题节点 %d/%d %s" % (s["bodyLen"], real, want,
                                              picked), \
        {"cands": dump, "nodes": s["topics"], "html": s["bodyHtml"]}


def click_in_view(pg, sel, last=False):
    u"""抖音表单比视口高，点之前必须滚进视口。返回 (ok, 说明)。"""
    loc = pg.locator(sel)
    if loc.count() == 0:
        return False, u"找不到 %s" % sel
    el = loc.last if last else loc.first
    try:
        el.scroll_into_view_if_needed(timeout=8000)
        time.sleep(0.4)
        el.click(timeout=8000)
        return True, u"点了 %s" % sel
    except Exception as e:
        return False, u"点 %s 失败：%s" % (sel, str(e)[:70])


def set_schedule(pg, stamp):
    ok, why = click_in_view(pg, "[class*=radio]:has-text('定时发布')", last=True)
    if not ok:
        return False, why
    time.sleep(2)
    s = state(pg)
    if s["radios"].get(u"定时发布") != "true":
        return False, u"定时单选没勾上（%s）" % json.dumps(s["radios"],
                                                  ensure_ascii=False)
    if s["sched"] is None:
        return False, u"没出现「日期和时间」输入框"
    default = s["sched"]
    e = pg.locator(DT_SEL).first
    try:
        e.scroll_into_view_if_needed(timeout=8000)
        e.click(timeout=8000)
    except Exception as ex:
        return False, u"点不到时间框：%s" % str(ex)[:70]
    time.sleep(0.8)
    pg.keyboard.press("Meta+a")
    pg.keyboard.type(stamp, delay=45)
    time.sleep(0.5)
    pg.keyboard.press("Enter")
    time.sleep(1.2)
    pg.mouse.click(300, 400)          # 点空白收面板
    time.sleep(1.0)
    got = (state(pg)["sched"] or "").strip()
    return got == stamp, u"时间框回读 %r（期望 %r，默认曾是 %r）" % (got, stamp, default)


# 位置搜索框 = 点开位置行后多出来的那个**没有 placeholder** 的 semi-input
POI_BOX_JS = r"""() => {
  const i=[...document.querySelectorAll('input.semi-input')].filter(e=>!e.placeholder)[0];
  if(!i) return null; const r=i.getBoundingClientRect();
  return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
          inView:r.top>=0&&r.bottom<=innerHeight};
}"""

# 结果条：[class*=option-v2]，名字在 [class*=detail-v2]、地址在 [class*=address-]
POI_JS = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  return [...document.querySelectorAll("[class*=option-v2]")].map(e=>{
    const r=e.getBoundingClientRect();
    const nm=e.querySelector("[class*=detail-v2]");
    const ad=e.querySelector("[class*=address-]");
    return {name: cut(nm?nm.innerText:''), addr: cut(ad?ad.innerText:'').slice(0,60),
            x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
            top:Math.round(r.top), h:Math.round(r.height),
            inView:r.top>=0&&r.bottom<=innerHeight};
  }).filter(o=>o.name).slice(0, 12);
}"""


# 选完之后 placeholder-less input 会被清空，真值落在位置行本身，所以两处都读
POI_READ_JS = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const row=[...document.querySelectorAll("[class*=anchor-item]")]
    .map(e=>cut(e.innerText)).join(' | ').slice(0,240);
  const i=[...document.querySelectorAll('input.semi-input')]
    .filter(e=>!e.placeholder)[0];
  return {row:row, val:i?cut(i.value).slice(0,60):''};
}"""


def set_location(pg, want):
    u"""抖音是三平台里**唯一能挂上真迪拜位置**的（POI 按出口 IP 定位，我们本来就在迪拜）。
    实测搜「Dubai」第一条就是城市级 POI：名字 Dubai / 地址 دبي, الإمارات العربية المتحدة。
    搜中文「迪拜」给的是兰博基尼未来城、迪拜之窗 MCN 这些具体商户 —— 片子不是在那拍的，
    挂上去等于报错地点，所以**只认名字就是 Dubai/迪拜 的城市级那条**，挑不到就留空。"""
    if not want:
        return True, u"方案没要求位置"
    ok, why = click_in_view(pg, "[class*=anchor-item]")
    if not ok:
        return True, u"降级：找不到位置入口（%s），留空" % why[:40]
    time.sleep(1.2)
    box = pg.evaluate(POI_BOX_JS)
    if not box:
        return True, u"降级：没有位置搜索框，留空"
    pg.mouse.click(box["x"], box["y"])
    pg.keyboard.press("Meta+a")
    pg.keyboard.type("Dubai", delay=110)
    cands = []
    for _ in range(10):
        time.sleep(1)
        try:
            cands = pg.evaluate(POI_JS)
        except Exception:
            cands = []
        if cands:
            break
    city = [c for c in cands
            if c["name"].strip().lower() in ("dubai", u"迪拜")]
    if not city:
        pg.keyboard.press("Escape")
        return True, u"降级：没有城市级 Dubai（候选 %s），留空" % \
            json.dumps([c["name"] for c in cands[:4]], ensure_ascii=False)
    c = city[0]
    if not c["inView"]:
        pg.evaluate(r"""(top)=>window.scrollBy(0, top-300)""", c["top"])
        time.sleep(0.6)
        cands = pg.evaluate(POI_JS)
        city = [x for x in cands if x["name"].strip().lower() in ("dubai", u"迪拜")]
        if not city or not city[0]["inView"]:
            pg.keyboard.press("Escape")
            return True, u"降级：Dubai 那条滚不进视口，留空"
        c = city[0]
    pg.mouse.click(c["x"], c["y"])
    time.sleep(1.5)
    # 选完下拉要收起来再读：不然读到的是候选列表里的字（假阳性）。
    pg.mouse.click(300, 400)
    time.sleep(1.5)
    got = pg.evaluate(POI_READ_JS)
    txt = u"%s %s" % (got.get("row") or "", got.get("val") or "")
    # 判据两条都要：① 「输入地理位置」占位符没了 = 真挂上了；
    #             ② 文字里有 Dubai。只看 ②会被城市页签里的「迪拜」骗（那是切城市用的）。
    ok2 = (u"输入地理位置" not in txt) and bool(re.search("Dubai", txt, re.I))
    return ok2, u"选了 %r（%s）· 回读 %r" % (
        c["name"], c["addr"][:26], txt.strip()[:60])


COVER_JS = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const b=cut(document.body.innerText);
  const mods=[...document.querySelectorAll('[class*=modal],[class*=Modal],[role=dialog]')]
    .filter(e=>{const r=e.getBoundingClientRect();
      return r.width>300&&r.height>200&&getComputedStyle(e).display!=='none';});
  const m=mods[mods.length-1];
  const mt=m?cut(m.innerText):'';
  // 弹窗里按文字找可点的东西。抖音这些按钮外面套了好几层同文字的 div，
  // 所以默认挑**面积最小**的那层（真正的可点内核）；low=true 时先挑最靠下的
  //（「设置横封面」既是顶部步骤标签、又是右下角按钮，要的是右下角那个）。
  const hit=(t,low)=>{
    let c=[...(m?m.querySelectorAll('button,div,span'):[])]
      .filter(x=>cut(x.innerText)===t && x.children.length<3 && !x.disabled)
      .map(x=>{const r=x.getBoundingClientRect();
               return {r:r, a:r.width*r.height};})
      .filter(o=>o.r.width>20 && o.r.height>12);
    if(!c.length) return null;
    c.sort(low ? (p,q)=>(q.r.top-p.r.top)||(p.a-q.a) : (p,q)=>p.a-q.a);
    const r=c[0].r;
    return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
            inView:r.top>=0&&r.bottom<=innerHeight};};
  return {
    modal: mt.slice(0,120),
    // 裁剪窗实测文字：「设置封面 重新上传 取消保存」
    isCrop: /重新上传/.test(mt) && /保存/.test(mt) && /设置封面/.test(mt),
    isCover: /上传封面|设置竖封面/.test(mt),
    save: hit('保存'), cancel: hit('取消'), done: hit('完成'),
    toH: hit('设置横封面', true),
    picks: (b.match(/选择封面/g)||[]).length,
    warn: /横\/竖双封面缺失|封面缺失/.test(b),
  };
}"""


def _cover_wait(pg, key, timeout=25):
    for _ in range(timeout):
        time.sleep(1)
        try:
            d = pg.evaluate(COVER_JS)
        except Exception:
            continue
        if d.get(key):
            return d
    return None


def cover_close(pg):
    u"""⚠️ 封面弹窗必须关掉。它是全屏遮罩，开着的话后面的定时/位置/发布全点不到
    ——第三遍就是这么一步红拖垮三步的。所以 set_covers 无论成败都要走这里。"""
    for _ in range(5):
        try:
            d = pg.evaluate(COVER_JS)
        except Exception:
            return False
        if not d["modal"]:
            return True
        for k in ("done", "cancel"):
            if d.get(k):
                pg.mouse.click(d[k]["x"], d[k]["y"])
                break
        else:
            pg.keyboard.press("Escape")
        time.sleep(1.8)
    try:
        return not pg.evaluate(COVER_JS)["modal"]
    except Exception:
        return False


# 弹窗里有 6 个 image 类型的 file input（semi-upload-hidden-input / -replace 各两份）。
# 喂 semi-* 那几个不弹裁剪窗（第三遍就是这么红的）；点「上传封面」也点不动
# （隐藏 input 盖在上面，Playwright 判定被遮挡直接超时，第四遍这么红的）。
# 探针证明能用的是 accept 只有 png/jpeg/jpg 那个（没有 bmp/webp）——直接喂它。
COVER_IN = "input[type=file][accept*='image/png']:not([accept*=bmp])"


def _feed_cover(pg, img):
    pg.locator(COVER_IN).first.set_input_files(img)


def set_covers(pg, ver, hor):
    u"""两张封面（3:4 竖 + 4:3 横）。抖音的发文助手自己会报
    「横/竖双封面缺失，为增加作品的流量，建议同时设置横版和竖版的封面」，所以这步不能省。

    流程（实测）：点「选择封面」→ 弹窗顶部是「设置竖封面 / 设置横封面」两步走
    → 点「上传封面」经 file chooser 喂图 → 裁剪窗（文字「设置封面 重新上传 取消保存」）
    → 点「保存」→ 回封面窗 → 点右下角「设置横封面」→ 再喂一张 → 保存 → 点「完成」。
    判据 = 页面上「选择封面」这四个字消失（两个位子都换成缩略图了）+ 助手不再报缺封面。"""
    ver = os.path.expanduser(ver or "")
    hor = os.path.expanduser(hor or "")
    if not os.path.isfile(ver) and not os.path.isfile(hor):
        return True, u"方案没给封面图，用平台自动帧"
    trail = []
    saved = 0
    need = len([x for x in (ver, hor) if os.path.isfile(x)])
    try:
        ok, why = click_in_view(pg, "text=选择封面")
        if not ok:
            return False, u"点不开封面弹窗（%s）" % why[:50]
        if not _cover_wait(pg, "isCover"):
            return False, u"封面弹窗没出来"
        for step, img in ((u"竖", ver), (u"横", hor)):
            if not os.path.isfile(img):
                trail.append(u"%s封面文件不在" % step)
                continue
            try:
                _feed_cover(pg, img)
            except Exception as e:
                trail.append(u"喂%s封面失败：%s" % (step, str(e)[:50]))
                break
            d = _cover_wait(pg, "isCrop")
            if not d:
                trail.append(u"%s封面没进裁剪窗" % step)
                break
            if not d["save"]:
                trail.append(u"%s封面裁剪窗里没有「保存」" % step)
                break
            pg.mouse.click(d["save"]["x"], d["save"]["y"])
            time.sleep(3)
            saved += 1
            trail.append(u"%s封面已存" % step)
            if step == u"竖" and os.path.isfile(hor):
                d = pg.evaluate(COVER_JS)
                if d["toH"]:
                    pg.mouse.click(d["toH"]["x"], d["toH"]["y"])
                    time.sleep(2.5)
                else:
                    trail.append(u"没找到「设置横封面」")
                    break
    finally:
        closed = cover_close(pg)
    time.sleep(1.5)
    d = pg.evaluate(COVER_JS)
    # ⚠️ 「选择封面」消失 + 助手不报缺 **不能单独当判据**：直接点「完成」会让平台
    # 拿视频帧当两张封面，一样满足这两条（第四遍就这么假绿过）。必须真存进去几张。
    ok = (closed and saved == need and d["picks"] == 0 and not d["warn"])
    return ok, u"存了 %d/%d 张 · %s · 弹窗已关=%s · 剩「选择封面」%d 个 · 助手报缺=%s" % (
        saved, need, " / ".join(trail) or u"没做", closed, d["picks"], d["warn"])


def preflight(pg, want):
    s = state(pg)
    bad = []
    if s["up"] or s["det"]:
        bad.append(u"上传未就绪 up=%r det=%r" % (s["up"], s["det"]))
    if not s["reup"]:
        bad.append(u"没有「重新上传」，视频不在")
    if not (s["title"] or "").strip():
        bad.append(u"标题空")
    if (s["bodyLen"] or 0) < 30:
        bad.append(u"正文只有 %s 字" % s["bodyLen"])
    if want.get("sched"):
        if (s["sched"] or "").strip() != want["sched"]:
            bad.append(u"定时 %r ≠ %r" % (s["sched"], want["sched"]))
        if s["radios"].get(u"定时发布") != "true":
            bad.append(u"定时单选没勾（%s）" % json.dumps(s["radios"],
                                                 ensure_ascii=False))
    if want.get("open") and s["radios"].get(u"公开") != "true":
        bad.append(u"可见范围不是公开（%s）" % json.dumps(s["radios"],
                                                ensure_ascii=False))
    if s["modal"]:
        bad.append(u"有弹窗盖着：%s" % s["modal"][0][:40])
    if not s["pub"]:
        bad.append(u"找不到发布按钮")
    return (not bad), bad, s


def do_publish(pg):
    u"""⚠️ 抖音的发布键永不禁用，平台零保险；只有体检是唯一防线。
    只认文字完全等于「发布」的 button（旁边「暂存离开」= 存草稿跳走）。"""
    s = state(pg)
    if s["up"] or s["det"]:
        return False, u"还在传/检测（up=%r det=%r），不敢点" % (s["up"], s["det"])
    pg.evaluate(r"""()=>{const b=[...document.querySelectorAll('button')]
        .filter(e=>(e.innerText||'').replace(/\s+/g,'')==='发布')[0];
        if(b) b.scrollIntoView({block:'center'});}""")
    time.sleep(0.8)
    s = state(pg)
    p = s["pub"]
    if not p:
        return False, u"找不到发布按钮"
    if not p["inView"]:
        return False, u"发布按钮滚不进视口 %s" % p
    log(u"       点发布 @(%d,%d) %dx%d" % (p["x"], p["y"], p["w"], p["h"]))
    pg.mouse.click(p["x"], p["y"])
    seen = ""
    for i in range(90):
        time.sleep(1)
        try:
            pg.evaluate("()=>1")
            u = pg.url
            t = pg.inner_text("body", timeout=4000) or ""
        except Exception:
            continue
        if "/content/manage" in u or "/content/post/video" not in u:
            return True, u"跳走了 URL=%s（%d 秒）" % (u, i + 1)
        if re.search(u"发布成功|定时发布成功|已发布", t):
            return True, u"平台回「发布成功」（%d 秒）" % (i + 1)
        m = re.findall(u"失败|请填写|请选择|不能为空|违规|风险|敏感", t)
        if m and str(m) != seen:
            seen = str(m)
            log(u"       页面提示：%s" % seen[:80])
    return False, u"90 秒没有成功信号（提示 %s，URL=%s）" % (seen, pg.url)


def verify_manage(pg, title, stamp, tries=3):
    u"""最终判据：作品管理里读到这条 + 定时时间。"""
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
                hit = re.findall(u"[^ ]{0,12}%s[^ ]{0,20}"
                                 % re.escape(stamp[5:16].replace("-", "-")), t)
                if not hit:
                    hit = re.findall(u"定时[^ ]{0,26}", t)
                return True, u"作品管理里有「%s…」%s" % (
                    title[:10], (u" · %s" % hit[0]) if hit else u"（没读到时间）")
    return False, u"作品管理里没读到这条"


# ── 一轮 ────────────────────────────────────────────────────────

def one_round(pg, plan, video, mode, stamp):
    cfg = plan.get("douyin") or {}
    steps = []

    def rec(name, ok, why):
        steps.append({"step": name, "ok": bool(ok), "why": why})
        log(u"    %s %-6s %s" % (u"✅" if ok else u"❌", name, why))
        return ok

    pg.goto(HOME, wait_until="domcontentloaded")
    if not wait_upload_area(pg):
        body = ""
        try:
            body = pg.inner_text("body", timeout=6000) or ""
        except Exception:
            pass
        if [w for w in LOGIN_WORDS if w in body]:
            return False, [{"step": u"登录", "ok": False, "why": u"掉登录了"}]
        return False, [{"step": u"表单", "ok": False, "why": u"等不到上传区"}]
    rec(u"表单", True, u"上传区就绪")

    if not rec(u"上传", *upload(pg, video)):
        shot(pg, "90_upload")
        return False, steps
    rec(u"标题", *set_title(pg, cfg.get("title") or ""))
    ok, why, diag = set_body(pg, cfg.get("body") or "", cfg.get("topics") or [])
    rec(u"正文", ok, why)
    try:
        with io.open(os.path.join(ROOT, "_pipeline", "dy_topics.json"), "w",
                     encoding="utf-8") as f:
            f.write(json.dumps(diag, ensure_ascii=False, indent=1))
    except Exception:
        pass
    rec(u"封面", *set_covers(pg, cfg.get("cover_vertical") or "",
                            cfg.get("cover_horizontal") or ""))
    # 封面弹窗残留 = 后面每一步都点不到，所以这里再兜一次底
    if state(pg)["modal"]:
        cover_close(pg)
    if cfg.get("schedule", True):
        rec(u"定时", *set_schedule(pg, stamp))
    rec(u"位置", *set_location(pg, cfg.get("location") or ""))
    if cfg.get("declare_original"):
        rec(u"原创", True, u"平台无此项（「自主声明」是 AI/虚构声明，勾了降权），跳过")

    want = {"sched": stamp if cfg.get("schedule", True) else None,
            "open": bool(cfg.get("privacy_open", True))}
    ok, bad, s = preflight(pg, want)
    rec(u"体检", ok, u"通过" if ok else u" / ".join(bad))
    log(u"       现场：%s" % json.dumps(
        {k: s[k] for k in ("up", "det", "reup", "title", "bodyLen", "topics",
                           "sched", "radios", "poi")}, ensure_ascii=False))
    if not ok:
        shot(pg, "91_preflight")
        return False, steps

    if mode == "fill":
        shot(pg, "filled")
        rec(u"收尾", True, u"fill 模式：填好不发")
        # ⚠️ 整轮算通过 = **每一步**都绿（别让「收尾 ✅」盖住中间的红）
        return all(s["ok"] for s in steps), steps

    if not rec(u"发布", *do_publish(pg)):
        shot(pg, "92_publish")
        return False, steps
    shot(pg, "published")
    rec(u"回读", *verify_manage(pg, cfg.get("title") or "", stamp))
    return all(s["ok"] for s in steps), steps


def bj_stamp(hhmm, ymd=None):
    u"""目标北京时间 YYYY-MM-DD HH:MM（定时框要的格式）。

    ⛔ 只做字段适配：日期解析、「今天来不及顺延一天」（抖音留 130 分钟余量）、
    以及**抖音只收 2 小时后 ~ 14 天内**这条硬边界，全在 `schedule_target.py`
    那一份实现里，别在这儿再写一遍。
    ⚠️ 抖音超界是**静默拒绝**（页面不报错、发布键也不禁用），所以必须在**填之前**
    就抛 ScheduleError 退出 —— 绝不能顺延、更不能当成功。
    ymd = 方案里的 schedule_bj_date。"""
    return schedule_target.target("douyin", hhmm, ymd)["stamp"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--mode", default="fill", choices=["fill", "publish"])
    ap.add_argument("--video", default="")
    ap.add_argument("--times", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "_pipeline", "dy_test.json"))
    a = ap.parse_args()

    with io.open(os.path.expanduser(a.plan), encoding="utf-8") as f:
        plan = json.load(f)
    video = os.path.expanduser(a.video or plan.get("video") or "")
    if not os.path.isfile(video):
        log(u"❌ 视频不在：%s" % video)
        return 1
    cfg = plan.get("douyin") or {}
    try:
        stamp = bj_stamp(cfg.get("schedule_bj_time") or plan.get("schedule_bj_time"),
                         schedule_target.plan_date(plan, "douyin"))
    except schedule_target.ScheduleError as e:
        # ⛔ 超界/太近就地停手：抖音会静默吃掉不合法的定时，填下去等于白发一条
        log(u"❌ 定时时刻不合法：%s" % e)
        return 3
    log(u"视频 %s（%.1f MB）· 模式 %s · 跑 %d 遍"
        % (os.path.basename(video), os.path.getsize(video) / 1e6, a.mode, a.times))
    log(u"定时目标 北京 %s" % stamp)

    # 开跑前清残留 + 拦住双开。实现只有 profile_guard 一份，⛔ 别在这里再写 pkill。
    try:
        profile_guard.solo(PROFILE)
    except profile_guard.BusyError as e:
        log(u"❌ %s" % e)
        return 4

    from playwright.sync_api import sync_playwright
    rounds = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE, channel="chrome", headless=False,
            no_viewport=True,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled",
                  "--remote-debugging-port=9224"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(45000)
        ctx.new_cdp_session(pg).send("Emulation.setTimezoneOverride",
                                     {"timezoneId": "Asia/Shanghai"})
        tz = pg.evaluate("()=>new Date().toString().slice(0,33)")
        log(u"时区已覆盖：%s" % tz)
        if "0800" not in tz.replace("+", "").replace(" ", ""):
            log(u"⚠️ 时区覆盖可疑，定时会差 4 小时")
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
                # ⚠️ ctx.close() 不保证进程真的死（见 profile_guard 的说明）
                if not profile_guard.kill(PROFILE):
                    log(u"⚠️ 这个 profile 的 Chrome 还有残留，下一个平台可能会被拖慢")
            else:
                log(u"🖐 --keep：浏览器留着（9224），记得手动关")
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
