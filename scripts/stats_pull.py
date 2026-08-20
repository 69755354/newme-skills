#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NewMe 数据回读器 —— 把三平台创作者中心的作品指标抓成时间序列

这是流水线的第六环（发出去之后）。前面五环是：选题 → 剪 → 渲染 → 发布 → 发布核实
（publish_verify.py）。本脚本接在 publish_verify.py 后面：那个脚本只回答"发出去了没有"，
这个脚本回答"发出去之后表现如何"，并把结果按天累积成 _pipeline/stats.csv，
交给 topic_next.py 算下一条拍什么。

用法:
    stats_pull.py                 抓全部三个平台（串行，一次只开一个浏览器）
    stats_pull.py douyin weixin   只抓指定平台
    stats_pull.py --selftest      离线自检：只跑解析逻辑，不开浏览器（可随时安全运行）

输出:
    _pipeline/stats.csv           UTF-8 带 BOM，Excel 双击直接能开
    stats_<平台>.png              每个平台的数据页全屏截图，抓错了好回溯

字段（12 列，三平台统一）:
    平台, 作品ID, 标题, 发布时间, 播放, 点赞, 评论, 收藏, 分享, 完播率, 涨粉, 抓取时间
    · 拿不到的字段一律写空（CSV 里是空单元格 / Python 里是 None）。**绝不用 0 冒充"没拿到"** ——
      0 播放和"页面上没这个字段"是两件完全不同的事，混了之后 topic_next 会算出假结论。
    · 完播率单位是百分数（32.5 表示 32.5%），不是 0.325。
    · 作品ID 优先取页面链接里的平台真 ID；实在取不到就退化成 "t-<标题MD5前10位>"，
      前缀 t- 就是在明说"这是我们自己派生的键，不是平台 ID"。

┌── 三个平台各自的坑（都是 2026-08-17~19 实测踩出来的，别再踩第二遍）────────────┐
│ 【微信视频号】作品列表的文字在 <wujie-app> 的 **open shadow root** 里。          │
│   → page.inner_text('body') 和 document.querySelectorAll('*') 都读不到任何作品，  │
│     曾因此误判成"页面空白"。必须自己写递归遍历，逐层进 el.shadowRoot。            │
│   → 遍历时必须跳过 STYLE / SCRIPT / NOSCRIPT / TEMPLATE：视频号页尾有大量 Vue    │
│     预渲染的隐藏模板（"切换视频号""暂时无法使用该功能"），不跳会把模板文字当成     │
│     作品数据抓进来。                                                            │
│   → 全站链接都是 javascript:;，直接 goto 列表页大概率只渲染侧边栏，              │
│     所以抓不到卡片时要退回去点「内容管理 → 视频」，而且每一级都得轮询等文字出现。 │
│                                                                                │
│ 【抖音】**URL 判据不可信**。2026-08-19 吃过一次假阳性：编辑页自己的 URL 就是      │
│   /content/post/video，判据里写了 content/post，于是没发布也报"已发布"。         │
│   → 本脚本一律不拿 URL 判断"到没到数据页"，只认"页面上真的扫到了带指标的作品卡片"。│
│   → 抖音页面底部常驻一句"点击发布后，如作品还在上传中，请勿关闭页面"，            │
│     所以任何含"上传中""发布"的裸文字判据都会永远为真，不能用。                    │
│                                                                                │
│ 【小红书】① 海外账号必须走 creator.rednote.com，大陆域名会 401 踢回登录页，       │
│   那个 401 长得极像登录过期，别误判。                                           │
│   ② 页面上的 <xhs-publish-btn> 是 **闭合 shadow root**，Playwright 穿不透、       │
│     递归遍历也报 shadow root 数 = 0。闭合 shadow 里的东西**只能靠坐标点**         │
│     （page.mouse.click(x, y)）。本脚本是只读的，正常不需要点它；                  │
│     万一左侧「笔记管理」入口也进了闭合 shadow，用环境变量给坐标兜底：             │
│     NEWME_XHS_NAV_XY="120,300"。⚠️ 这条坐标兜底路径未实测。                      │
└────────────────────────────────────────────────────────────────────────────────┘

内存纪律（这台机器只有 8 GB，曾经因为同时开多个浏览器硬死机过一次）:
    · 三个平台**严格串行**，关掉上一个再开下一个，中间 sleep 3 秒等内存真的还回来。
    · 清理残留进程只准用窄杀：
          pkill -TERM -f "user-data-dir=$HOME/NewMe/profiles/<平台>"
      ⛔ 绝对不许 pkill -f chrome —— 用户自己的 Chrome、别的会话的浏览器都会被带走。
