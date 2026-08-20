#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
镜头库索引 —— 让下一条片子不用再手工翻素材

为什么要它：实拍素材全是无口播 b-roll（见记忆 material-reality），所以流水线的入口
是脚本而不是转写。但脚本写完要配画面，靠人一条条翻 675 秒素材太慢。这个脚本给每条
素材算出"哪几秒能用"，写成 `_pipeline/shot_index.json`，下次写分镜直接查表。

每 0.5 秒取一帧（缩到 192px 灰度），逐帧算三个指标：
  sharp  = 相邻像素差的方差，糊/失焦/运动模糊会掉下去
  bright = 平均亮度，过暗过曝都不能用
  motion = 与上一帧的平均绝对差，用来判抖动和镜头切换
然后滑窗找连续可用段（默认 ≥1.5 秒），按 sharp 中位数排序。

⚠️ 只索引自拍素材（IMG_*.MOV）。Downloads 里还有 invideo-ai / RPReplay / ScreenRecording
   那些是下载的竞品和演示片，不是自家素材，不要混进来当画面用。
⚠️ 有一批 IMG_*.MOV 是 moov atom not found（iCloud 没下全的占位文件），会被记成 broken，
   要让用户在 Mac 上把它们下全再重跑。

⚠️ 沙箱里 nohup 的后台进程会在这次 bash 调用返回后被回收，日志还没 flush 就没了
   （2026-08-19 踩过：日志全空、进程消失）。所以要么在同一次调用里跑完，要么像这样
   分批：`--offset 0 --limit 8` 跑几次，索引会自动合并已有结果。

