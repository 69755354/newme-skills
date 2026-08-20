#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NewMe 选题建议器 —— 读 stats.csv，算出下一条拍什么、发哪个平台、什么时候发

设计原则只有一条：**可解释**。每一个结论后面都必须能翻出具体数字，
所以这里没有任何模型、没有黑箱打分，全是加减乘除 + 中位数，
而且样本不够的时候必须自己承认不够 —— 三条数据编不出趋势。

用法:
    topic_next.py                        读 _pipeline/stats.csv
    topic_next.py _pipeline/stats_样例.csv   读指定 CSV（造数据验证逻辑用）
    topic_next.py <csv> -o <输出.md>

输出:
    _pipeline/选题建议.md

算法（四步，都能手算复核）:
  第 1 步 · 取最新快照
      同一作品可能有多天的快照，只取最后一天那条算表现；多天快照另外用来算"还在不在涨"。
  第 2 步 · 按平台归一化（**平台之间的绝对播放量根本不可比** ——
      抖音随手一条几万播放，视频号几千就算好，直接比等于永远推荐抖音）
      · 日均播放 = 播放 ÷ 发布至今天数     → 抹掉"老片子攒得久"的便宜
      · 互动率   = (点赞+评论+收藏+分享) ÷ 播放   （只累加该平台真拿到的字段）
      · 播放倍数 = 本条日均播放 ÷ 该平台日均播放的**中位数**
      · 互动倍数 = 本条互动率   ÷ 该平台互动率的**中位数**
        用中位数不用平均数：一条爆款能把平均数拉飞，剩下全变"低于平均"。
      · 表现分   = 0.6 × 播放倍数 + 0.4 × 互动倍数
        权重是人定的，不是学出来的：播放代表分发量、互动代表这条真的打到人了。
        1.0 = 跟这个平台自己的中位数持平；1.5 = 比自己的一般水平好五成。
      ⚠️ 互动率的口径各平台不同（小红书列表有收藏没分享、抖音相反），
         所以互动率**只在同平台内部比**，跨平台比的只有"倍数"这个相对值。
  第 3 步 · 给标题打主题标签（KNX 总线 / 预算 / 装修阶段 / 场景联动 / 踩坑 / 安防对讲 / 海外客群 / 炫房）
      按关键词命中，一条可以带多个标签。然后统计"哪类主题在哪个平台的表现分更高"。
      ⚠️ 我们只能从**标题**打标签 —— 正文和话题没进 CSV。所以这层判断偏粗，报告里会说明。
  第 4 步 · 发布时间 vs 表现
      按发布小时分成 早(6-11) / 午(11-14) / 下午(14-18) / 晚(18-23) / 深夜(23-6)，
      看哪个时段的表现分中位数高。

可信度闸门（写死的，不许绕）:
    · 单平台作品数 < 3     → 不许给该平台的结论，只能说"线索"
    · 某标签样本数 < 2     → 只能进"线索"，不许进结论
    · 全部作品数 < 9       → 报告顶部打大字警告：这是方向性猜测，不是结论
    · 只有一天的快照       → 不许谈"势头/还在涨"
内容口味闸门:
    · 选题必须是**一个具体痛点**（例："装修到一半才想做智能家居，线已经封在墙里了"）
    · 「炫房」方向（豪宅/顶配/千万）即使数据上表现好也**不采纳**，只在报告里如实标出来，
      理由是账号定位要留住"准备装修的人"，不是看热闹的人。