"""
import csv
import hashlib
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

OUT_DIR = os.path.expanduser(
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft")
PIPE_DIR = os.path.join(OUT_DIR, "_pipeline")
PROFILE_ROOT = os.path.expanduser("~/NewMe/profiles")
CSV_PATH = os.path.join(PIPE_DIR, "stats.csv")

FIELDS = [u"平台", u"作品ID", u"标题", u"发布时间", u"播放", u"点赞", u"评论",
          u"收藏", u"分享", u"完播率", u"涨粉", u"抓取时间"]

ORDER = ["weixin", "xiaohongshu", "douyin"]
NAME = {"weixin": u"微信视频号", "xiaohongshu": u"小红书", "douyin": u"抖音"}

# 每个平台按顺序试这些地址，第一个"真的扫到作品卡片"的就算成功。
# 为什么给多个候选：创作者后台改版很勤，写死一个地址等于埋一颗定时炸弹。
# ✅ 已实测可达：抖音 content/manage（publish_verify.py 抓到过作品）
# ⚠️ 未实测：各家「数据中心」地址、小红书笔记管理地址（改版频繁，跑一次看日志就知道哪个中了）
URLS = {
    "douyin": [
        "https://creator.douyin.com/creator-micro/content/manage",
        "https://creator.douyin.com/creator-micro/data-center/content",
        "https://creator.douyin.com/creator-micro/data/content",
    ],
    "weixin": [
        "https://channels.weixin.qq.com/platform/post/list",
        "https://channels.weixin.qq.com/platform",
    ],
    # ✅ 2026-08-20 实测命中：/new/note-manager（其余三个地址全是错的，已删）
    "xiaohongshu": [
        "https://creator.rednote.com/new/note-manager",
    ],
}

# 抓不到卡片时的兜底导航：只点这些"看板/列表入口"文字，绝不点任何提交类按钮。
NAV = {
    "weixin": [u"内容管理", u"视频"],
    "xiaohongshu": [u"笔记管理", u"数据中心", u"数据分析"],
    "douyin": [u"内容管理", u"数据中心", u"作品数据"],
}

# 读页面时的安全闸门：本脚本是只读的，出现这些字样的元素一律不点。
NEVER_CLICK = (u"发表", u"发布", u"提交", u"删除", u"下架", u"推广", u"投放",
               u"暂存离开", u"保存草稿")

LOGIN_MARKS = (u"扫码登录", u"登录视频号助手", u"请使用微信扫码", u"二维码登录",
               u"手机号登录", u"密码登录", u"短信登录")

# 指标别名。顺序**很重要**：先抠掉「完播率」再找「播放」，
# 否则 "完播率" 里的 "播" 会被当成播放量的一部分（同理"涨粉"要先于"粉丝"类词）。
METRIC_ALIASES = [
    (u"完播率", [u"完播率", u"完播"]),
    (u"涨粉", [u"涨粉", u"新增粉丝", u"粉丝增长", u"新增关注"]),
    (u"播放", [u"播放量", u"播放", u"观看量", u"观看", u"展现量", u"阅读量", u"浏览量"]),
    (u"点赞", [u"点赞量", u"点赞", u"获赞", u"赞"]),
    (u"评论", [u"评论量", u"评论", u"留言"]),
    (u"收藏", [u"收藏量", u"收藏"]),
    (u"分享", [u"分享量", u"分享", u"转发", u"转发量"]),
]
ALL_LABELS = [a for _, al in METRIC_ALIASES for a in al]

# 卡片文字里要剔掉的噪声词（状态、按钮、平台话术），剩下最长的那段才当标题
NOISE_WORDS = (u"已发布", u"审核中", u"审核未通过", u"未通过", u"草稿", u"发布中",
               u"转码中", u"仅自己可见", u"公开", u"好友可见", u"编辑", u"删除",
               u"下载", u"数据详情", u"作品数据", u"更多", u"推广", u"置顶",
               u"查看详情", u"分享给好友", u"复制链接", u"权限设置", u"合集")

# 页面上一个"数字"长什么样：12,345 / 1.2万 / 3.4k / 32.5% / -- / —（后两个是"暂无数据"）
NUM_RE = r"(?:\d[\d,]*(?:\.\d+)?\s*(?:亿|万|w|W|k|K)?%?|-{1,2}|—)"


def log(msg):
    """统一日志出口。前缀用 emoji 是为了用户在 .command 黑窗口里一眼扫到结果。"""
    try:
        print(msg)
    except UnicodeEncodeError:                      # 极端终端编码兜底
        print(msg.encode("utf-8", "replace").decode("ascii", "replace"))
    sys.stdout.flush()


# ── 解析层（纯函数，可离线自检）────────────────────────────────────────────
def parse_num(raw):
    """把页面上的数字文本变成 int/float。拿不到就返回 None，绝不返回 0。

    页面上的写法五花八门：'1.2万' '12,345' '3.4k' '32.5%' '--' '—' '' 。
    '--' 和 '—' 是平台自己表示"暂无数据"，必须映射成 None 而不是 0。
    """
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if not s or s in ("-", "--", u"—", u"暂无", u"无"):
        return None
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    mult = 1
    for suf, m in ((u"亿", 100000000), (u"万", 10000), ("w", 10000),
                   ("W", 10000), ("k", 1000), ("K", 1000)):
        if s.endswith(suf):
            s, mult = s[:-len(suf)], m
            break
    try:
        v = float(s)
    except ValueError:
        return None
    v = v * mult
    if pct:                       # 完播率保留百分数，32.5% → 32.5
        return round(v, 2)
    return int(round(v)) if v == int(v) else round(v, 2)


def extract_metrics(text):
    """从一张作品卡片的文字里抠出各项指标。

    两种排布都要认：'播放量 1.2万'（标签在前）和 '1.2万 播放'（数字在前，抖音常见）。
    每命中一个就把那段文字从待搜文本里删掉，避免同一个数字被两个标签抢走。
    """
    rest = " " + re.sub(r"\s+", " ", text or "") + " "
    out = {}
    for field, aliases in METRIC_ALIASES:
        got = None
        for al in aliases:
            a = re.escape(al)
            for pat in (a + r"\s*[:：]?\s*(" + NUM_RE + r")",
                        r"(" + NUM_RE + r")\s*(?:次)?\s*" + a):
                m = re.search(pat, rest)
                if not m:
                    continue
                v = parse_num(m.group(1))
                if v is None:
                    continue
                got = v
                rest = rest[:m.start()] + " " + rest[m.end():]
                break
            if got is not None:
                break
        out[field] = got
    return out


def parse_publish_time(text, now=None):
    """从卡片文字里认发布时间，统一成 'YYYY-MM-DD HH:MM'（没有时分就只给日期）。

    绝对日期直接用。相对时间（'3天前''昨天''2小时前'）是**按抓取时刻做减法**算出来的，
    不是平台给的原值 —— 这是算术，不是猜；但精度只到当天，topic_next 里只当"哪天/哪个时段"用。
    """
    now = now or datetime.now()
    t = re.sub(r"\s+", " ", text or "")
    m = re.search(r"(20\d\d)[-/年](\d{1,2})[-/月](\d{1,2})"
                  r"(?:\D{1,3}(\d{1,2}):(\d{2}))?", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if m.group(4):
            return "%04d-%02d-%02d %02d:%02d" % (y, mo, d, int(m.group(4)),
                                                 int(m.group(5)))
        return "%04d-%02d-%02d" % (y, mo, d)
    m = re.search(r"(\d{1,2})[-/月](\d{1,2})日?\s*(\d{1,2}):(\d{2})", t)
    if m:                                   # 没有年份的 '08-19 21:30'，补当年
        return "%04d-%02d-%02d %02d:%02d" % (
            now.year, int(m.group(1)), int(m.group(2)),
            int(m.group(3)), int(m.group(4)))
    m = re.search(r"(\d+)\s*天前", t)
    if m:
        return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    m = re.search(r"(\d+)\s*(?:小时|个小时)前", t)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    m = re.search(r"(\d+)\s*分钟前", t)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).strftime("%Y-%m-%d %H:%M")
    if u"昨天" in t:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if u"今天" in t or u"刚刚" in t:
        return now.strftime("%Y-%m-%d")
    return None


def guess_title(text):
    """从卡片文字里猜标题（启发式，不是平台字段，所以叫 guess）。

    做法：把指标标签+数字、时间、状态词、按钮文字全部抠掉，
    剩下最长的一段连续文字就是标题。抓歪了看 stats_<平台>.png 截图对一下。
    """
    t = re.sub(r"\s+", " ", text or "")
    t = re.sub(r"\d{1,2}:\d{2}(:\d{2})?", " ", t)              # 时长/时间 00:40
    t = re.sub(r"20\d\d[-/年]\d{1,2}[-/月]\d{1,2}日?", " ", t)
    t = re.sub(r"\d+\s*(?:天|小时|个小时|分钟)前", " ", t)
    for al in sorted(ALL_LABELS, key=len, reverse=True):
        t = re.sub(re.escape(al) + r"\s*[:：]?\s*" + NUM_RE, " ", t)
        t = re.sub(NUM_RE + r"\s*(?:次)?\s*" + re.escape(al), " ", t)
        t = t.replace(al, " ")
    for w in NOISE_WORDS:
        t = t.replace(w, " ")
    t = re.sub(r"[#＃][^\s#＃]{1,20}", " ", t)                  # 话题不算标题
    parts = [p.strip(u" ·|/、,，.。-—")
             for p in re.split(r"\s{1,}", t) if len(p.strip()) >= 4]
    parts = [p for p in parts if not re.fullmatch(NUM_RE + r"?", p or "x")]
    if not parts:
        return None
    return max(parts, key=len)[:80]


def pick_work_id(hrefs, title, plat):
    """作品ID：优先平台真 ID，取不到就派生一个稳定键并用 t- 前缀标明是派生的。"""
    pats = [r"item_?id[=/]([\w-]{8,})", r"/note/([0-9a-f]{16,})",
            r"noteId[=/]([\w-]{8,})", r"/video/(\d{8,})",
            r"exportId[=/]([\w-]{8,})", r"objectId[=/]([\w-]{8,})",
            r"/(\d{15,})"]
    for h in hrefs or []:
        for p in pats:
            m = re.search(p, h)
            if m:
                return m.group(1)
    seed = (u"%s|%s" % (plat, title or "")).encode("utf-8")
    return "t-" + hashlib.md5(seed).hexdigest()[:10]


def cards_to_rows(plat, cards, grabbed):
    """把扫到的原始卡片（{'text','hrefs'}）转成统一字段的行。"""
    rows, seen = [], set()
    for c in cards:
        txt = c.get("text") or ""
        met = extract_metrics(txt)
        # 至少要有播放或点赞，否则这块八成不是作品卡片（是筛选栏、汇总条、模板残留）
        if met.get(u"播放") is None and met.get(u"点赞") is None:
            continue
        title = guess_title(txt)
        wid = pick_work_id(c.get("hrefs"), title, plat)
        if wid in seen:
            continue
        seen.add(wid)
        rows.append({
            u"平台": NAME[plat], u"作品ID": wid, u"标题": title,
            u"发布时间": parse_publish_time(txt),
            u"播放": met[u"播放"], u"点赞": met[u"点赞"],
            u"评论": met[u"评论"], u"收藏": met[u"收藏"],
            u"分享": met[u"分享"], u"完播率": met[u"完播率"],
            u"涨粉": met[u"涨粉"], u"抓取时间": grabbed,
        })
    return rows


# ── CSV 层 ────────────────────────────────────────────────────────────────
def load_csv(path):
    if not os.path.isfile(path):
        return []
    # utf-8-sig 既能读带 BOM 的（我们自己写的），也能读不带的
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip()
                                                    for v in r.values())]


def day_of(s):
    return (s or "")[:10]


def upsert_csv(path, new_rows):
    """追加写入，同一作品同一天只留最后一条（按 平台+作品ID+抓取日期 去重）。

    为什么按天而不是按次：她一天可能双击好几次跑数据，一天留一条正好形成日线，
    既能画趋势又不会把 CSV 撑爆。BOM 是给 Excel 的 —— 不带 BOM 双击会变乱码。
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged = {}
    for r in load_csv(path) + new_rows:
        key = (r.get(u"平台"), r.get(u"作品ID"), day_of(r.get(u"抓取时间")))
        merged[key] = r                       # 后来的覆盖先来的 = 留最后一条
    rows = sorted(merged.values(),
                  key=lambda r: (r.get(u"抓取时间") or "", r.get(u"平台") or "",
                                 r.get(u"作品ID") or ""))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k))
                        for k in FIELDS})
    return len(rows)


