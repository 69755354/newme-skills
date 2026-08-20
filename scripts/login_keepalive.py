#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NewMe 三平台登录态保活 + 提前告警

为什么要有这个脚本：
    整条发布链条最大的不稳定来源不是选择器，是**登录态会静悄悄过期**。
    以前每次都是"要发片了才发现要扫码"，于是必须临时叫人，人不在就卡住。
    这里把发现时机提前到**每天凌晨**：只读不写地探一次三个平台，
    掉线就在日志和 stdout 里点名"哪个平台需要人工扫码"，白天再从容补一次码。

它做什么：
    1. 串行（一次只开一个浏览器）用各平台自己的 profile 打开创作者中心首页
    2. 用**每平台独立的判据函数**判断"还在登录态"——看账号名 / 头像 / 发布入口，
       不只看 URL（抖音的 URL 完全不可信，见下面 check_douyin 的注释）
    3. 还在登录的话做一次轻量活动（滚动 + 打开一次作品/笔记列表）让 cookie 续期
    4. 一行 JSON 追加进 ~/NewMe/logs/login_state.jsonl，并往 mcp-audit.log 记一条审计
    5. 有平台掉线 → 退出码 2 + stdout 醒目中文告警

它绝对不做什么（每条都是踩过坑或明确铁律）：
    ⛔ 不点任何"发表/发布/提交"按钮（点击一律过 newme_publish.guard_click 闸门）
    ⛔ 不点登录、不刷新登录页、不重新生成二维码 —— 一次扫码很贵，发现掉线只记录
    ⛔ 不 add_cookies 回灌 *_state.json（2026-08-19 两次登录态被毁都是回灌干的）
    ⛔ 不用 pkill -f chrome 这种宽杀，只精确杀 user-data-dir=<本平台 profile>
    ⛔ 同一时刻只开一个浏览器（这台机器只有 8 GB，曾因双开浏览器硬死机）

退出码：
    0  三平台（或指定的平台）都还在登录态
    2  至少一个平台掉线 —— 需要人工扫码
    3  这次没能检查（MCP_OFF / 可用内存不足 / 有别的自动化浏览器在跑 / 缺 playwright）
    4  都在登录态，但有关键 cookie 即将过期（默认 3 天内），建议主动补一次码

用法：
    python3 login_keepalive.py                     # 三个平台都查
    python3 login_keepalive.py douyin              # 只查抖音
    python3 login_keepalive.py --headful           # 显示窗口（放到屏幕外，等于最小化）
    python3 login_keepalive.py --min-free 1200     # 放宽内存闸门（默认 2000 MB）
    python3 login_keepalive.py --no-recheck        # 判成掉线时不做真窗口复检
