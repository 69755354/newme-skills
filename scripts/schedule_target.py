#!/usr/bin/env python3
# -*- coding: utf-8 -*-
u"""定时目标时刻的**唯一**实现 —— publish_weixin / publish_xhs / publish_douyin 都 import 它。

为什么必须只有一份
------------------
这个项目已经被「同一条边界写在多处、没人比对」咬过五次。定时这件事以前就是
**三个脚本各写一份**内联的「今天来不及就顺延一天」，所以：
  · 想把 11 条内容排到 08-22 / 08-25 / 08-28 这些**不同日子**上，根本没有入口；
  · 抖音的「14 天内」这条硬边界写在注释里、代码里谁都不校验，超界了平台**静默拒绝**，
    脚本还会一路绿灯报成功。
现在日期解析、合法性检查、平台窗口都只在这个文件里。三个发布脚本里的
`bj_target` / `bj_stamp` 只剩字段适配（视频号要 pick/hhmm/ymd/text，另两个要
'YYYY-MM-DD HH:MM' 字符串），⛔ 不许在那边再写一份逻辑 —— selftest 里有绑定测试
（把本模块的 target() 换成哨兵，三个包装函数必须把哨兵原样带回来），复制粘贴会当场变红。

平台定时窗口（都是**实测**出来的，不是文档抄的）
--------------------------------------------
  视频号  最远 32 天    `wx_schedule_horizon.py`  2026-08-20 实测（可选 08-21~09-21）
  小红书  最远 14 天    `xhs_schedule_horizon.py` 2026-08-21 实测（北京 08-21 那天
                        面板亮到 09-04，9/5 起全灰）。⛔ 小红书时间框**自己不校验**：
                        键入 +64 天照样回读一致，「回读一致」是假判据。
  抖音    最远 14 天    平台自己写的是「2 小时后 ~ 14 天内」，卡边界会被**静默拒绝**，
                        所以按 336 小时**滚动**算（rolling=True），比按日历天更保守。
  下限：视频号/小红书留 45 分钟，抖音留 130 分钟（够 2 小时还有余量）。

用法
----
    import schedule_target as st
    t = st.target("douyin", "19:30", "2026-08-25")   # 方案里给了 schedule_bj_date
    t = st.target("douyin", "19:30")                 # 没给日期：今天来不及就顺延一天
    t["stamp"]  -> '2026-08-25 19:30'   （小红书/抖音要的格式）
    t["pick"]   -> 毫秒时间戳            （视频号 mp-date-picker 的 __vue__.pick）
  超界 / 过去 / 格式不对 → 抛 ScheduleError，调用方**必须**报错退出，
  ⛔ 不许静默顺延、不许当成功。

自检：`python3 schedule_target.py --selftest`（阳性 + 阴性对照 + 三个脚本的绑定测试）
"""
import datetime as dt
import re
import sys