# ── 浏览器层 ──────────────────────────────────────────────────────────────
# ⚠️ 递归遍历，逐层进 open shadow root。视频号的作品列表全在 <wujie-app> 的
#    shadow root 里，inner_text('body') 一个字都读不到。
#    SKIP 那四个标签必须跳：视频号页尾有大量 Vue 预渲染隐藏模板，
#    不跳会把"切换视频号""暂时无法使用该功能"当成作品文字抓进来。
SCAN_JS = r"""
(cfg) => {
  const SKIP = new Set(['STYLE','SCRIPT','NOSCRIPT','TEMPLATE']);
  function deepAll(root, out) {
    out = out || [];
    const kids = root.querySelectorAll ? root.querySelectorAll('*') : [];
    kids.forEach((el) => {
      if (SKIP.has(el.tagName)) return;
      out.push(el);
      if (el.shadowRoot) deepAll(el.shadowRoot, out);   // 闭合 shadow 这里恒为 null
    });
    return out;
  }
  function deepText(node) {
    let s = '';
    (function walk(n) {
      if (!n) return;
      if (n.nodeType === 3) { s += n.nodeValue + ' '; return; }
      if (n.nodeType !== 1 && n.nodeType !== 11 && n.nodeType !== 9) return;
      if (n.nodeType === 1 && SKIP.has(n.tagName)) return;
      if (n.nodeType === 1 && n.shadowRoot) walk(n.shadowRoot);
      const cs = n.childNodes || [];
      for (let i = 0; i < cs.length; i++) walk(cs[i]);
    })(node);
    return s.replace(/\s+/g, ' ').trim();
  }
  const labels = cfg.labels || [];
  const all = deepAll(document);
  const cand = [];
  all.forEach((el) => {
    const t = deepText(el);
    if (!t || t.length < 6 || t.length > 900) return;
    let hit = 0;
    for (const l of labels) if (t.indexOf(l) >= 0) hit++;
    if (hit < 2) return;                       // 一张作品卡片至少带两个指标标签
    if (!/\d/.test(t)) return;
    cand.push({el: el, text: t});
  });
  // 由小到大接受：先收最内层的卡片，再把"包着已收卡片"的外层容器丢掉。
  // 用文字包含关系判断嵌套，因为 el.contains() 跨不过 shadow 边界。
  cand.sort((a, b) => a.text.length - b.text.length);
  const kept = [];
  cand.forEach((c) => {
    for (const k of kept) if (c.text.indexOf(k.text) >= 0) return;
    kept.push(c);
  });
  const cards = kept.slice(0, 60).map((c) => {
    const hrefs = [];
    try {
      c.el.querySelectorAll('a[href]').forEach((a) => {
        if (hrefs.length < 6) hrefs.push(a.getAttribute('href'));
      });
    } catch (e) {}
    return {text: c.text, hrefs: hrefs};
  });
  return {url: location.href, cards: cards, elements: all.length,
          body: deepText(document.body).slice(0, 1200)};
}
"""


