# newme-skills

NewMe（迪拜智能家居）实际在跑的三套作业规程 + 配套脚本。

这个仓库是**给人和给 AI 助手（ChatGPT / Codex / Claude）共用的一份事实来源**：
`skills/` 里是规程，`scripts/` 里是这些规程真正调用的脚本。两边必须一致 —— 改了脚本行为，
就要改对应 SKILL.md，反过来也一样。

> ⚠️ **仓库里没有素材、没有登录态、没有密钥。** 全部需要自备（见「跑起来需要什么」）。
> 客户别墅实拍素材与成片按约定绝不上传任何第三方，包括这里。

**接手先读 [HANDOFF.md](HANDOFF.md)** —— 项目定位、现在做到哪一步、素材缺口、下一步该干什么、以及全部踩过的坑。

---

## 目录怎么读

```
AGENTS.md                                  ← AI 助手先读这个：合并后的硬规矩 + 假判据清单 + 各平台坑
skills/
  newme-shortvideo-pipeline/SKILL.md       ← 短视频：素材筛查 → 脚本 → 合片 → 三平台定时发布 → 数据回读 → 选题
  knx-quotation/SKILL.md                   ← KNX 报价：线材用量、穿线人工、报价表结构、accept.py 验收、点位图
  excel-recalc-verify/SKILL.md             ← Excel 公式重算与排版校验（行高截断的唯一可靠查法）
scripts/                                   ← 只放已过回归的生产脚本，探针/废弃版本不进这里
examples/publish_plan.template.json        ← 三平台发布方案（方案.json）的字段模板
```

阅读顺序建议：`AGENTS.md` → 对应的 `SKILL.md` → 脚本文件头的 docstring
（每个脚本开头都写了「为什么要它」和踩过的坑，那是最新的一手信息）。

---

## 跑起来需要什么

| 依赖 | 说明 |
|---|---|
| macOS | 脚本用 `security`（keychain）、`pkill -f user-data-dir=`、真 Chrome 窗口 |
| Python 3.9+ | 标准库 + `playwright`；`shot_index.py` 还要 `numpy`；`wx_login_remote.py` 要 `cos-python-sdk-v5` |
| Playwright + 真 Chrome | `pip3 install playwright`（用 channel=chrome，不用自带 chromium） |
| ffmpeg / ffprobe | 抽帧、合片、探素材 |
| **每平台一个已登录 Chrome profile** | `~/NewMe/profiles/weixin`、`~/NewMe/profiles/xiaohongshu`、`~/NewMe/profiles/douyin` |
| 工作目录 | 脚本默认自身所在目录就是工作目录，产物写到同级 `_pipeline/`。`scripts/_run.sh` 里硬编码了原项目路径，换机器要改这一行 |
| 内存 | 原机器只有 8 GB —— **同时只能开一个 Chrome**，所以所有多平台脚本都是串行的，别改成并行 |

登录态不在仓库里，需要自己扫一次码/登一次录：小红书 cookie 约 1 年、抖音约 2 个月
（可用 keychain 里的密码自动登录），**视频号服务端约 26 小时就作废会话，只能扫码**
（`wx_login_remote.py` 把二维码传到对象存储、发一条签名链接，人在外面也能扫）。

---

## 三平台入口命令

发布只有**一个**入口 `newme_post.py`，它串行调三个已过 ×10 回归的专用脚本：

```bash
python3 scripts/newme_post.py 方案.json                        # 三平台都填、都不发（回归用）
python3 scripts/newme_post.py 方案.json --mode publish         # 三平台真发（定时 北京 19:30）
python3 scripts/newme_post.py 方案.json --only douyin --times 10  # 单平台连跑 10 遍
python3 scripts/newme_post.py 方案.json --video 小样.mp4        # 覆盖方案里的片子
```

单平台也可以直接跑，CLI 统一是 `方案.json --mode fill|publish [--video x.mp4] [--times N]`：

| 平台 | 脚本 | 站点 | 特点 |
|---|---|---|---|
| 微信视频号 | `publish_weixin.py` | channels.weixin.qq.com | 表单在 wujie 微前端沙箱 iframe 里，只能 `frame.evaluate` + 真鼠标/键盘；`--mode draft` 只有它支持 |
| 小红书 | `publish_xhs.py` | **creator.rednote.com**（不是 xiaohongshu.com） | 发布键要在发布栏坐标 +71px；左移 72px 是「暂存离开」= 没发 |
| 抖音 | `publish_douyin.py` | creator.douyin.com | DOM 最好自动化，但发布键**永不禁用**，点下去就发；三平台里唯一能挂真实迪拜 POI 的 |

其余脚本：

```bash
bash    scripts/_run.sh 日志名 脚本 [参数...]   # 长任务必须走它（内部 detach.py / os.setsid）
python3 scripts/stats_pull.py xiaohongshu douyin  # 数据回读 → _pipeline/stats.csv
python3 scripts/stats_pull.py --selftest          # 离线自检解析逻辑，不开浏览器
python3 scripts/topic_next.py                     # 读 stats.csv → _pipeline/选题建议.md
python3 scripts/login_keepalive.py                # 三平台只读登录体检，掉线只告警
python3 scripts/wx_login_remote.py                # 视频号出码 → 传 COS → 打印签名链接
python3 scripts/wx_heartbeat.py                   # 视频号轻量保活（LaunchAgent 每 20 分钟）
python3 scripts/wx_schedule_horizon.py            # 只读：量视频号定时最远能排到哪天（实测 32 天）
python3 scripts/shot_index.py [素材目录]          # 无口播 b-roll 选段：抽帧算清晰度/亮度/抖动
python3 scripts/newme_draft.py [草稿名]           # 生成剪映 11.x 明文草稿
python3 scripts/_xhs_clean_drafts.py --probe      # 小红书草稿箱清理（fill 模式每遍会留一条草稿）
python3 scripts/_xhs_dedup.py  /  _dy_dedup.py    # 号里重复条目清理
```

`方案.json` 的字段见 `examples/publish_plan.template.json`。**三平台文案必须分叉写**，
复制粘贴同一份会被判搬运降权。

---

## 铁规矩（详见 AGENTS.md）

1. 任何「绿」都必须有能被真实缺陷打红的回读判据，**且判据本身要有阳性对照**。
2. 定时基准是**北京时间**，跑之前必须 CDP `Emulation.setTimezoneOverride: Asia/Shanghai`（原机在迪拜 UTC+4）。
3. ⛔ 永远不 `pkill -f chrome`，只能按 `user-data-dir=` 精确杀。
4. ⛔ 永远不往活的 persistent profile 里 `add_cookies`（会顶掉登录态）。
5. 位置一律迪拜，绝不能出现阿布扎比（视频号/小红书按出口 IP 猜位置会猜错，所以那两个平台索性不填）。
6. 音频口径：原声 + 字幕 + 背景音乐，不用 TTS、不用声音克隆。
7. 改任何发布脚本后重跑 ×10 回归，10/10 全绿才算完。

## 许可与免责

内部工作资产，按现状提供。脚本会**操作真实社交账号并可能真的发布内容** ——
在没读完 `AGENTS.md` 之前不要跑 `--mode publish`。