可选环境变量：NEWME_MIN_FREE_MB / NEWME_WARN_DAYS / NEWME_KEEPALIVE_CDP=1（开 9223 调试口）
定时入口见同目录 login_keepalive_cron.sh。
"""
import json
import os
import subprocess
import sys
import time

OUT_DIR = os.path.expanduser(
    "~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
)
PROFILE_ROOT = os.path.expanduser("~/NewMe/profiles")
LOG_DIR = os.path.expanduser("~/NewMe/logs")
STATE_JSONL = os.path.join(LOG_DIR, "login_state.jsonl")
AUDIT_LOG = os.path.join(LOG_DIR, "mcp-audit.log")
MCP_OFF = os.path.expanduser("~/NewMe/MCP_OFF")
LOCK = os.path.join(LOG_DIR, ".keepalive.lock")

ORDER = ("weixin", "xiaohongshu", "douyin")
# 起浏览器的内存下限。8 GB 机器 + 一个 Chrome 约 1.5~2 GB，低于这个数就不开。
MIN_FREE_MB = int(os.environ.get("NEWME_MIN_FREE_MB") or 2000)
WARN_DAYS = float(os.environ.get("NEWME_WARN_DAYS") or 3)   # cookie 提前告警天数
LOCK_STALE_SEC = 1800
HEADFUL = False

# 复用发布器里的安全闸门与 shadow DOM 穿透，不另写一套（避免两处判据漂移）。
sys.path.insert(0, OUT_DIR)
try:
    from newme_publish import DEEP_ALL_JS, guard_click, RefusedToClick
    from newme_publish import P as PUB_PLATFORM
except Exception as _e:                      # 独立可跑，导入失败也不至于整体挂掉
    PUB_PLATFORM = {}
    RefusedToClick = RuntimeError
    DEEP_ALL_JS = r"""
    function deepAll(root) {
      const out = [];
      (function walk(r) {
        r.querySelectorAll('*').forEach((el) => {
          out.push(el);
          if (el.shadowRoot) walk(el.shadowRoot);
        });
      })(root);
      return out;
    }
    """

    def guard_click(loc, why="", timeout=8000, allow_nav=False):
        u"""降级版闸门：导入不到发布器时至少保住"不点提交按钮"这条底线。"""
        try:
            txt = (loc.inner_text(timeout=3000) or "").strip()
        except Exception:
            txt = ""
        for w in (u"发表", u"发布", u"提交", u"暂存离开", u"保存草稿", u"立即投稿"):
            if w in txt and len(txt) <= 10:
                raise RefusedToClick(u"拒绝点击「%s」" % txt[:20])
        loc.click(timeout=timeout)
        return txt[:20]


# ── 平台配置 ────────────────────────────────────────────────────
# home 一律用**创作者中心首页/落地页**，不用上传页：上传页更重，而且没必要。
# ⚠️ 小红书海外账号必须走 rednote.com，大陆域名会以 401 踢回登录页（假掉线）。
PLAT = {
    "weixin": {
        "name": u"微信视频号",
        "home": "https://channels.weixin.qq.com/platform",
        "list_url": None,                       # 全站 javascript:;，只能点进去
        "list_nav": [u"内容管理", u"视频"],
        "account": u"Newme-Tanya",
        # 会话相关 cookie（只记名字和过期时间，绝不记值）
        "key_cookies": ("sessionid", "wxuin", "slave_sid", "bizuin",
                        "sessionid_ss", "wxvid"),
    },
    "xiaohongshu": {
        "name": u"小红书",
        "home": "https://creator.rednote.com/publish/publish",
        "list_url": None,
        "list_nav": [u"笔记管理"],
        "account": u"小红薯_9446",
        "key_cookies": ("web_session", "galaxy_creator_session_id",
                        "galaxy.creator.beaker.session.id", "customerClientId",
                        "access-token-creator.rednote.com",
                        "access-token-creator.xiaohongshu.com", "a1"),
    },
    "douyin": {
        "name": u"抖音",
        # 扫码成功后抖音自己落到 /creator-micro/home，这里就用它当探测首页
        "home": "https://creator.douyin.com/creator-micro/home",
        "list_url": "https://creator.douyin.com/creator-micro/content/manage",
        "list_nav": [],
        "account": u"Tanya",
        "key_cookies": ("sessionid", "sessionid_ss", "sid_tt", "sid_guard",
                        "uid_tt", "passport_csrf_token"),
    },
}


def log(msg):
    print(msg)
    sys.stdout.flush()


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def audit(line):
    u"""往 MCP 审计日志追加一条。格式跟桥自己写的那种对齐，方便一起 grep。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] login_keepalive :: %s\n" % (now_str(), line))
    except Exception as e:
        log(u"  ⚠️ 写审计日志失败: %s" % e)


def append_state(rec):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(STATE_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log(u"  ⚠️ 写 login_state.jsonl 失败: %s" % e)


# ── 内存闸门与进程卫生 ──────────────────────────────────────────
def free_mb():
    u"""可用内存（MB）≈ free + inactive + speculative。跟本机内存闸门一个口径。

    这台机器只有 8 GB，2026-08-18 就是因为同时开了两个浏览器探针硬死机的。
    所以起浏览器之前必须量一次，量不到就当 0（宁可不跑）。"""
    try:
        out = subprocess.check_output(["vm_stat"], stderr=subprocess.STDOUT)
        txt = out.decode("utf-8", "ignore")
    except Exception:
        return 0
    page = 4096
    first = txt.splitlines()[0] if txt else ""
    if "page size of" in first:
        try:
            page = int(first.split("page size of")[1].split("bytes")[0].strip())
        except Exception:
            page = 4096
    pages = 0
    for label in ("Pages free", "Pages inactive", "Pages speculative"):
        for line in txt.splitlines():
            if line.startswith(label + ":"):
                try:
                    pages += int(line.split(":")[1].strip().rstrip("."))
                except Exception:
                    pass
                break
    return int(pages * page / 1048576)


def profile_dir(key):
    return os.path.join(PROFILE_ROOT, key)


def own_browser_pids():
    u"""列出正跑着的、用我们自己 profile 的浏览器进程。

    ⚠️ 匹配串必须锚在 `user-data-dir=<PROFILE_ROOT>` 上。只写 user-data-dir
    会把 Claude 桌面版自己的 Helper 进程全捞出来（实测），更别提宽杀了。"""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "user-data-dir=%s" % PROFILE_ROOT],
            stderr=subprocess.DEVNULL)
        return [p for p in out.decode().split() if p.strip()]
    except Exception:
        return []