def kill_profile_chrome(key):
    """只杀本 profile 的 chrome，避免上次残留的进程锁住 user-data-dir。

    ⛔ 永远不要写 pkill -f chrome / killall Chrome：
       用户自己开着的 Chrome、别的会话的浏览器都会被一起带走。
       模式里带完整的 user-data-dir 路径，命中范围就只有我们自己启的这一个。
    """
    pat = "user-data-dir=%s" % os.path.join(PROFILE_ROOT, key)
    try:
        subprocess.call(["pkill", "-TERM", "-f", pat])
    except Exception as e:
        log(u"    （清理残留进程失败，忽略：%s）" % e)


def safe_click_text(page, label):
    """只读脚本里的导航点击：命中 NEVER_CLICK 就拒绝，宁可抓不到也不能误操作。"""
    try:
        loc = page.locator('text="%s"' % label).first
        if not loc.is_visible(timeout=2000):
            return False
        txt = (loc.inner_text(timeout=2000) or "").strip()
        if len(txt) <= 12 and any(w in txt for w in NEVER_CLICK):
            log(u"    🛑 拒绝点击「%s」（只读脚本的安全闸门）" % txt[:12])
            return False
        loc.click(timeout=6000)
        return True
    except Exception:
        return False


def scan(page):
    return page.evaluate(SCAN_JS, {"labels": ALL_LABELS})


# ── 行文字解析（2026-08-20 实测替换掉了原来的"通用卡片猜测器"）─────────────
# 为什么换：通用猜测器在抖音抓出 3 条垃圾（标题「平均浏览图片数」、播放 59），
# 因为它把数据面板碎片当成了作品卡片。真作品行的文字是有固定形状的，写死更准。