"""
import csv
import os
import re
import sys
from datetime import datetime

OUT_DIR = os.path.expanduser(
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft")
PIPE_DIR = os.path.join(OUT_DIR, "_pipeline")
DEFAULT_CSV = os.path.join(PIPE_DIR, "stats.csv")
DEFAULT_MD = os.path.join(PIPE_DIR, u"选题建议.md")

MIN_PER_PLATFORM = 3      # 少于这个数不给平台级结论
MIN_PER_TAG = 2           # 少于这个数标签只算线索
MIN_TOTAL = 9             # 少于这个数整篇只算方向性猜测
W_PLAY, W_ENG = 0.6, 0.4  # 表现分权重（人定的，见上面说明）

ENG_FIELDS = [u"点赞", u"评论", u"收藏", u"分享"]

# 主题标签的关键词表。命中即打标，一条可带多个标签。
TAG_KEYWORDS = [
    (u"KNX总线", [u"KNX", u"knx", u"总线", u"一套系统", u"同一套", u"协议",
                  u"网关", u"有线", u"无线", u"布线", u"一块屏", u"面板", u"开关",
                  u"App", u"app", u"各管一摊", u"打通"]),
    # ⚠️ 别把裸的「万」放进来：实测"迪拜千万豪宅"会被误判成预算话题。
    (u"预算价格", [u"预算", u"多少钱", u"价格", u"报价", u"花了", u"多少",
                   u"性价比", u"省钱", u"贵", u"便宜", u"钱", u"哪几项",
                   u"AED", u"迪拉姆", u"成本", u"分期"]),
    (u"装修阶段", [u"水电", u"预埋", u"阶段", u"装修前", u"开墙", u"砸墙", u"毛坯",
                   u"施工", u"改造", u"精装", u"来不及", u"越早", u"晚了", u"交房",
                   u"装完", u"装修到一半"]),
    (u"场景联动", [u"场景", u"联动", u"一键", u"回家", u"离家", u"自动", u"窗帘",
                   u"灯光", u"开灯", u"手动", u"空调", u"温度", u"睡眠", u"模式"]),
    (u"踩坑", [u"坑", u"避坑", u"后悔", u"别买", u"翻车", u"教训", u"失效",
               u"断连", u"售后", u"维护", u"白花", u"废", u"停产", u"配件"]),
    (u"安防对讲", [u"对讲", u"门锁", u"摄像头", u"猫眼", u"安防", u"门口",
                   u"谁来了", u"可视"]),
    (u"海外客群", [u"迪拜", u"海外", u"中东", u"自建房", u"华人", u"移民", u"置业"]),
    # 「炫房」单独列出来是为了**识别并拒绝**，不是为了推荐
    # ⚠️ 别放裸的「千万」：实测"这两项千万别砍"会被误判成炫豪宅。
    (u"炫房", [u"豪宅", u"千万豪", u"顶配", u"豪华", u"奢", u"土豪", u"富人",
               u"有钱人", u"顶级", u"天花板"]),
]
TASTE_BLOCK = {u"炫房"}

HOUR_BUCKETS = [(6, 11, u"早 6-11 点"), (11, 14, u"午 11-14 点"),
                (14, 18, u"下午 14-18 点"), (18, 23, u"晚 18-23 点"),
                (23, 30, u"深夜 23-6 点")]

# 每个标签对应的**具体痛点**选题库。口味约束在这里落地：
# 每条都是"一个具体的、会让人心里一紧的处境"，不是"智能家居有多好"。
PAINPOINTS = {
    u"装修阶段": {
        u"痛点": u"装修到一半才想做智能家居，线已经封在墙里了",
        u"标题": [u"水电做完才想做智能家居，等于重新开墙",
                  u"错过这三个节点，全屋智能只能打补丁",
                  u"毛坯阶段两小时能定的事，装完要砸墙两周"],
        u"怎么拍": u"先给一面已经封好的墙（贴瓷砖了），再切到预埋阶段裸露的线管，"
                   u"最后用字幕列三个时间节点：水电进场前 / 封墙前 / 交房后。全程无口播，只上字幕。",
    },
    u"预算价格": {
        u"痛点": u"问预算永远问不到数，因为报价里有能砍的和绝对不能砍的两部分",
        u"标题": [u"3 房别墅全屋智能，钱到底花在哪几项",
                  u"报价单里这两项可以砍，这两项千万别砍",
                  u"先说清楚：不是全屋都值得做智能"],
        u"怎么拍": u"把报价拆成「预埋（砍不掉）」和「末端设备（可分期）」两块，"
                   u"用真实点位图配数字。价格必须交代来源，不许给一个凭空的总数。",
    },
    u"KNX总线": {
        u"痛点": u"灯光、空调、对讲各装一个 App，最后一个都不用",
        u"标题": [u"三个 App 各管一摊，用一个月就放弃了",
                  u"墙面为什么能只剩一块屏",
                  u"无线方案省钱，代价在第三年"],
        u"怎么拍": u"手机里三个 App 来回切的实拍 → 切到一块屏上全搞定。"
                   u"重点讲「为什么」，不是「多高级」。",
    },
    u"场景联动": {
        u"痛点": u"装了智能家居还在天天手动开灯，因为场景是照说明书设的，不是照生活设的",
        u"标题": [u"智能家居装完还在手动开灯，是场景设错了",
                  u"一天真正用得上的场景只有四个",
                  u"这个场景设完，家里人才开始用它"],
        u"怎么拍": u"拍一个具体动作：进门一按，玄关灯亮、窗帘关、空调到 24 度。"
                   u"然后说清另外三个场景是什么，别列十个。",
    },
    u"踩坑": {
        u"痛点": u"系统断连、售后找不到人、原厂停产后买不到配件",
        u"标题": [u"总线断连时，屏幕上会出现这行字",
                  u"选品牌先问一件事：五年后还买得到配件吗",
                  u"这个位置装错，以后每次维修都要拆柜子"],
        u"怎么拍": u"直接给断连提示的实拍画面（我们素材里有），"
                   u"再给配电箱标签清楚 / 不清楚的对比。真实缺点照说，可信度就是从这里来的。",
    },
    u"安防对讲": {
        u"痛点": u"门口来人，得跑到大门口或者掏手机翻 App",
        u"标题": [u"门口谁来了，不用跑也不用掏手机",
                  u"可视对讲和摄像头分开做，等于白装"],
        u"怎么拍": u"门铃响 → 屏上直接出画面 → 屏上开门，一镜到底。",
    },
    u"海外客群": {
        u"痛点": u"迪拜的精装房交付时弱电只做到毛坯标准，业主是收房才发现的",
        u"标题": [u"迪拜精装房交房时，弱电只给到这一步",
                  u"在迪拜自建房，智能家居要在哪一步介入"],
        u"怎么拍": u"拍交付标准里弱电那一页 + 实际墙内情况。"
                   u"这个方向只在小红书/视频号讲，抖音观众对迪拜交付标准无感。",
    },
}

# 兜底：一条数据都没有时也得给出可执行的第一条（不能让她对着空报告发呆）
COLD_START = u"装修阶段"


# ── 小工具 ────────────────────────────────────────────────────────────────
def log(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "replace").decode("ascii", "replace"))
    sys.stdout.flush()


def num(v):
    """CSV 里的空单元格 = 没拿到 → None。绝不当 0 用。"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", u"—"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else f


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def fmt(v, nd=2):
    if v is None:
        return u"—"
    if isinstance(v, float):
        return ("%%.%df" % nd) % v
    return "%s" % v