# ── 冻结常量：三平台定时窗口。⛔ 单一真相，别在任何别的文件里再写一份 ──
WINDOW = {
    "weixin":      {"min_ahead_min": 45,  "horizon_days": 32, "rolling": False,
                    "measured": "wx_schedule_horizon.py 2026-08-20"},
    "xiaohongshu": {"min_ahead_min": 45,  "horizon_days": 14, "rolling": False,
                    "measured": "xhs_schedule_horizon.py 2026-08-21"},
    "douyin":      {"min_ahead_min": 130, "horizon_days": 14, "rolling": True,
                    "measured": u"平台文案「2 小时后~14 天内」+ 静默拒绝，按 336h 严算"},
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
EPOCH = dt.datetime(1970, 1, 1)


class ScheduleError(ValueError):
    u"""定时时刻不合法（格式错 / 已过去 / 太近 / 超出平台上限）。"""


def bj_now():
    u"""北京时间的现在。⚠️ 本机在迪拜 UTC+4，一律从 UTC 推，别用 localtime。"""
    return dt.datetime.utcnow() + dt.timedelta(hours=8)


def parse_hhmm(hhmm):
    m = TIME_RE.match((hhmm or "19:30").strip())
    if not m:
        raise ScheduleError(u"schedule_bj_time 格式不对：%r（要 HH:MM）" % hhmm)
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ScheduleError(u"schedule_bj_time 超范围：%r" % hhmm)
    return h, mi


def parse_ymd(ymd):
    u"""北京日期 YYYY-MM-DD。⚠️ 只认零填充的标准写法：'2026-8-2'、'20260822' 一律报错，
    不然 09-31 这种不存在的日子会一路混到浏览器里才炸（视频号那把尺子踩过）。"""
    s = (ymd or "").strip()
    if not DATE_RE.match(s):
        raise ScheduleError(u"schedule_bj_date 格式不对：%r（要 YYYY-MM-DD）" % ymd)
    try:
        return dt.date(*[int(x) for x in s.split("-")])
    except ValueError as e:
        raise ScheduleError(u"schedule_bj_date 不是真日期：%r（%s）" % (ymd, e))


def target(platform, hhmm, ymd=None, now=None):
    u"""算出目标发表时刻（北京墙上时间）。

    platform  weixin / xiaohongshu / douyin —— 决定用哪个窗口
    hhmm      '19:30'
    ymd       '2026-08-25'（方案里的 schedule_bj_date，可空）
              · 给了：**就按这一天**，来不及或超上限 → 抛 ScheduleError（⛔ 不顺延）
              · 没给：保持老行为 —— 今天该点还差够久就用今天，否则顺延一天
    返回全是 JSON 可序列化的字段（发布脚本会把它写进 *_test.json，别塞 datetime）。
    """
    if platform not in WINDOW:
        raise ScheduleError(u"不认识的平台：%r" % platform)
    w = WINDOW[platform]
    now = now or bj_now()
    h, mi = parse_hhmm(hhmm)
    explicit = bool((ymd or "").strip())

    if explicit:
        d = parse_ymd(ymd)
        t = dt.datetime(d.year, d.month, d.day, h, mi)
    else:
        t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if (t - now).total_seconds() < w["min_ahead_min"] * 60:
            t += dt.timedelta(days=1)

    ahead_min = (t - now).total_seconds() / 60.0
    days_ahead = (t.date() - now.date()).days
    if ahead_min < w["min_ahead_min"]:
        raise ScheduleError(
            u"%s 定时太近：北京 %s 距现在 %.0f 分钟，至少要 %d 分钟"
            u"（平台会静默拒绝）。改 schedule_bj_date 或换一天。"
            % (platform, t.strftime("%Y-%m-%d %H:%M"), ahead_min,
               w["min_ahead_min"]))
    if w["rolling"]:
        if ahead_min > w["horizon_days"] * 24 * 60:
            raise ScheduleError(
                u"%s 定时超上限：北京 %s 距现在 %.1f 天，平台只收 %d 天内"
                u"（%s）。这条要分批排，等日子近了再发。"
                % (platform, t.strftime("%Y-%m-%d %H:%M"), ahead_min / 1440.0,
                   w["horizon_days"], w["measured"]))
    elif days_ahead > w["horizon_days"]:
        raise ScheduleError(
            u"%s 定时超上限：北京 %s 是 %d 天后，平台最远只能排 %d 天"
            u"（%s）。这条要分批排，等日子近了再发。"
            % (platform, t.strftime("%Y-%m-%d %H:%M"), days_ahead,
               w["horizon_days"], w["measured"]))

    pick = int((t - EPOCH).total_seconds() - 8 * 3600) * 1000
    return {"platform": platform, "ymd": t.strftime("%Y-%m-%d"),
            "hhmm": t.strftime("%H:%M"), "stamp": t.strftime("%Y-%m-%d %H:%M"),
            "text": t.strftime(u"%Y年%m月%d日 %H:%M"), "pick": pick,
            "days_ahead": days_ahead, "explicit_date": explicit}


def plan_date(plan, platform):
    u"""方案 JSON 里取 schedule_bj_date：平台段优先，其次顶层。"""
    cfg = (plan.get(platform) or {}) if isinstance(plan, dict) else {}
    return cfg.get("schedule_bj_date") or (plan or {}).get("schedule_bj_date") or ""


# ── 自检 ──────────────────────────────────────────────────────────
def _selftest():
    u"""⚠️ 一律走 `import schedule_target as ST` 那个模块对象，不用本文件的全局名字：
    直接跑 `python3 schedule_target.py` 时本文件是 `__main__`，而三个发布脚本 import
    到的是 `schedule_target` —— **同一份代码被装载成两个模块**，两边的 ScheduleError
    是两个不同的类。第一版就是这么把绑定测试全打红的（哨兵打在 __main__ 上，
    包装函数拿的是另一个对象；异常也 except 不住）。"""
    import calendar
    import importlib
    ST = importlib.import_module("schedule_target")
    target = ST.target
    ScheduleError = ST.ScheduleError
    bad = []

    def ck(name, cond, extra=""):
        if cond:
            print(u"  ✅ %s" % name)
        else:
            print(u"  ❌ %s %s" % (name, extra))
            bad.append(name)

    def raises(name, fn):
        try:
            got = fn()
        except ScheduleError as e:
            print(u"  ✅ %s（阴性对照命中：%s）" % (name, str(e)[:60]))
            return
        except Exception as e:
            print(u"  ❌ %s 抛的不是 ScheduleError：%r" % (name, e))
            bad.append(name)
            return
        print(u"  ❌ %s 竟然过了：%s" % (name, got))
        bad.append(name)

    NOW = dt.datetime(2026, 8, 21, 3, 56)        # 北京时间，和实测那天对齐
    print(u"── 1. 给了 schedule_bj_date：算出来的时刻必须一模一样 ──")
    for plat in WINDOW:
        t = target(plat, "19:30", "2026-08-25", now=NOW)
        ck(u"%s 08-25 19:30" % plat,
           t["stamp"] == "2026-08-25 19:30" and t["ymd"] == "2026-08-25"
           and t["hhmm"] == "19:30" and t["days_ahead"] == 4
           and t["text"] == u"2026年08月25日 19:30" and t["explicit_date"],
           t)
    # pick 用**独立算法**重算一遍真相（calendar.timegm），不是抄一遍原式子
    t = target("weixin", "19:30", "2026-09-21", now=NOW)
    truth = calendar.timegm((2026, 9, 21, 19 - 8, 30, 0, 0, 0, 0)) * 1000
    ck(u"pick 时间戳 = 北京 19:30 的绝对时刻", t["pick"] == truth,
       u"%s ≠ %s" % (t["pick"], truth))

    print(u"── 2. 没给日期：老行为一点不能变 ──")
    # 03:56 时问 19:30 → 当天；问 03:00 → 已过，顺延到明天
    ck(u"当天还来得及就用当天",
       target("weixin", "19:30", None, now=NOW)["stamp"] == "2026-08-21 19:30")
    ck(u"来不及就顺延一天",
       target("weixin", "03:00", None, now=NOW)["stamp"] == "2026-08-22 03:00")
    ck(u"抖音 130 分钟余量：04:30 也要顺延",
       target("douyin", "04:30", None, now=NOW)["stamp"] == "2026-08-22 04:30")
    ck(u"小红书 45 分钟余量：05:00（64 分钟后）还收当天",
       target("xiaohongshu", "05:00", None, now=NOW)["stamp"] == "2026-08-21 05:00")
    ck(u"小红书 04:30（34 分钟后）不够 45 分钟 → 顺延",
       target("xiaohongshu", "04:30", None, now=NOW)["stamp"] == "2026-08-22 04:30")

    print(u"── 3. 阴性对照：越界必须报错（不许静默顺延）──")
    raises(u"抖音 +15 天", lambda: target("douyin", "19:30", "2026-09-05", now=NOW))
    raises(u"抖音 +14 天整（滚动 336h 卡边界）",
           lambda: target("douyin", "19:30", "2026-09-04", now=NOW))
    raises(u"小红书 +15 天", lambda: target("xiaohongshu", "19:30", "2026-09-05", now=NOW))
    raises(u"视频号 +33 天", lambda: target("weixin", "19:30", "2026-09-23", now=NOW))
    raises(u"过去的日子", lambda: target("weixin", "19:30", "2026-08-20", now=NOW))
    raises(u"今天但只剩几分钟", lambda: target("weixin", "04:10", "2026-08-21", now=NOW))
    raises(u"日期格式 2026-8-2", lambda: target("weixin", "19:30", "2026-8-2", now=NOW))
    raises(u"日期格式 20260822", lambda: target("weixin", "19:30", "20260822", now=NOW))
    raises(u"不存在的 09-31", lambda: target("weixin", "19:30", "2026-09-31", now=NOW))
    raises(u"时间格式 1930", lambda: target("weixin", "1930", "2026-08-25", now=NOW))
    raises(u"不认识的平台", lambda: target("kuaishou", "19:30", None, now=NOW))
    print(u"  ── 界内那一天必须**过**（不然上面的阴性全是白给）──")
    ck(u"小红书 +14 天（界内最后一天）",
       target("xiaohongshu", "19:30", "2026-09-04", now=NOW)["stamp"]
       == "2026-09-04 19:30")
    ck(u"视频号 +32 天（界内最后一天）",
       target("weixin", "19:30", "2026-09-22", now=NOW)["stamp"]
       == "2026-09-22 19:30")
    ck(u"抖音 +13 天（界内）",
       target("douyin", "19:30", "2026-09-03", now=NOW)["stamp"]
       == "2026-09-03 19:30")

    print(u"── 4. 绑定测试：三个发布脚本必须真的走这一份实现 ──")
    import publish_weixin as wx
    import publish_xhs as xhs
    import publish_douyin as dy
    # ⚠️ 4b 走的是**真的现在**（包装函数不吃 now 参数），所以日子必须相对今天算，
    #    写死 '2026-08-25' 的话过几天这条测试自己就红了（假红最伤人）。
    near = (ST.bj_now().date() + dt.timedelta(days=4)).isoformat()
    mods = [(u"publish_weixin.bj_target", wx, lambda: wx.bj_target("19:30", near),
             "weixin"),
            (u"publish_xhs.bj_stamp", xhs, lambda: xhs.bj_stamp("19:30", near),
             "xiaohongshu"),
            (u"publish_douyin.bj_stamp", dy, lambda: dy.bj_stamp("19:30", near),
             "douyin")]
    # 4a 哨兵：把 ST.target() 换掉，包装函数必须把哨兵的值带回来
    #     —— 谁再把日期逻辑复制回自己文件里，这条立刻红
    real = ST.target
    for name, mod, call, plat in mods:
        ck(u"%s import 的是同一个模块" % name,
           getattr(mod, "schedule_target", None) is ST)
        sent = {"platform": plat, "ymd": "1999-12-31", "hhmm": "01:02",
                "stamp": "1999-12-31 01:02", "text": u"哨兵", "pick": 12345,
                "days_ahead": 0, "explicit_date": True}
        ST.target = lambda *a, **k: sent
        try:
            got = call()
        finally:
            ST.target = real
        s = got["stamp"] if isinstance(got, dict) else got
        ck(u"%s 把活委托给 schedule_target" % name, s == sent["stamp"], got)
    # 4b 真调用：界内的值要对、界外必须抛（每个脚本用**自己平台**的上限）
    ck(u"wx 包装返回 pick/hhmm/ymd/text 四件套",
       set(["pick", "hhmm", "ymd", "text"]) <=
       set(wx.bj_target("19:30", "2026-08-25").keys()))
    ck(u"xhs 包装返回字符串戳",
       xhs.bj_stamp("19:30", "2026-08-25") == "2026-08-25 19:30")
    ck(u"dy 包装返回字符串戳",
       dy.bj_stamp("19:30", "2026-08-25") == "2026-08-25 19:30")
    far = (bj_now().date() + dt.timedelta(days=20)).isoformat()
    raises(u"抖音包装 +20 天要炸", lambda: dy.bj_stamp("19:30", far))
    raises(u"小红书包装 +20 天要炸", lambda: xhs.bj_stamp("19:30", far))
    ck(u"视频号包装 +20 天要过（它的上限是 32 天）",
       wx.bj_target("19:30", far)["ymd"] == far)

    print(u"\n%s selftest %s" % (u"✅" if not bad else u"❌",
                                 u"全绿" if not bad else u"红了 %d 条：%s"
                                 % (len(bad), bad)))
    return 0 if not bad else 2


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