ROWS_JS = r"""() => {
  const cut=s=>(s||'').replace(/\s+/g,' ').trim();
  const out=[];
  document.querySelectorAll('div,li,tr,article').forEach(e=>{
    const t=cut(e.innerText);
    if(t.length<12||t.length>300) return;
    if(!/\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月\d{1,2}日/.test(t)) return;
    const r=e.getBoundingClientRect();
    if(r.height<40||r.width<250) return;
    out.push(t);
  });
  // 只保留**最内层**：谁包含了别的候选，谁就是父容器，丢掉。
  // ⚠️ 方向千万别写反：写成「丢掉被别人包含的」会只剩下整页容器，
  //    实测那次小红书 9 行全被一段页头文字吃掉，解析结果 0 条。
  const keep=out.filter(a=>!out.some(b=>b!==a&&a.includes(b)));
  return {rows:[...new Set(keep)], nRaw:out.length,
          body:cut(document.body.innerText).slice(0,1500)};
}"""

# 抖音行形状（作品管理页，标签+数值，值可能是 '-' 表示私密/无数据）：
#   00:26 标题#话题 编辑作品 设置权限 作品置顶 删除作品 2026年08月05日 09:44 已发布
#   播放 331 点赞 9 评论 2 分享 0 收藏 0 完播率 5.41% 2秒跳出率 43.44% 吸粉量 4
DY_LABELS = [(u"播放", u"播放"), (u"点赞", u"点赞"), (u"评论", u"评论"),
             (u"收藏", u"收藏"), (u"分享", u"分享"),
             (u"完播率", u"完播率"), (u"涨粉", u"吸粉量")]
DY_BTNS = (u"编辑作品", u"设置权限", u"作品置顶", u"取消置顶", u"删除作品",
           u"修改定时", u"数据详情", u"推广", u"私密", u"已发布", u"定时发布中")


def _dy_row(text, grabbed):
    t = re.sub(r"\s+", " ", text)
    if u"删除作品" not in t and u"修改定时" not in t:
        return None                      # 不是作品行（面板碎片没有操作按钮）
    m = re.search(r"(20\d\d)年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", t)
    if not m:
        return None
    when = "%04d-%02d-%02d %02d:%02d" % tuple(int(x) for x in m.groups())
    head = t[:m.start()]
    head = re.sub(r"^\d{1,2}:\d{2}(:\d{2})?\s*", "", head)   # 去时长
    for w in DY_BTNS:
        head = head.replace(w, " ")
    head = re.sub(r"[#＃][^\s#＃]{1,24}", " ", head)          # 话题不算标题
    if any(w in head for w in NAV_WORDS):
        return None                      # 匹配到整页容器了，不是一行
    title = re.sub(r"\s+", " ", head).strip(u" ·|/、,，.。-—") or None
    if title:
        title = title[:40]               # 抖音「标题」其实是作品描述，会很长
    met = {}
    for field, label in DY_LABELS:
        mm = re.search(re.escape(label) + r"\s*(-|[\d\.,]+%?|\d+\.?\d*万?)", t)
        met[field] = None if (not mm or mm.group(1) == "-") \
            else parse_num(mm.group(1))
    return {u"平台": NAME["douyin"],
            u"作品ID": pick_work_id([], title, "douyin"),
            u"标题": (title or u"")[:80] or None, u"发布时间": when,
            u"播放": met[u"播放"], u"点赞": met[u"点赞"],
            u"评论": met[u"评论"], u"收藏": met[u"收藏"],
            u"分享": met[u"分享"], u"完播率": met[u"完播率"],
            u"涨粉": met[u"涨粉"], u"抓取时间": grabbed}


# 小红书行形状（笔记管理页，**没有标签**，尾部五个裸数字）：
#   00:39 标题 2026-08-19 23:55 299 0 2 0 1
# 顺序按页面图标：👁播放 💬评论 ♡点赞 ☆收藏 ↗分享（截图逐个对过）。
# 定时未发的那条形如「… 定时发布 2026-08-20 19:30 （GMT+8:00 北京时间）」，
# 尾部没有数字 → 返回 None（还没有数据，写 0 会污染时间序列）。
XHS_RE = re.compile(
    u"^(?:(\\d{1,2}:\\d{2})\\s+)?(.{1,60}?)\\s+(20\\d\\d-\\d{2}-\\d{2}\\s+\\d{1,2}:\\d{2})"
    u"\\s+([\\d,\\.]+万?)\\s+(\\d+)\\s+(\\d+)\\s+(\\d+)\\s+(\\d+)$")

# 导航/页头词：出现这些说明匹配到的是**整页容器**而不是一行
# （第一次实跑就把「创作服务平台 小红薯_9446 发布笔记 笔记管理…」整段当成了标题）
NAV_WORDS = (u"创作服务平台", u"笔记管理", u"收起侧边栏", u"发布笔记",
             u"审核中", u"未通过", u"数据中心", u"视频号助手")


def _xhs_row(text, grabbed):
    t = re.sub(r"\s+", " ", text).strip()
    if u"定时发布" in t:
        return None
    if any(w in t for w in NAV_WORDS):
        return None
    m = XHS_RE.match(t)
    if not m:
        return None
    title = (m.group(2) or "").strip(u" ·|/、,，.。-—") or None
    return {u"平台": NAME["xiaohongshu"],
            u"作品ID": pick_work_id([], title, "xiaohongshu"),
            u"标题": (title or u"")[:80] or None,
            u"发布时间": m.group(3),
            u"播放": parse_num(m.group(4)), u"点赞": parse_num(m.group(6)),
            u"评论": parse_num(m.group(5)), u"收藏": parse_num(m.group(7)),
            u"分享": parse_num(m.group(8)), u"完播率": None, u"涨粉": None,
            u"抓取时间": grabbed}


ROW_PARSER = {"douyin": _dy_row, "xiaohongshu": _xhs_row}