def parse_dt(s):
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime((s or "").strip(), f)
        except (ValueError, TypeError):
            continue
    return None


# ── 第 1 步：读 CSV、取最新快照 ────────────────────────────────────────────
def load(path):
    if not os.path.isfile(path):
        return [], []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        raw = [r for r in csv.DictReader(f)
               if (r.get(u"平台") or "").strip()]
    snaps = {}
    for r in raw:
        key = (r.get(u"平台"), r.get(u"作品ID"))
        snaps.setdefault(key, []).append(r)
    latest = []
    for key, rows in snaps.items():
        rows.sort(key=lambda r: (r.get(u"抓取时间") or ""))
        latest.append(rows[-1])
    return latest, snaps


# ── 第 2 步：按平台归一化 ──────────────────────────────────────────────────
def enrich(rows):
    """给每条作品算 日均播放 / 互动率 / 播放倍数 / 互动倍数 / 表现分。"""
    for r in rows:
        play = num(r.get(u"播放"))
        got = {f: num(r.get(f)) for f in ENG_FIELDS}
        eng = sum(v for v in got.values() if v is not None)
        have = [f for f, v in got.items() if v is not None]
        pub, grab = parse_dt(r.get(u"发布时间")), parse_dt(r.get(u"抓取时间"))
        days = None
        if pub and grab:
            days = max((grab - pub).total_seconds() / 86400.0, 0.5)
        r["_播放"] = play
        r["_互动数"] = eng if have else None
        r["_互动字段"] = have
        r["_天数"] = days
        # 日均播放：抹掉"发得早所以攒得多"。没有发布时间就退化成绝对播放，并做标记。
        r["_日均播放"] = (play / days) if (play is not None and days) else None
        r["_按绝对播放"] = play is not None and not days
        r["_互动率"] = (eng / float(play)) if (play and have) else None
        r["_标签"] = tag_of(r.get(u"标题"))
    for plat in sorted({r[u"平台"] for r in rows}):
        grp = [r for r in rows if r[u"平台"] == plat]
        m_play = median([r["_日均播放"] for r in grp]) or \
            median([r["_播放"] for r in grp])
        m_eng = median([r["_互动率"] for r in grp])
        for r in grp:
            base = r["_日均播放"] if r["_日均播放"] is not None else r["_播放"]
            r["_播放倍数"] = (base / m_play) if (base is not None and m_play) else None
            r["_互动倍数"] = (r["_互动率"] / m_eng) \
                if (r["_互动率"] is not None and m_eng) else None
            p, e = r["_播放倍数"], r["_互动倍数"]
            if p is not None and e is not None:
                r["_表现分"] = W_PLAY * p + W_ENG * e
                r["_分数口径"] = u"播放+互动"
            elif p is not None:
                r["_表现分"], r["_分数口径"] = p, u"只有播放"
            elif e is not None:
                r["_表现分"], r["_分数口径"] = e, u"只有互动"
            else:
                r["_表现分"], r["_分数口径"] = None, u"没数据"
        r_plat = {"平台": plat, "中位日均播放": m_play, "中位互动率": m_eng,
                  "条数": len(grp)}
        for r in grp:
            r["_平台基准"] = r_plat
    return rows