def kill_profile_browser(key):
    u"""精确收尾：只杀 user-data-dir 正好是本平台 profile 的进程。

    ⛔ 绝对不许 pkill -f chrome / killall Google Chrome —— 那会连用户
    自己正在用的浏览器一起杀掉。匹配串写全路径，宁可杀不干净也不能杀多。"""
    pat = "user-data-dir=%s" % profile_dir(key)
    try:
        subprocess.call(["pkill", "-TERM", "-f", pat],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def take_lock():
    u"""防止两个 keepalive 同时跑（会变成两个浏览器）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.exists(LOCK):
            age = time.time() - os.path.getmtime(LOCK)
            if age < LOCK_STALE_SEC:
                return False, u"另一个 keepalive 正在跑（锁文件 %d 秒前更新）" % age
            os.remove(LOCK)          # 陈旧锁（上次崩了没清），可以接管
        with open(LOCK, "w", encoding="utf-8") as f:
            f.write("%d %s\n" % (os.getpid(), now_str()))
        return True, ""
    except Exception as e:
        return True, u"（锁文件处理异常，继续跑：%s）" % e


def drop_lock():
    try:
        if os.path.exists(LOCK):
            os.remove(LOCK)
    except Exception:
        pass


# ── 页面观测 ────────────────────────────────────────────────────
# 只取**可见**元素自身的文字，并穿透 shadow root。两个原因：
#   1. 视频号整站在 wujie 的 shadow root 里，document.body.innerText 抓不到侧栏
#   2. 视频号页面尾部有一堆 Vue 预渲染的隐藏弹窗模板（「切换视频号」「我知道了」），
#      用 textContent 会把它们当成真文字，判据立刻污染
VISIBLE_DEEP_TEXT_JS = r"""
() => {
  """ + DEEP_ALL_JS + r"""
  const parts = [];
  for (const el of deepAll(document)) {
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.nodeValue;
    own = own.replace(/\s+/g, ' ').trim();
    if (!own || own.length > 120) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    let st;
    try { st = getComputedStyle(el); } catch (e) { continue; }
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    if (parseFloat(st.opacity || '1') < 0.05) continue;
    parts.push(own);
  }
  return parts.join('\n').slice(0, 60000);
}
"""

# 头像：只有登录后才会渲染。⚠️ 只回传 class / 尺寸 / 域名，
# **不回传完整 src** —— 头像 URL 常带签名参数，写进日志等于泄凭据。
AVATAR_JS = r"""
() => {
  """ + DEEP_ALL_JS + r"""
  const hits = [];
  for (const el of deepAll(document)) {
    const tag = el.tagName.toLowerCase();
    const cls = String(el.className || '');
    const src = el.getAttribute && (el.getAttribute('src') || '') || '';
    const isImg = tag === 'img';
    const looks = /avatar|head-?img|headimg|profile-?pic|user-?pic|头像/i;
    if (!(isImg && looks.test(src + ' ' + cls)) && !looks.test(cls)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 16 || r.height < 16 || r.width > 160) continue;
    let host = '';
    try { host = new URL(src, location.href).host; } catch (e) { host = ''; }
    hits.push({tag: tag, cls: cls.slice(0, 40),
               w: Math.round(r.width), h: Math.round(r.height), host: host});
    if (hits.length >= 4) break;
  }
  return hits;
}
"""


def observe(page):
    u"""抓一次页面观测数据，三个判据函数共用。"""
    obs = {"url": page.url}
    try:
        obs["text"] = page.evaluate(VISIBLE_DEEP_TEXT_JS) or ""
    except Exception as e:
        obs["text"] = ""
        obs["text_err"] = str(e)[:120]
    try:
        obs["avatars"] = page.evaluate(AVATAR_JS) or []
    except Exception:
        obs["avatars"] = []
    return obs


def count_sel(page, sel):
    try:
        return page.locator(sel).count()
    except Exception:
        return 0


def hits(text, words):
    return [w for w in words if w in text]


def verdict(name, strong, weak, negative, extra=None):
    u"""统一的结论组装。

    规则：只要命中任何一个"登录页专有"负面词 → 判掉线（不给翻盘机会，
    因为登录页出现就意味着会话已经废了）。否则必须至少有一个**强证据**
    （账号名 / 头像 / 只有登录后才存在的发布入口）才敢说"还在登录"，
    弱证据（两个以上侧栏菜单文字）合起来才顶一个强证据。"""
    d = {"platform": name, "strong": strong, "weak": weak,
         "negative": negative}
    if extra:
        d.update(extra)
    if negative:
        d["ok"] = False
        d["reason"] = u"页面上出现登录页特征：%s" % u"/".join(negative)
        return d
    if strong:
        d["ok"] = True
        d["reason"] = u"命中强证据：%s" % u"/".join(strong)
        return d
    if len(weak) >= 2:
        d["ok"] = True
        d["reason"] = u"无登录页特征 + 侧栏菜单齐全：%s" % u"/".join(weak)
        return d
    d["ok"] = False
    d["reason"] = u"既没有账号名/头像/发布入口，也没凑够侧栏菜单（弱证据 %d 个）" % len(weak)
    return d


# ── 三个平台各自的登录判据（每平台一个函数，互不复用措辞）────────
def check_weixin(page, obs):
    u"""视频号：判据在 wujie 的 shadow root 里，必须用穿透后的可见文字。

    坑（2026-08-19）：只查 URL 里有没有 'login' + 「扫码登录」四个字，掉登录时
    两个都没命中 —— 视频号登录页写的是**「登录视频号助手」**，措辞跟别家都不一样，
    于是脚本以为已登录，一路点到导航才失败。

    坑二（2026-08-20，反过来的假阳性）：顶层文档里**常驻**「登录视频号助手」这段
    营销文案，即使已登录也在。所以文字不能当唯一判据 —— 硬信号是
    **有没有 frame 的 URL 里带 login.html / qrconnect**（真登录页才会加载它们），
    这条在 stats_pull.py 里也是这么判的，两边保持一致。
    """
    t = obs["text"]
    furls = " ".join((f.url or "") for f in page.frames)
    qr = ("login.html" in furls) or ("qrconnect" in furls)
    neg = []
    if qr:
        neg.append(u"页面挂着扫码 frame（login.html/qrconnect）")
    neg += hits(t, [u"请使用微信扫码", u"使用微信扫描二维码",
                    u"登录失效", u"重新登录"])
    # ⚠️ 「登录视频号助手」「扫码登录」不能进负面词：已登录时顶层也有这两段文字
    strong = []
    if PLAT["weixin"]["account"] in t:
        strong.append(u"账号名 %s" % PLAT["weixin"]["account"])
    if obs["avatars"]:
        strong.append(u"头像元素×%d" % len(obs["avatars"]))
    # 「发表视频」是内容管理页的橙色新建按钮，只有登录后才有 —— 算发布入口
    for w in (u"发表视频", u"账号中心", u"视频管理"):
        if w in t:
            strong.append(u"登录后专属入口「%s」" % w)
            break
    weak = hits(t, [u"内容管理", u"数据中心", u"直播管理", u"互动管理",
                    u"创作者服务", u"首页"])
    return verdict("weixin", strong, weak, neg)


def check_xiaohongshu(page, obs):
    u"""小红书：上传控件 input.upload-input 是最硬的登录后信号。

    坑（2026-08-18）：海外号访问大陆域名会 401 跳 /login?redirectReason=401，
    长得跟登录过期一模一样。所以这里 home 写死 rednote.com；如果 URL 里出现
    xiaohongshu.com/login，那更可能是域名走错而不是真掉线，reason 里点明。
    """
    t = obs["text"]
    neg = hits(t, [u"手机号登录", u"短信登录", u"扫码登录", u"新用户扫码",
                   u"登录后可", u"验证码登录", u"其他登录方式"])
    strong = []
    if PLAT["xiaohongshu"]["account"] in t:
        strong.append(u"账号名 %s" % PLAT["xiaohongshu"]["account"])
    if obs["avatars"]:
        strong.append(u"头像元素×%d" % len(obs["avatars"]))
    n_upload = count_sel(page, "input.upload-input")
    if n_upload:
        strong.append(u"上传控件 input.upload-input×%d（登录后才渲染）" % n_upload)
    weak = hits(t, [u"发布笔记", u"笔记管理", u"数据中心", u"创作服务",
                    u"上传视频", u"创作灵感"])
    d = verdict("xiaohongshu", strong, weak, neg)
    if not d["ok"] and "xiaohongshu.com" in (obs["url"] or ""):
        d["reason"] += u"（注意：URL 落到了大陆域名，先怀疑域名走错而不是掉登录）"
    return d


def check_douyin(page, obs):
    u"""抖音：⚠️ **URL 完全不能当判据**，这里连栽过两次。

    1) 编辑页自己的 URL 就长得像成功页（/content/post/video），拿 URL 匹配必然假阳性；
    2) 扫码成功后先落 /creator-micro/home，那页上没有"发布视频"字样，
       反过来又会把已登录判成未登录。
    所以只认页面元素：账号昵称 / 头像 / 「抖音号」这张只有登录后才有的资料卡，
    再加侧栏菜单当弱证据。未登录时抖音整页是营销页 + 登录弹窗，负面词很好抓。
    """
    t = obs["text"]
    neg = hits(t, [u"扫码登录", u"验证码登录", u"密码登录", u"手机号登录",
                   u"请使用抖音", u"立即登录", u"登录后即可", u"同意并继续"])
    strong = []
    if u"抖音号" in t:
        strong.append(u"资料卡「抖音号」（登录后才有）")
    if PLAT["douyin"]["account"] in t:
        strong.append(u"账号名 %s" % PLAT["douyin"]["account"])
    if obs["avatars"]:
        strong.append(u"头像元素×%d" % len(obs["avatars"]))
    weak = hits(t, [u"作品管理", u"内容管理", u"数据总览", u"创作灵感",
                    u"发布视频", u"作品数据", u"我的作品", u"账号诊断"])
    return verdict("douyin", strong, weak, neg)


CHECKERS = {"weixin": check_weixin,
            "xiaohongshu": check_xiaohongshu,
            "douyin": check_douyin}


# ── cookie 过期时间 ─────────────────────────────────────────────
def cookie_report(ctx, key):
    u"""读关键 cookie 的过期时间。⚠️ 只取 name / domain / expires，
    **绝不读 value** —— 这份数据要落盘进日志的。"""
    rep = {"checked": list(PLAT[key]["key_cookies"]), "found": {}, "soonest": None}
    try:
        cookies = ctx.cookies()
    except Exception as e:
        rep["err"] = str(e)[:120]
        return rep
    want = set(PLAT[key]["key_cookies"])
    soonest = None
    for c in cookies:
        n = c.get("name")
        if n not in want:
            continue
        exp = c.get("expires")
        if exp is None or exp <= 0:
            rep["found"][n] = u"会话级（关浏览器即失效，靠 profile 保活）"
            continue
        iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))
        days = (exp - time.time()) / 86400.0
        rep["found"][n] = "%s（还剩 %.1f 天）" % (iso, days)
        if soonest is None or exp < soonest:
            soonest = exp
    if soonest:
        rep["soonest"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(soonest))
        rep["soonest_days"] = round((soonest - time.time()) / 86400.0, 2)
    return rep


# ── 轻量活动：让会话续期，且绝不写入任何东西 ─────────────────────
def light_activity(page, key):
    u"""滚一下 + 打开一次作品/笔记列表。目的只有一个：让服务端看到一次真实活动，
    把滑动过期的 session 往后顶。**只读**：不填表、不上传、不点任何提交按钮，
    所有点击都过 guard_click 闸门（抖音那边干脆不点，直接 goto 列表页）。"""
    done = []
    try:
        page.mouse.wheel(0, 700)
        time.sleep(1.0)
        page.mouse.wheel(0, -700)
        done.append(u"滚动")
    except Exception:
        try:
            page.evaluate("() => { window.scrollBy(0, 700); window.scrollBy(0, -700); }")
            done.append(u"滚动(JS)")
        except Exception:
            pass

    url = PLAT[key]["list_url"]
    if url:
        # 抖音的作品管理页可以直接 goto，是纯读页面，比点导航稳
        try:
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(4)
            done.append(u"打开作品管理页")
        except Exception as e:
            done.append(u"打开列表页失败(%s)" % str(e)[:40])
    for label in PLAT[key]["list_nav"]:
        # 视频号全站是 javascript:; 链接，只能点；小红书的「笔记管理」也走点。
        # 这些文字都不在 FORBIDDEN 里，闸门会放行；万一平台改文案撞上"发布"，
        # guard_click 会直接抛异常，我们宁可不做活动也不冒误点风险。
        try:
            loc = page.locator("text=\"%s\"" % label)
            got = None
            for i in range(min(loc.count(), 6)):
                if loc.nth(i).is_visible():
                    got = loc.nth(i)
                    break
            if got is None:
                done.append(u"没找到「%s」" % label)
                continue
            guard_click(got, u"保活：打开列表", timeout=8000)
            done.append(u"点开「%s」" % label)
            time.sleep(3)
        except RefusedToClick as e:
            done.append(u"闸门拦下「%s」：%s" % (label, str(e)[:40]))
        except Exception as e:
            done.append(u"点「%s」失败(%s)" % (label, str(e)[:40]))
    try:
        page.mouse.wheel(0, 500)
        time.sleep(0.8)
    except Exception:
        pass
    return done


# ── 单平台一次检查 ──────────────────────────────────────────────
def check_one(p, key, headful=None):
    u"""起一个浏览器 → 判登录 → （在线才）做轻量活动 → 关掉。返回记录 dict。

    headful=None 表示跟随全局设置；复检时会显式传 True（见 main 里的说明）。"""
    if headful is None:
        headful = HEADFUL
    plat = PLAT[key]
    rec = {"ts": now_str(), "platform": key, "name": plat["name"],
           "ok": False, "headless": not headful}
    profile = profile_dir(key)
    os.makedirs(profile, exist_ok=True)

    args = ["--disable-blink-features=AutomationControlled",
            "--no-first-run", "--no-default-browser-check"]
    if headful:
        # "最小化"用屏幕外窗口实现：既不抢用户焦点，也不用 headless
        args += ["--window-position=-32000,-32000", "--window-size=1280,900"]
    if os.environ.get("NEWME_KEEPALIVE_CDP"):
        # 用 9223 而不是发布器的 9222：万一发布器正开着，端口撞车会把两边都搞坏
        args.append("--remote-debugging-port=9223")

    log(u"\n[%s] 起浏览器（%s，profile=%s）"
        % (plat["name"], u"有窗口·屏幕外" if headful else "headless", key))
    ctx = None
    try:
        # ⚠️ headless 的 UA 里带「HeadlessChrome」——微信这种风控站可能因此把会话
        #    当异地新设备作废。既然只是探一下，就把 UA 伪回真 Chrome，代价为零。
        real_ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/139.0.0.0 Safari/537.36")
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile, channel="chrome", headless=not headful,
            no_viewport=True, args=args,
            user_agent=None if headful else real_ua)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30000)
        # ⛔ 这里绝对不 add_cookies(*_state.json)。2026-08-19 连着两次
        #    "刚登录 → 跑一下脚本 → 又变未登录"都是回灌旧 cookie 覆盖掉的。
        page.goto(plat["home"], wait_until="domcontentloaded")
        time.sleep(6)                      # 抖音/小红书首屏要几秒才渲染出资料卡

        obs = observe(page)
        d = CHECKERS[key](page, obs)
        rec["ok"] = bool(d["ok"])
        rec["reason"] = d["reason"]
        rec["evidence"] = {"strong": d["strong"], "weak": d["weak"],
                           "negative": d["negative"]}
        rec["url_seen"] = obs["url"][:120]          # 只作参考，不是判据
        rec["avatars"] = obs["avatars"]
        rec["cookies"] = cookie_report(ctx, key)

        log(u"  判定：%s —— %s" % (u"✅ 还在登录态" if rec["ok"] else u"❌ 掉登录了",
                                  rec["reason"]))
        if rec["cookies"].get("soonest"):
            log(u"  关键 cookie 最早过期：%s（%.1f 天后）"
                % (rec["cookies"]["soonest"], rec["cookies"]["soonest_days"]))

        if rec["ok"]:
            rec["activity"] = light_activity(page, key)
            log(u"  轻量活动：%s" % u"、".join(rec["activity"]))
            # 在线才刷新快照；掉线时存下来等于用废 cookie 覆盖掉好备份
            try:
                ctx.storage_state(path=os.path.join(
                    PROFILE_ROOT, "%s_state.json" % key))
                rec["state_snapshot"] = True
            except Exception as e:
                rec["state_snapshot"] = str(e)[:80]
        else:
            # ⛔ 不点登录、不刷新、不切二维码 —— 一次扫码很贵，绝不浪费。
            #    只留一张截图给人看，然后立刻走。
            shot = os.path.join(
                OUT_DIR, "keepalive_%s_logged_out_%s.png"
                % (key, time.strftime("%m%d_%H%M%S")))
            try:
                page.screenshot(path=shot, full_page=False)
                rec["shot"] = shot
                log(u"  📷 掉线证据：%s" % os.path.basename(shot))
            except Exception:
                pass
            log(u"  （不做任何登录动作、不刷新二维码，交给人工处理）")
    except Exception as e:
        rec["ok"] = False
        rec["reason"] = u"检查过程出错：%s" % str(e)[:200]
        rec["error"] = str(e)[:300]
        log(u"  ❌ %s" % rec["reason"])
    finally:
        if ctx is not None:
            try:
                ctx.close()
            except Exception:
                pass
        # 关不干净就精确杀。匹配串锚死本平台 profile 全路径。
        kill_profile_browser(key)
        time.sleep(3)
        log(u"  🧹 已关闭 %s 的浏览器（剩余可用内存 %d MB）"
            % (plat["name"], free_mb()))
    return rec


def main():
    global HEADFUL, MIN_FREE_MB
    argv = sys.argv[1:]
    HEADFUL = "--headful" in argv
    if "--min-free" in argv:
        try:
            MIN_FREE_MB = int(argv[argv.index("--min-free") + 1])
        except Exception:
            pass
    queue = [a for a in argv if a in PLAT] or list(ORDER)

    log("=" * 62)
    log(u"  NewMe 登录态保活 · %s" % now_str())
    log(u"  平台队列（串行，一次只开一个浏览器）：%s"
        % u" → ".join(PLAT[k]["name"] for k in queue))
    log("=" * 62)
    audit(u"开始检查 %s（headless=%s）" % (",".join(queue), not HEADFUL))

    # 关卡一：总开关
    if os.path.exists(MCP_OFF):
        log(u"\n⛔ ~/NewMe/MCP_OFF 存在，本次什么都不做。")
        audit(u"跳过：MCP_OFF 存在")
        append_state({"ts": now_str(), "platform": "-", "ok": None,
                      "skipped": "MCP_OFF"})
        return 3

    # 关卡二：别的自动化浏览器还开着（很可能是发布器正在跑）
    pids = own_browser_pids()
    if pids:
        log(u"\n⛔ 已经有用 NewMe profile 的浏览器在跑（pid %s）。"
            % ",".join(pids))
        log(u"   这台机器只有 8 GB，不叠第二个浏览器。本次跳过，不算掉线。")
        audit(u"跳过：已有 profile 浏览器在跑 pid=%s" % ",".join(pids))
        append_state({"ts": now_str(), "platform": "-", "ok": None,
                      "skipped": "已有浏览器在跑", "pids": pids})
        return 3

    # 关卡三：内存
    mb = free_mb()
    log(u"\n可用内存 %d MB（下限 %d MB）" % (mb, MIN_FREE_MB))
    if mb < MIN_FREE_MB:
        log(u"⛔ 内存不够，不起浏览器（宁可这次不查，也不能再把机器搞死机一次）。")
        audit(u"跳过：可用内存 %d MB < %d MB" % (mb, MIN_FREE_MB))
        append_state({"ts": now_str(), "platform": "-", "ok": None,
                      "skipped": "内存不足", "free_mb": mb})
        return 3

    # 关卡四：并发锁
    got, why = take_lock()
    if not got:
        log(u"\n⛔ %s，本次跳过。" % why)
        audit(u"跳过：%s" % why)
        append_state({"ts": now_str(), "platform": "-", "ok": None,
                      "skipped": why})
        return 3
    if why:
        log(why)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        drop_lock()
        log(u"\n⛔ 找不到 playwright，没法检查。")
        audit(u"跳过：缺 playwright")
        append_state({"ts": now_str(), "platform": "-", "ok": None,
                      "skipped": "缺 playwright"})
        return 3

    results = {}
    try:
        with sync_playwright() as p:
            for i, key in enumerate(queue):
                if i:
                    mb = free_mb()
                    if mb < MIN_FREE_MB:
                        log(u"\n⛔ 剩余内存只有 %d MB，剩下的平台不查了（不算掉线）" % mb)
                        for k in queue[i:]:
                            append_state({"ts": now_str(), "platform": k,
                                          "ok": None, "skipped": "内存不足",
                                          "free_mb": mb})
                        break
                rec = check_one(p, key)
                append_state(rec)
                audit(u"%s ok=%s 判据=%s" % (key, rec["ok"],
                                             (rec.get("reason") or "")[:90]))

                # 判成掉线时，用**真窗口**再验一次才敢告警。
                # 理由：headless 的 UA/指纹跟正常窗口不一样，抖音这种有风控的站
                # 完全可能只对 headless 弹登录页。误报的代价很实：会白白催人去扫
                # 一次码 —— 而"不浪费扫码"是这条链子的铁律。复检仍然串行、
                # 仍然只开一个浏览器（上一个已经在 finally 里关掉了）。
                if (not rec["ok"]) and (not HEADFUL) and "--no-recheck" not in argv:
                    mb2 = free_mb()
                    if mb2 < MIN_FREE_MB:
                        rec["recheck"] = u"内存只剩 %d MB，没做真窗口复检" % mb2
                        log(u"  ⚠️ %s" % rec["recheck"])
                    else:
                        log(u"  🔁 headless 判成掉线 —— 换真窗口（屏幕外）复检一次，"
                            u"避免误报催人扫码")
                        rec2 = check_one(p, key, headful=True)
                        rec2["recheck_of"] = rec.get("reason")
                        append_state(rec2)
                        audit(u"%s 复检 ok=%s" % (key, rec2["ok"]))
                        if rec2["ok"]:
                            log(u"  ✅ 复检结果是**在线** —— 上一轮是 headless 误报，"
                                u"按在线记账，不告警")
                        rec = rec2
                results[key] = rec
    finally:
        drop_lock()

    # ── 汇总 ──
    down = [k for k, r in results.items() if not r["ok"]]
    warn = [k for k, r in results.items()
            if r["ok"] and (r.get("cookies") or {}).get("soonest_days") is not None
            and r["cookies"]["soonest_days"] <= WARN_DAYS]

    log("\n" + "=" * 62)
    for k in queue:
        r = results.get(k)
        if r is None:
            log(u"  %-8s ⏭ 本次未检查" % PLAT[k]["name"])
            continue
        log(u"  %-8s %s  %s" % (PLAT[k]["name"],
                                u"✅ 在线" if r["ok"] else u"❌ 掉线",
                                (r.get("reason") or "")[:70]))
    log("=" * 62)
    log(u"日志：%s" % STATE_JSONL)

    if down:
        names = u"、".join(PLAT[k]["name"] for k in down)
        log(u"")
        log(u"🚨" * 20)
        log(u"🚨 需要人工扫码的平台：%s" % names)
        log(u"🚨 现在还没到发布时间，请白天抽两分钟补一次码：")
        for k in down:
            log(u"🚨   · %s → 打开 %s，用手机扫码登录"
                % (PLAT[k]["name"], PLAT[k]["home"]))
        log(u"🚨 脚本没有点登录、没有刷新二维码，登录页还是原样。")
        log(u"🚨" * 20)
        audit(u"告警：掉线平台 %s" % ",".join(down))
        return 2

    if warn:
        log(u"\n⚠️ 以下平台还在线，但关键 cookie %.0f 天内就过期，建议主动补一次码：" % WARN_DAYS)
        for k in warn:
            log(u"   · %s（最早过期 %s，还剩 %.1f 天）"
                % (PLAT[k]["name"], results[k]["cookies"]["soonest"],
                   results[k]["cookies"]["soonest_days"]))
        audit(u"预警：即将过期 %s" % ",".join(warn))
        return 4

    log(u"\n✅ 全部在线，登录态已顺手续期，不需要任何人工操作。")
    audit(u"结束：全部在线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