def rows_from_text(key, texts, grabbed):
    u"""行文字 → 统一字段。同一条作品可能被抓到多层，按 (标题, 发布时间) 去重。"""
    fn = ROW_PARSER.get(key)
    if not fn:
        return []
    out, seen = [], set()
    for t in texts:
        try:
            r = fn(t, grabbed)
        except Exception:
            r = None
        if not r:
            continue
        k = (r[u"标题"], r[u"发布时间"])
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _pull_generic(pg, log, key):
    """三平台共用的抓取骨架：候选地址逐个试 → 不行就点导航入口 → 深层扫卡片。

    判"到没到数据页"只认一件事：**深层扫描真的扫到了带指标的作品卡片**。
    ⚠️ 不看 URL —— 抖音的 URL 判据被证明会骗人（编辑页 URL 就含 content/post，
       曾据此误报"已发布"）。
    """
    grabbed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    best, best_url = [], ""
    for url in URLS[key]:
        log(u"    → 试 %s" % url)
        try:
            pg.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            log(u"      打不开：%s" % str(e)[:80])
            continue
        time.sleep(8)                       # 微前端/懒加载，给足渲染时间
        # 登录判据只认 **frame 的 URL**：顶层文档里那句「登录视频号助手」是
        # 首页宣传文案的常驻文字，拿它判登录会永远为真（假阴性）。
        # 真掉线的样子是 frames 里出现 login.html / qrconnect 二维码页。
        furls = " ".join(f.url for f in pg.frames)
        if "login.html" in furls or "qrconnect" in furls:
            log(u"    ❌ 登录过期（页面里挂着扫码二维码）——需要本人扫码，本平台跳过")
            return []
        # ⚠️ 不能只 evaluate 一次：列表是懒加载的，8 秒时小红书只渲染出首屏 1 条
        #    （实测 1 条 vs 轮询后 7 条）。轮询到行数不再增长为止。
        d, rows, still = {"rows": [], "nRaw": 0}, [], 0
        for i in range(12):
            try:
                dd = pg.evaluate(ROWS_JS)
            except Exception as e:
                # ⚠️ 别静默吞：吞掉过一次，页面明明渲染好了却报 0 段，白查半天
                log(u"      ⚠️ 第 %d 轮取行失败：%s" % (i + 1, str(e)[:120]))
                dd = {"rows": [], "nRaw": 0}
            rr = rows_from_text(key, dd["rows"], grabbed)
            if dd["nRaw"] > d["nRaw"] or len(dd["rows"]) > len(d["rows"]):
                d = dd                        # 日志要反映最后看到的真实情况
            if len(rr) > len(rows):
                rows, still = rr, 0
            else:
                still += 1
                if rows and still >= 2:
                    break
            time.sleep(2)
        r = {"url": pg.url}
        log(u"      行文字 %d 段（原始 %d）→ 认成作品 %d 条"
            % (len(d["rows"]), d["nRaw"], len(rows)))
        if not rows:                          # 解析不出来时把样本打出来，否则无从下手
            for s in d["rows"][:4]:
                log(u"        样本｜%s" % s[:180])
        if len(rows) > len(best):
            best, best_url = rows, r["url"]
        if rows:
            break

    if not best:
        # 地址都没抓到东西 → 退回去点导航入口（视频号必走这条路：全站 javascript:;）
        for label in NAV.get(key, []):
            log(u"    → 抓不到，试着点「%s」" % label)
            if not safe_click_text(pg, label):
                continue
            time.sleep(6)
            d = pg.evaluate(ROWS_JS)
            rows = rows_from_text(key, d["rows"], grabbed)
            r = {"url": pg.url}
            log(u"      点完扫到作品 %d 条" % len(rows))
            if len(rows) > len(best):
                best, best_url = rows, r["url"]
            if rows:
                break

    if not best and key == "xiaohongshu":
        xy = os.environ.get("NEWME_XHS_NAV_XY")
        if xy and "," in xy:
            # ⚠️ 未实测路径。小红书的闭合 shadow root 里的元素只能靠坐标点，
            #    没有任何选择器进得去。坐标随窗口尺寸变，所以做成环境变量而不是写死。
            x, y = [int(v.strip()) for v in xy.split(",")[:2]]
            log(u"    → 闭合 shadow 兜底：坐标点 (%d, %d)（未实测路径）" % (x, y))
            try:
                pg.mouse.click(x, y)
                time.sleep(6)
                d = pg.evaluate(ROWS_JS)
                best = rows_from_text(key, d["rows"], grabbed)
                best_url = pg.url
            except Exception as e:
                log(u"      坐标点失败：%s" % str(e)[:80])

    if best:
        log(u"    ✅ %s 拿到 %d 条（数据页 %s）" % (NAME[key], len(best),
                                                best_url[:70]))
    else:
        log(u"    ⚠️ %s 一条都没抓到。看截图 stats_%s.png 对一下页面长什么样，"
            u"再把命中的地址补进 URLS。" % (NAME[key], key))
    return best


def pull_weixin(pg, log):
    """微信视频号（Newme-Tanya）。

    坑：作品列表整个在 <wujie-app> 的 **open shadow root** 里 ——
        page.inner_text('body') / document.querySelectorAll('*') 都读不到作品，
        必须用 SCAN_JS 的递归遍历，并跳过 STYLE/SCRIPT/NOSCRIPT/TEMPLATE
        （页尾有大量 Vue 预渲染隐藏模板会污染文字）。
    坑：全站链接是 javascript:;，直接 goto /platform/post/list 常常只出侧边栏，
        所以必须保留「内容管理 → 视频」的点击兜底。
    列表页通常给：播放 / 点赞 / 评论 / 分享。完播率和涨粉要点进单条「数据」页，
        本脚本不进（只读、省内存），所以这两项写空。
    """
    return _pull_generic(pg, log, "weixin")