# ── 第 3 步：主题标签 ──────────────────────────────────────────────────────
def tag_of(title):
    t = title or ""
    hits = [tag for tag, kws in TAG_KEYWORDS if any(k in t for k in kws)]
    return hits or [u"未分类"]


def tag_table(rows):
    """(标签, 平台) → 表现分列表。同时给标签的跨平台汇总。"""
    per, overall = {}, {}
    for r in rows:
        if r["_表现分"] is None:
            continue
        for tag in r["_标签"]:
            per.setdefault((tag, r[u"平台"]), []).append(r["_表现分"])
            overall.setdefault(tag, []).append(r["_表现分"])
    return per, overall


# ── 第 4 步：发布时间 ──────────────────────────────────────────────────────
def bucket_of(pub):
    dt = parse_dt(pub)
    if not dt or (len((pub or "").strip()) <= 10):
        return None                 # 只有日期没有时分 → 不参与时段分析
    h = dt.hour
    for lo, hi, name in HOUR_BUCKETS:
        if lo <= h < hi or (hi > 24 and (h >= lo or h < hi - 24)):
            return name
    return u"深夜 23-6 点"


def time_table(rows):
    per = {}
    for r in rows:
        b = bucket_of(r.get(u"发布时间"))
        if b and r["_表现分"] is not None:
            per.setdefault(b, []).append(r["_表现分"])
    return per


# ── 时间序列：还在不在涨 ──────────────────────────────────────────────────
def momentum(snaps):
    """有两天以上快照的作品，算最近一段的日增播放。只有一天快照的一律不谈势头。"""
    out = []
    for (plat, wid), rows in snaps.items():
        rows = sorted(rows, key=lambda r: (r.get(u"抓取时间") or ""))
        pts = [(parse_dt(r.get(u"抓取时间")), num(r.get(u"播放")),
                r.get(u"标题")) for r in rows]
        pts = [p for p in pts if p[0] and p[1] is not None]
        if len(pts) < 2:
            continue
        (t0, v0, _), (t1, v1, title) = pts[-2], pts[-1]
        d = (t1 - t0).total_seconds() / 86400.0
        if d <= 0:
            continue
        out.append({"平台": plat, "标题": title, "日增播放": (v1 - v0) / d,
                    "跨天": d, "最新播放": v1})
    return sorted(out, key=lambda x: -x["日增播放"])