用法: shot_index.py [素材目录] [--offset 0] [--limit 999]
"""
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(ROOT, "_pipeline")
SRC = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
    else "/sessions/tender-eager-wright/mnt/Downloads"

STEP = 0.5      # 采样间隔（秒）
WIDTH = 192     # 采样宽度，够算清晰度又不吃 CPU
MIN_WIN = 1.5   # 最短可用段
# 阈值不是拍脑袋定的：拿 v3 成片实际用上的 10 段当标准答案反推（2026-08-19）。
# 那 10 段的实测范围是 sharp 156~816、bright 146~182、motion 中位 17~41 峰值 43。
# 一开始我定 sharp≥18 / motion≤26，结果把 IMG_4461（成片主力，77 秒）判成只有 5 秒可用 ——
# 移镜 b-roll 的 motion 本来就有 30~40，卡 26 等于把好素材全毙掉。
SHARP_MIN = 120.0
BRIGHT = (80, 235)
MOTION_MAX = 55.0   # 再高基本是切镜或甩镜（切镜的帧间差常在 80 以上）


def probe(path):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:"
             "format=duration", "-of", "json", path],
            stderr=subprocess.STDOUT).decode()
    except subprocess.CalledProcessError as e:
        return None, e.output.decode("utf-8", "replace").strip().splitlines()[-1]
    d = json.loads(out)
    s = (d.get("streams") or [{}])[0]
    num, den = (s.get("r_frame_rate") or "30/1").split("/")
    return {"w": s.get("width"), "h": s.get("height"),
            "fps": round(float(num) / float(den or 1), 2),
            "dur": round(float(d["format"]["duration"]), 2)}, None


def frames(path, h):
    """按 STEP 抽帧，灰度 rawvideo 直接管进 numpy —— 不落盘，省 IO。

    ⚠️ 尺寸必须写死成正方形。原来用 scale=192:-2 再按数据量反推高度，遇到
    192 的公因数就会猜错帧数（IMG_4462 时长 13.8s 竟算出 21.5s 可用）。
    比例失真不影响清晰度/亮度/运动这三个相对指标。"""
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path,
         "-vf", "fps=%g,scale=%d:%d,format=gray" % (1.0 / STEP, WIDTH, WIDTH),
         "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    buf = p.communicate()[0]
    n = len(buf) // (WIDTH * WIDTH)
    if n < 2:
        return None
    return np.frombuffer(buf[:n * WIDTH * WIDTH], np.uint8).reshape(
        n, WIDTH, WIDTH)


def metrics(a):
    a = a.astype(np.float32)
    sharp = np.array([np.var(np.diff(f, axis=0)) + np.var(np.diff(f, axis=1))
                      for f in a])
    bright = a.mean(axis=(1, 2))
    motion = np.concatenate([[0.0], np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))])
    return sharp, bright, motion


def windows(sharp, bright, motion):
    ok = ((sharp >= SHARP_MIN) & (bright > BRIGHT[0]) & (bright < BRIGHT[1])
          & (motion <= MOTION_MAX))
    out, i = [], 0
    while i < len(ok):
        if not ok[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(ok) and ok[j + 1]:
            j += 1
        if (j - i + 1) * STEP >= MIN_WIN:
            out.append({"in": round(i * STEP, 2),
                        "dur": round((j - i + 1) * STEP, 2),
                        "sharp": round(float(np.median(sharp[i:j + 1])), 1),
                        "bright": round(float(np.median(bright[i:j + 1])), 1),
                        "motion": round(float(np.median(motion[i:j + 1])), 1)})
        i = j + 1
    return sorted(out, key=lambda w: -w["dur"])


def main():
    def opt(k, d):
        return int(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d

    out = os.path.join(PIPE, "shot_index.json")
    prev = {"clips": {}, "broken": []}
    if os.path.exists(out):
        try:
            prev = json.load(open(out, encoding="utf-8"))
        except Exception:
            pass
    names = sorted(f for f in os.listdir(SRC)
                   if f.upper().startswith("IMG_") and
                   f.upper().endswith((".MOV", ".MP4")))
    done = set(prev["clips"]) | set(x["file"] for x in prev.get("broken", []))
    if "--redo" not in sys.argv:
        names = [n for n in names if n not in done]
    names = names[opt("--offset", 0):][:opt("--limit", 999)]
    print(u"本批 %d 条（库里共 %d 条已入库）" % (len(names), len(done)))
    idx, broken = {}, []
    for n in names:
        p = os.path.join(SRC, n)
        info, err = probe(p)
        if not info:
            broken.append({"file": n, "why": err})
            print(u"✗ %-22s %s" % (n, err))
            continue
        a = frames(p, info["h"] or 1920)
        if a is None:
            broken.append({"file": n, "why": "decode failed"})
            print(u"✗ %-22s 解不出帧" % n)
            continue
        s, b, m = metrics(a)
        w = windows(s, b, m)
        idx[n] = dict(info, windows=w,
                      usable=round(sum(x["dur"] for x in w), 1),
                      label="")     # 内容标签留空，看联系表后人工/我来填
        print(u"  %-22s %5.1fs 可用%5.1fs %d段 最长%.1fs"
              % (n, info["dur"], idx[n]["usable"], len(w),
                 w[0]["dur"] if w else 0))
    old = prev.get("clips", {})
    for k, v in idx.items():     # 保住已经填好的 label，别每次重跑都丢
        if old.get(k, {}).get("label"):
            v["label"] = old[k]["label"]
    clips = dict(old, **idx)
    brk = {x["file"]: x for x in prev.get("broken", [])}
    brk.update({x["file"]: x for x in broken})
    json.dump({"src": SRC, "step": STEP, "min_window": MIN_WIN,
               "thresholds": {"sharp": SHARP_MIN, "bright": BRIGHT,
                              "motion": MOTION_MAX},
               "clips": clips, "broken": sorted(brk.values(),
                                                key=lambda x: x["file"])},
              open(out, "w"), ensure_ascii=False, indent=1)
    print(u"\n累计 %d 条可用 / %d 条坏档，总可用素材 %.0f 秒 → %s"
          % (len(clips), len(brk), sum(v["usable"] for v in clips.values()), out))
    broken = list(brk.values())
    if broken:
        print(u"坏档（多半是 iCloud 没下全，让用户在 Mac 上下全再重跑）：%s"
              % ", ".join(x["file"] for x in broken))
    return 0


if __name__ == "__main__":
    sys.exit(main())