def pull_xiaohongshu(pg, log):
    """小红书（小红薯_9446）。

    坑：海外账号只能用 creator.rednote.com；大陆域名 401 长得像掉登录，别误判。
    坑：<xhs-publish-btn> 是**闭合 shadow root**，穿不透也扫不到，
        闭合 shadow 里的东西只能坐标点（NEWME_XHS_NAV_XY 兜底，未实测）。
    笔记管理通常给：观看 / 点赞 / 收藏 / 评论（本脚本把"观看"归到「播放」列）。
        分享、完播率、涨粉一般不在列表上 → 写空。
    """
    return _pull_generic(pg, log, "xiaohongshu")


def pull_douyin(pg, log):
    """抖音（@Tanya）。

    坑：**URL 判据不可信**。编辑页 URL 自己就是 /content/post/video，
        2026-08-19 据此误报过"已发布"。所以到没到数据页只认"扫到了作品卡片"。
    坑：页面底部常驻"点击发布后，如作品还在上传中，请勿关闭页面"，
        任何含"上传中/发布"的裸文字判据都会永远为真，不能用。
    内容管理通常给：播放 / 点赞 / 评论 / 分享（+ 收藏，看版本）。
        完播率和涨粉在「数据中心 → 作品数据」里，地址未实测，抓不到就写空。
    """
    return _pull_generic(pg, log, "douyin")


PULLER = {"weixin": pull_weixin, "xiaohongshu": pull_xiaohongshu,
          "douyin": pull_douyin}


def run_platform(p, key):
    """开一个浏览器、抓一个平台、关掉。串行调用，一次只活着一个 chrome。"""
    log("\n" + "=" * 60)
    log(u"  %s" % NAME[key])
    log("=" * 60)
    kill_profile_chrome(key)
    time.sleep(1)
    ctx = None
    try:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=os.path.join(PROFILE_ROOT, key), channel="chrome",
            headless=False, no_viewport=True,
            args=["--start-maximized",
                  "--disable-blink-features=AutomationControlled"])
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_default_timeout(30000)
        # ⚠️ 必须覆盖时区。本机在迪拜（UTC+4），后台按浏览器时区渲染发布时间：
        #    第一次实跑把北京 19:30 那条记成了 15:30，整列时间口径就废了。
        try:
            ctx.new_cdp_session(pg).send("Emulation.setTimezoneOverride",
                                         {"timezoneId": "Asia/Shanghai"})
        except Exception as e:
            log(u"    ⚠️ 时区覆盖失败（发布时间会是迪拜时间）：%s" % str(e)[:80])
        rows = PULLER[key](pg, log)
        try:
            pg.screenshot(path=os.path.join(OUT_DIR, "stats_%s.png" % key),
                          full_page=True)
        except Exception:
            pass
        return rows
    except Exception as e:
        log(u"    ❌ %s 出错：%s" % (NAME[key], str(e)[:200]))
        return []
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass
        kill_profile_chrome(key)            # 窄杀，收尾（见函数注释）
        time.sleep(3)                       # 8 GB 机器：等内存真的还回来再开下一个


# ── 离线自检 ──────────────────────────────────────────────────────────────
SELFTEST_CARDS = {
    # 抖音内容管理卡片的典型文字（照 publish_verify.json 里真抓到的那条改写）
    "douyin": [{"text": u"00:40 整面墙只留一块屏，全屋都在这里面 2026-08-19 21:30 "
                        u"已发布 播放量 1.2万 点赞 486 评论 37 分享 52",
                "hrefs": ["/creator-micro/content/manage?item_id=7412345678901234567"]},
               {"text": u"筛选 全部作品 已发布 审核中", "hrefs": []}],
    "weixin": [{"text": u"一块屏管全屋是怎么做到的 3天前 播放 2,341 点赞 88 "
                        u"评论 12 分享 9 已发布", "hrefs": []}],
    "xiaohongshu": [{"text": u"迪拜这套别墅，墙上只留了一块屏 08-19 21:30 "
                             u"观看 3456 点赞 210 收藏 178 评论 24", "hrefs":
                     ["/note/65f0a1b2c3d4e5f60718293a"]}],
}