# ── 报告 ──────────────────────────────────────────────────────────────────
def choose(rows, per_tag, overall_tag, per_time):
    """挑出"下一条拍什么 / 发哪 / 什么时候"，并把挑选理由一起带出来。"""
    reasons = []
    # ① 主题：按跨平台平均表现分排，样本 >= MIN_PER_TAG 的才算有指示性
    ranked = sorted(
        ((tag, sum(v) / len(v), len(v)) for tag, v in overall_tag.items()
         if tag != u"未分类"),
        key=lambda x: -x[1])
    solid = [x for x in ranked if x[2] >= MIN_PER_TAG]
    blocked = [x for x in solid if x[0] in TASTE_BLOCK]
    usable = [x for x in solid if x[0] not in TASTE_BLOCK and x[0] in PAINPOINTS]
    if usable:
        tag, score, n = usable[0]
        reasons.append(u"「%s」在 %d 条作品里平均表现分 %.2f（1.00 = 平台自己的中位水平），"
                       u"是样本量够（≥%d 条）的方向里最高的。"
                       % (tag, n, score, MIN_PER_TAG))
    elif ranked:
        cand = [x for x in ranked
                if x[0] not in TASTE_BLOCK and x[0] in PAINPOINTS]
        if cand:
            tag, score, n = cand[0]
            reasons.append(u"⚠️ 没有任何主题攒够 %d 条样本。暂时选表现分最高的「%s」"
                           u"（只有 %d 条，平均 %.2f）—— 这是线索，不是结论。"
                           % (MIN_PER_TAG, tag, n, score))
        else:
            tag, score, n = COLD_START, None, 0
            reasons.append(u"现有数据里没有可用方向，按账号定位从「%s」起手。" % tag)
    else:
        tag, score, n = COLD_START, None, 0
        reasons.append(u"CSV 里没有可用数据，按账号定位从「%s」起手（冷启动）。" % tag)
    for b_tag, b_score, b_n in blocked:
        reasons.append(u"🚫「%s」数据上其实不差（%d 条，平均 %.2f），但**不采纳** ——"
                       u"炫房吸引来的是看热闹的人，不是准备装修的人。"
                       % (b_tag, b_n, b_score))

    # ② 平台：这个主题在哪个平台表现最好；样本不够就退回"哪个平台整体互动更好"
    plat_scores = sorted(
        ((p, sum(v) / len(v), len(v)) for (t, p), v in per_tag.items()
         if t == tag), key=lambda x: -x[1])
    ok_plat = [x for x in plat_scores if x[2] >= MIN_PER_TAG]
    if ok_plat:
        plat = ok_plat[0][0]
        reasons.append(u"「%s」在%s的平均表现分 %.2f（%d 条），高于其他平台。"
                       % (tag, plat, ok_plat[0][1], ok_plat[0][2]))
    else:
        cnt = {}
        for r in rows:
            cnt.setdefault(r[u"平台"], []).append(r["_互动率"])
        ranked_p = sorted(((p, median(v) or 0, len(v)) for p, v in cnt.items()),
                          key=lambda x: -x[1])
        big = [x for x in ranked_p if x[2] >= MIN_PER_PLATFORM]
        plat = (big or ranked_p or [(u"小红书", 0, 0)])[0][0]
        if plat_scores:
            reasons.append(u"⚠️ 「%s」在每个平台都不满 %d 条，按平台整体互动率中位数"
                           u"退一步选%s（%.2f%%）。"
                           % (tag, MIN_PER_TAG, plat,
                              100 * ((big or ranked_p)[0][1] or 0)))
        else:
            reasons.append(u"⚠️ 没有这个主题的历史数据，按平台整体互动率中位数选%s。" % plat)

    # ③ 时间：只有攒够样本的时段才敢说
    t_ranked = sorted(((b, sum(v) / len(v), len(v)) for b, v in per_time.items()),
                      key=lambda x: -x[1])
    t_ok = [x for x in t_ranked if x[2] >= MIN_PER_TAG]
    if t_ok:
        slot = t_ok[0][0]
        reasons.append(u"发布时段里「%s」平均表现分 %.2f（%d 条）最高。"
                       % (slot, t_ok[0][1], t_ok[0][2]))
    else:
        slot = None
        reasons.append(u"⚠️ 发布时段的样本还凑不出比较（每个时段都 <%d 条），"
                       u"这次不给时间结论。" % MIN_PER_TAG)
    return tag, plat, slot, reasons