def selftest():
    """不开浏览器，只验证解析 + CSV 去重逻辑。任何时候都能安全跑。"""
    log(u"=== 离线自检（不开浏览器）===")
    bad = 0
    cases = [(u"1.2万", 12000), (u"12,345", 12345), (u"3.4k", 3400),
             (u"32.5%", 32.5), ("--", None), (u"—", None), ("", None),
             (u"1.5亿", 150000000), ("0", 0)]
    for raw, want in cases:
        got = parse_num(raw)
        ok = got == want
        bad += 0 if ok else 1
        log(u"  parse_num(%-8r) = %-12r %s" % (raw, got, u"✅" if ok else
                                              u"❌ 期望 %r" % want))
    grabbed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 行文字解析：阳性 + 阴性对照（样本是 2026-08-20 从真页面 dump 下来的）──
    POS = {
        "douyin": [
            u"00:26 KNX智能家居系统什么时候进场#智能家居智能生活 #豪宅别墅 #迪拜 "
            u"编辑作品 设置权限 作品置顶 删除作品 2026年08月05日 09:44 已发布 "
            u"播放 331 点赞 9 评论 2 分享 0 收藏 0 完播率 5.41% "
            u"2秒跳出率 43.44% 吸粉量 4",
            u"04:49 私密 无作品描述 编辑作品 设置权限 删除作品 "
            u"2025年11月01日 15:52 播放 - 点赞 - 评论 - 分享 - 收藏 - 吸粉量 -",
        ],
        "xiaohongshu": [
            u"00:26 KNX智能家居进场阶段 2026-08-05 13:46 374 5 15 0 0",
            u"迪拜聚会日常 2024-11-18 21:06 1056 6 18 2 5",
        ],
    }
    # 这些必须**一条都认不出来**，否则就是当初抓出「平均浏览图片数 播放 59」的那种病
    NEG = [u"平均浏览图片数 2024-08-12 17:59 59",
           u"数据概览 2026-08-20 播放量 1234 较昨日 +5%",
           u"00:39 迪拜这套别墅，墙上只留了一块屏 定时发布 2026-08-20 19:30 "
           u"（GMT+8:00 北京时间）"]
    for key, samples in POS.items():
        got = rows_from_text(key, samples, grabbed)
        ok = len(got) == len(samples)
        bad += 0 if ok else 1
        log(u"\n  %s 阳性 %d/%d %s" % (NAME[key], len(got), len(samples),
                                      u"✅" if ok else u"❌"))
        for r in got:
            log(u"    《%s》 %s 播=%s 赞=%s 评=%s 藏=%s 享=%s 完播=%s 涨粉=%s"
                % (r[u"标题"], r[u"发布时间"], r[u"播放"], r[u"点赞"],
                   r[u"评论"], r[u"收藏"], r[u"分享"], r[u"完播率"], r[u"涨粉"]))
    for key in ("douyin", "xiaohongshu"):
        n = len(rows_from_text(key, NEG, grabbed))
        log(u"  %s 阴性对照（面板碎片/未发定时）认出 %d 条 %s"
            % (NAME[key], n, u"✅" if n == 0 else u"❌ 应该是 0"))
        bad += 0 if n == 0 else 1
    # 抖音私密作品：指标全是 '-'，必须是 None 而不是 0
    priv = rows_from_text("douyin", [POS["douyin"][1]], grabbed)[0]
    ok = priv[u"播放"] is None and priv[u"点赞"] is None
    log(u"  抖音「-」指标 → None 而不是 0 %s" % (u"✅" if ok else u"❌"))
    bad += 0 if ok else 1

    for key, cards in SELFTEST_CARDS.items():
        rows = cards_to_rows(key, cards, grabbed)
        log(u"\n  [旧通用解析器，仅保留参考] %s → 认出 %d 条"
            % (NAME[key], len(rows)))
        for r in rows:
            log(u"    ID=%s 标题=《%s》 发布=%s 播放=%s 赞=%s 评=%s 藏=%s 享=%s "
                u"完播=%s 涨粉=%s"
                % (r[u"作品ID"], r[u"标题"], r[u"发布时间"], r[u"播放"],
                   r[u"点赞"], r[u"评论"], r[u"收藏"], r[u"分享"],
                   r[u"完播率"], r[u"涨粉"]))
        if not rows:
            bad += 1
    tmp = os.path.join(PIPE_DIR, "_selftest_stats.csv")
    r1 = cards_to_rows("douyin", SELFTEST_CARDS["douyin"], "2026-08-19 10:00:00")
    r2 = cards_to_rows("douyin", SELFTEST_CARDS["douyin"], "2026-08-19 22:00:00")
    if os.path.isfile(tmp):
        os.remove(tmp)
    upsert_csv(tmp, r1)
    n = upsert_csv(tmp, r2)
    log(u"\n  同一作品同一天写两次 → CSV 里剩 %d 行 %s"
        % (n, u"✅" if n == 1 else u"❌ 应该只剩 1 行"))
    bad += 0 if n == 1 else 1
    n2 = upsert_csv(tmp, cards_to_rows("douyin", SELFTEST_CARDS["douyin"],
                                       "2026-08-20 09:00:00"))
    log(u"  换一天再写一次 → CSV 里剩 %d 行 %s"
        % (n2, u"✅" if n2 == 2 else u"❌ 应该是 2 行"))
    bad += 0 if n2 == 2 else 1
    os.remove(tmp)
    log(u"\n%s" % (u"✅ 自检全部通过" if not bad else u"❌ 有 %d 项没过" % bad))
    return 0 if not bad else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    keys = [a for a in sys.argv[1:] if a in PULLER] or ORDER
    log("=" * 60)
    log(u"  NewMe 数据回读 · %s" % " / ".join(NAME[k] for k in keys))
    log(u"  串行执行，一次只开一个浏览器（这台机器只有 8 GB）")
    log("=" * 60)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log(u"❌ 找不到 playwright。先跑 newme-install.command。")
        return 1

    all_rows, per = [], {}
    with sync_playwright() as p:
        for k in keys:
            rows = run_platform(p, k)
            per[k] = len(rows)
            all_rows += rows

    total = upsert_csv(CSV_PATH, all_rows) if all_rows else \
        len(load_csv(CSV_PATH))
    log("\n" + "=" * 60)
    for k in keys:
        log(u"  %-10s %s" % (NAME[k], u"%d 条" % per[k] if per[k]
                             else u"0 条（未登录 / 页面改版 / 没作品，看日志和截图）"))
    log(u"  CSV 累计 %d 行 → %s" % (total, CSV_PATH))
    log("=" * 60)
    if not all_rows:
        log(u"\n这次一条都没抓到，stats.csv 没变。接着跑 topic_next.py 只会用旧数据。")
        return 2
    log(u"\n下一步：topic_next.py 会读这个 CSV 出选题建议。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