def build_md(rows, snaps, csv_path):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    L = []
    if not rows:
        L.append(u"# NewMe 下一条拍什么 · %s\n" % now)
        L.append(u"## ⛔ 没有数据\n")
        L.append(u"`%s` 里没有任何作品记录。可能是：还没发过、没跑过 "
                 u"`stats_pull.py`、或者跑了但三个平台都没登录。\n" % csv_path)
        pp = PAINPOINTS[COLD_START]
        L.append(u"**先按账号定位拍这一条（冷启动，不是数据结论）：**\n")
        L.append(u"- 痛点：%s" % pp[u"痛点"])
        L.append(u"- 标题：%s" % pp[u"标题"][0])
        L.append(u"- 怎么拍：%s\n" % pp[u"怎么拍"])
        return "\n".join(L)

    per_tag, overall_tag = tag_table(rows)
    per_time = time_table(rows)
    mom = momentum(snaps)
    tag, plat, slot, reasons = choose(rows, per_tag, overall_tag, per_time)
    pp = PAINPOINTS.get(tag) or PAINPOINTS[COLD_START]

    plats = {}
    for r in rows:
        plats.setdefault(r[u"平台"], []).append(r)
    # ⚠️ 抓取日必须从**全部快照**里数，不能只数 rows（rows 是每条作品的最新一条，
    #    抓取日永远只有一个，会把"势头"分析错杀掉 —— 第一版就栽在这里）。
    days = sorted({(r.get(u"抓取时间") or "")[:10]
                   for v in snaps.values() for r in v if r.get(u"抓取时间")})
    n_rows = sum(len(v) for v in snaps.values())

    L.append(u"# NewMe 下一条拍什么 · %s\n" % now)
    span = (u"%s → %s" % (days[0], days[-1])) if len(days) > 1 else \
        (days[0] if days else u"未知")
    L.append(u"> 数据来源：`%s` ｜ %d 条作品 / %d 行快照 / 覆盖 %d 个抓取日（%s）"
             % (csv_path, len(rows), n_rows, len(days), span))
    L.append(u"> 平台分布：%s\n"
             % u"、".join(u"%s %d 条" % (p, len(v)) for p, v in
                          sorted(plats.items(), key=lambda x: -len(x[1]))))

    # 可信度警告放最前面
    warn = []
    if len(rows) < MIN_TOTAL:
        warn.append(u"**总样本只有 %d 条（<%d），下面所有内容都是方向性猜测，"
                    u"不是结论。**" % (len(rows), MIN_TOTAL))
    thin = [p for p, v in plats.items() if len(v) < MIN_PER_PLATFORM]
    if thin:
        warn.append(u"%s 的作品数不足 %d 条，这些平台的比较不作数。"
                    % (u"、".join(thin), MIN_PER_PLATFORM))
    if len(days) < 2:
        warn.append(u"只有一天的快照，**不能谈「还在涨 / 已经凉」** —— "
                    u"势头要至少隔一天再抓一次才看得出来。")
    if warn:
        L.append(u"## ⚠️ 先说可信度\n")
        for w in warn:
            L.append(u"- " + w)
        L.append("")

    # 一、结论
    L.append(u"## 一、结论（下一条照这个拍）\n")
    L.append(u"| | |")
    L.append(u"|---|---|")
    L.append(u"| **拍什么** | %s |" % pp[u"痛点"])
    L.append(u"| **主题方向** | %s |" % tag)
    L.append(u"| **主发平台** | %s |" % plat)
    L.append(u"| **什么时间发** | %s |"
             % (slot or u"数据不足，按常识发晚上 20-22 点，同时**这次开始记录发布时间**，"
                        u"下次就能算了"))
    L.append("")
    L.append(u"**三条标题草案**（都指向同一个痛点，不要改成泛泛的「全屋智能真香」）：\n")
    for i, t in enumerate(pp[u"标题"], 1):
        L.append(u"%d. %s" % (i, t))
    L.append(u"\n**怎么拍**：%s\n" % pp[u"怎么拍"])
    L.append(u"**另外两个平台怎么办**：同一个痛点换讲法，别一稿三投（同质内容会被降权）。"
             u"小红书讲决策过程给要装修的人抄作业；抖音前三秒先给反差画面；"
             u"视频号讲专业判断给同行和业主看。\n")

    # 二、依据
    L.append(u"## 二、依据（数字都在这儿，可以自己复核）\n")
    L.append(u"**怎么算的**：日均播放 = 播放 ÷ 发布至今天数；"
             u"互动率 = (点赞+评论+收藏+分享) ÷ 播放；"
             u"倍数 = 本条 ÷ **同平台中位数**；"
             u"表现分 = %.1f×播放倍数 + %.1f×互动倍数。"
             u"1.00 就是「跟这个平台自己的一般水平持平」。\n" % (W_PLAY, W_ENG))

    L.append(u"### 2.1 各平台基准线\n")
    L.append(u"| 平台 | 作品数 | 日均播放中位数 | 互动率中位数 |")
    L.append(u"|---|---|---|---|")
    for p, v in sorted(plats.items()):
        b = v[0]["_平台基准"]
        L.append(u"| %s | %d | %s | %s |"
                 % (p, b["条数"], fmt(b["中位日均播放"], 1),
                    u"—" if b["中位互动率"] is None
                    else u"%.2f%%" % (100 * b["中位互动率"])))
    L.append(u"\n平台之间**不要横向比这两列** —— 抖音随手几万播放、视频号几千就算好，"
             u"横着比等于永远推荐抖音。它们只用来做各自平台内部的分母。\n")

    L.append(u"### 2.2 每条作品的相对表现（按平台归一化后排序）\n")
    L.append(u"| 平台 | 标题 | 主题标签 | 播放 | 日均播放 | 互动率 | 完播率 | "
             u"播放倍数 | 互动倍数 | **表现分** | 口径 |")
    L.append(u"|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: -(r["_表现分"] or -9)):
        fin = num(r.get(u"完播率"))
        L.append(u"| %s | %s | %s | %s | %s | %s | %s | %s | %s | **%s** | %s |"
                 % (r[u"平台"], (r.get(u"标题") or u"（无标题）")[:22],
                    u"/".join(r["_标签"]), fmt(r["_播放"]),
                    fmt(r["_日均播放"], 0),
                    u"—" if r["_互动率"] is None else u"%.2f%%" % (100 * r["_互动率"]),
                    u"—" if fin is None else u"%.1f%%" % fin,
                    fmt(r["_播放倍数"]), fmt(r["_互动倍数"]),
                    fmt(r["_表现分"]), r["_分数口径"]))
    L.append(u"\n完播率**没有**进表现分：只有一个平台给这个字段，"
             u"混进去会让那个平台的分数跟别人不是一个口径。它只用来单独看"
             u"「前三秒抓不抓人」。\n")

    L.append(u"### 2.3 主题标签 × 平台（表格里是平均表现分，括号里是样本数）\n")
    tags = [t for t in sorted(overall_tag, key=lambda t: -sum(overall_tag[t])
                              / len(overall_tag[t]))]
    ps = sorted(plats)
    L.append(u"| 主题 | " + u" | ".join(ps) + u" | 跨平台平均 | 总样本 |")
    L.append(u"|---" * (len(ps) + 3) + u"|")
    for t in tags:
        cells = []
        for p in ps:
            v = per_tag.get((t, p))
            cells.append(u"—" if not v
                         else u"%.2f (%d)%s" % (sum(v) / len(v), len(v),
                                                u"" if len(v) >= MIN_PER_TAG
                                                else u" ⚠️"))
        av = overall_tag[t]
        L.append(u"| %s%s | %s | %.2f | %d |"
                 % (t, u" 🚫" if t in TASTE_BLOCK else u"",
                    u" | ".join(cells), sum(av) / len(av), len(av)))
    L.append(u"\n⚠️ = 样本 <%d 条，只能当线索。🚫 = 数据可能不差但按内容口味不采纳。"
             u"标签是**只从标题**关键词打的（正文和话题没进 CSV），所以偏粗。\n"
             % MIN_PER_TAG)

    L.append(u"### 2.4 发布时间 vs 表现\n")
    if per_time:
        L.append(u"| 发布时段 | 作品数 | 平均表现分 |")
        L.append(u"|---|---|---|")
        for b, v in sorted(per_time.items(), key=lambda x: -sum(x[1]) / len(x[1])):
            L.append(u"| %s | %d | %.2f |" % (b, len(v), sum(v) / len(v)))
        no_hour = len([r for r in rows if not bucket_of(r.get(u"发布时间"))])
        if no_hour:
            L.append(u"\n（另有 %d 条只抓到日期、没抓到具体时分，没参与这项分析。）"
                     % no_hour)
    else:
        L.append(u"一条都没有可用的发布时分，这项分析做不了。")
    L.append("")

    L.append(u"### 2.5 势头：还在涨的作品\n")
    if len(days) < 2:
        L.append(u"只有一天的快照，算不了。**隔一天再双击一次「跑数据」就有了。**")
    elif not mom:
        L.append(u"有多天快照，但没有一条作品同时出现在两天里（可能作品ID变了或没抓全）。")
    else:
        L.append(u"| 平台 | 标题 | 最新播放 | 日增播放 | 跨天 |")
        L.append(u"|---|---|---|---|---|")
        for m in mom[:8]:
            L.append(u"| %s | %s | %s | %s | %.1f 天 |"
                     % (m["平台"], (m["标题"] or u"（无标题）")[:22],
                        fmt(m["最新播放"]), fmt(m["日增播放"], 1), m["跨天"]))
        L.append(u"\n日增播放高的说明还在被推荐，这类主题值得**马上追一条**，"
                 u"不要等它凉了再拍。")
    L.append("")

    L.append(u"### 2.6 选择过程（逐条理由）\n")
    for r in reasons:
        L.append(u"- " + r)
    L.append("")

    # 三、不敢下结论的部分
    L.append(u"## 三、数据还不够，这些我不敢下结论\n")
    gaps = []
    # 每个缺失字段的**具体后果**，不能一句"数据缺失"糊过去
    CONSEQ = {
        u"完播率": u"没法判断前三秒有没有留住人，只能拿互动率当粗糙替代",
        u"涨粉": u"没法判断哪条真的带来了粉丝 —— 播放高但不涨粉的内容是白忙",
        u"收藏": u"互动率被低估（收藏是「我以后要用」的强信号，对装修类内容最值钱）",
        u"分享": u"互动率被低估，也看不出哪条被转给了家人/装修队",
        u"评论": u"看不出观众到底在问什么，问题本身就是下一条的选题",
    }
    for f in [u"完播率", u"涨粉", u"收藏", u"分享", u"评论"]:
        miss = [r for r in rows if num(r.get(f)) is None]
        if not miss:
            continue
        if len(miss) == len(rows):
            gaps.append(u"**%s 一条都没有** —— 三个平台的作品列表页都不给这个字段，"
                        u"要么改成进单条「数据详情」页抓（会慢很多），要么就一直缺。"
                        u"后果：%s。" % (f, CONSEQ[f]))
        else:
            plats_miss = u"、".join(sorted({r[u"平台"] for r in miss}))
            gaps.append(u"%s 只有 %d/%d 条有（缺的是 %s）。"
                        u"%s所以**跨平台不要比这一列**，只在同平台内部看。"
                        % (f, len(rows) - len(miss), len(rows), plats_miss,
                           (u"后果：%s。" % CONSEQ[f]) if f in
                           (u"完播率", u"涨粉") else
                           u"缺这个字段的平台互动率天然偏低，不是内容差 —— "
                           u"好在倍数是跟同平台比的，这个偏差被抵消掉了。"))
    thin_tags = sorted({t for t, v in overall_tag.items()
                        if len(v) < MIN_PER_TAG and t != u"未分类"})
    if thin_tags:
        gaps.append(u"这些主题只有 1 条数据，表现好坏都可能是偶然：%s。"
                    u"每个方向至少各拍 2 条才有可比性。" % u"、".join(thin_tags))
    unc = [r for r in rows if r["_标签"] == [u"未分类"]]
    if unc:
        gaps.append(u"%d 条作品的标题没命中任何关键词（未分类），"
                    u"它们的表现没进主题分析。要么标题起得太抽象，"
                    u"要么关键词表该补词了。" % len(unc))
    abs_only = [r for r in rows if r["_按绝对播放"]]
    if abs_only:
        gaps.append(u"%d 条没抓到发布时间，只能用绝对播放代替日均播放，"
                    u"发得早的会被高估。" % len(abs_only))
    fresh = [r for r in rows if r["_天数"] is not None and r["_天数"] < 1]
    if fresh:
        gaps.append(u"%d 条发出来还不到 24 小时（%s），"
                    u"它们的日均播放是拿不足一天的量除出来的，**会被高估** ——"
                    u"新片子刚发时有一波集中推荐。等它们满 3 天再回来看这张表更准。"
                    % (len(fresh), u"、".join((r.get(u"标题") or u"?")[:12]
                                              for r in fresh)))
    if len(days) < 2:
        gaps.append(u"只有一次抓取，**完全没有时间维度** —— "
                    u"分不清「这条爆了」和「这条发得久所以攒够了量」。"
                    u"最省事的补法：让她每天双击一次「跑数据」。")
    if len(rows) < MIN_TOTAL:
        gaps.append(u"总共 %d 条作品，任何「趋势」都是错觉。"
                    u"建议先按上面的方向连拍 6 条（每个主题 2 条）再回来看这张表。"
                    % len(rows))
    if not gaps:
        gaps.append(u"（这次没有明显缺口。）")
    for g in gaps:
        L.append(u"- " + g)
    L.append(u"\n---\n*本报告由 topic_next.py 生成，全部算法在文件头的 docstring 里，"
             u"没有黑箱。数据不对先查 stats_pull.py 抓错没有（看 stats_*.png 截图）。*")
    return "\n".join(L)


def main():
    args = [a for a in sys.argv[1:]]
    out = DEFAULT_MD
    if "-o" in args:
        i = args.index("-o")
        out = os.path.expanduser(args[i + 1])
        del args[i:i + 2]
    csv_path = os.path.expanduser(args[0]) if args else DEFAULT_CSV
    if not os.path.isabs(csv_path):
        cand = os.path.join(OUT_DIR, csv_path)
        csv_path = cand if os.path.isfile(cand) else csv_path

    log(u"读数据：%s" % csv_path)
    rows, snaps = load(csv_path)
    if rows:
        enrich(rows)
    log(u"  作品 %d 条 / 快照 %d 行" % (len(rows), sum(len(v) for v in snaps.values())))
    md = build_md(rows, snaps, csv_path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    log(u"✅ 报告已写出：%s" % out)
    log("")
    log(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
