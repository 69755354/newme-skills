#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NewMe → 剪映草稿生成器（新版格式，剪映 11.x / version 360000）

为什么要这个：成片必须在剪映里做（用户买了 SVIP，特效/花字/曲库都在里面），
ffmpeg 只做前置的切片与合成音乐。所以这里把分镜表直接写成一份剪映能打开的草稿：
10 段视频 + 13 条字幕 + 1 条背景音乐，时间线已经对好，打开就能改。

格式来源：NEWME_VECTCUT_V10_DIAGNOSTIC/（Codex 那边验证新版兼容留下的样本）。
新版草稿的关键结构和老版不一样，别照老教程写：
  <草稿目录>/
    draft_content.json          ← 根上也要放一份（老入口兼容）
    draft_meta_info.json        ← 剪映首页靠它列出草稿：名字、封面、时长、素材清单
    timeline_layout.json        ← 指向 Timelines/<时间线ID>
    Timelines/<时间线ID>/draft_content.json (+ .bak + template.tmp + template-2.tmp)
    assets/video|audio/...      ← 素材复制进来，别引用 ~/Downloads
时长单位是**微秒**，不是秒也不是毫秒。

素材为什么复制进草稿目录：Mac 的 TCC 会拦剪映读 ~/Downloads，一旦弹窗没点就是
"素材丢失"。放进草稿自己的 assets/ 下最稳。

用法: newme_draft.py [草稿名]
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

# 沙箱里的路径（Linux 侧）
CUTS = "/sessions/tender-eager-wright/mnt/Downloads/NewMe_cuts"
ROOT = "/sessions/tender-eager-wright/mnt/com.lveditor.draft"
# 同一个目录在 Mac 上的真实路径 —— 写进 json 的必须是这个，剪映按它找素材
MAC_ROOT = "/Users/yalantan/Movies/JianyingPro/User Data/Projects/com.lveditor.draft"

W, H, FPS = 1080, 1920, 30
APP = {"app_id": 3704, "app_source": "lv", "app_version": "11.2.13043", "os": "mac"}


def uid():
    return uuid.uuid4().hex


def UID():
    return str(uuid.uuid4()).upper()


def us(sec):
    """秒 → 微秒（剪映的时间单位）"""
    return int(round(sec * 1000000))


def probe(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=width,height", "-of", "json", path])
    d = json.loads(out)
    st = [s for s in d["streams"] if "width" in s]
    return (float(d["format"]["duration"]),
            st[0]["width"] if st else 0, st[0]["height"] if st else 0)


def video_material(path, dur, w, h):
    return {
        "audio_fade": None, "category_id": "", "category_name": "local",
        "check_flag": 63487,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0,
                 "upper_right_x": 1.0, "upper_right_y": 0.0,
                 "lower_left_x": 0.0, "lower_left_y": 1.0,
                 "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free", "crop_scale": 1.0,
        "duration": dur, "height": h, "width": w,
        "id": uid(), "local_material_id": "",
        "material_name": os.path.basename(path),
        "media_path": "", "path": path, "remote_url": "", "type": "video",
    }


def audio_material(path, dur):
    return {
        "id": uid(), "type": "extract_music", "name": os.path.basename(path),
        "path": path, "duration": dur,
        "category_id": "", "category_name": "local", "check_flag": 1,
        "effect_id": "", "formula_id": "", "intensifies_path": "",
        "is_ai_clone_tone": False, "is_text_edit_overdub": False,
        "is_ugc": False, "local_material_id": "", "music_id": uid(),
        "query": "", "request_id": "", "resource_id": "", "search_id": "",
        "source_platform": 0, "team_id": "", "text_id": "",
        "tone_category_id": "", "tone_category_name": "", "tone_effect_id": "",
        "tone_effect_name": "", "tone_platform": "", "tone_speaker": "",
        "tone_type": "", "wave_points": [],
    }


def text_material(text, size=9.0):
    """字幕样式。size 是剪映自己的字号刻度（不是像素），9 在 1080x1920 上
    大致等于成片里 64px 那一档；stroke width 0.05 是描边，深色画面上才看得清。"""
    content = {
        "text": text,
        "styles": [{
            "fill": {"alpha": 1.0, "content": {
                "render_type": "solid",
                "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}}},
            "range": [0, len(text)],
            "size": size, "bold": True, "italic": False, "underline": False,
            "strokes": [{"content": {"solid": {
                "alpha": 1.0, "color": [0.0, 0.0, 0.0]}}, "width": 0.05}],
        }],
    }
    return {
        "id": uid(), "type": "text",
        "content": json.dumps(content, ensure_ascii=False),
        "typesetting": 0, "alignment": 1, "letter_spacing": 0.0,
        "line_spacing": 0.02, "line_feed": 1, "line_max_width": 0.82,
        "force_apply_line_max_width": False, "check_flag": 15,
        "fixed_width": -1, "fixed_height": -1,
        "font_category_id": "", "font_category_name": "", "font_id": "",
        "font_name": "", "font_path": "", "font_resource_id": "",
        "font_size": 15.0, "font_source_platform": 0, "font_team_id": "",
        "font_title": "none", "font_url": "", "fonts": [],
        "shadows": [], "background_alpha": 1.0,
    }


def speed_material():
    return {"curve_speed": None, "id": uid(), "mode": 0, "speed": 1.0,
            "type": "speed"}


def scm_material():
    return {"id": uid(), "audio_channel_mapping": 0, "is_config_open": False,
            "type": "none"}


def beat_material():
    return {"id": uid(), "type": "beats", "gear": 404, "gear_count": 0,
            "mode": 404, "enable_ai_beats": False, "user_beats": [],
            "user_delete_ai_beats": None,
            "ai_beats": {"beat_speed_infos": [], "beats_path": "",
                         "beats_url": "", "user_beats": []}}


def seg(material_id, start, dur, refs, src_start=0, src_dur=None,
        volume=1.0, render_index=0, scale=1.0, ty=0.0, has_src=True):
    s = {
        "id": uid(), "material_id": material_id,
        "target_timerange": {"start": start, "duration": dur},
        "source_timerange": ({"start": src_start,
                              "duration": src_dur if src_dur else dur}
                             if has_src else None),
        "extra_material_refs": refs,
        "speed": 1.0, "volume": volume, "visible": True, "reverse": False,
        "enable_adjust": True, "enable_color_correct_adjust": False,
        "enable_color_curves": True, "enable_color_match_adjust": False,
        "enable_color_wheels": True, "enable_lut": True,
        "enable_smart_color_adjust": False, "last_nonzero_volume": 1.0,
        "track_attribute": 0, "track_render_index": 0,
        "common_keyframes": [], "keyframe_refs": [],
        "clip": {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
                 "rotation": 0.0, "scale": {"x": scale, "y": scale},
                 "transform": {"x": 0.0, "y": ty}},
        "uniform_scale": {"on": True, "value": 1.0},
        "render_index": render_index,
    }
    if has_src:
        # 只有视频段有 hdr_settings；文本段带上反而是脏字段
        s["hdr_settings"] = {"intensity": 1.0, "mode": 1, "nits": 1000}
    return s


def build():
    name = sys.argv[1] if len(sys.argv) > 1 else u"NewMe_一面墙管全屋"
    sb = json.load(open(os.path.join(CUTS, "storyboard.json"), encoding="utf-8"))

    d_dir = os.path.join(ROOT, name)
    mac_dir = os.path.join(MAC_ROOT, name)
    for sub in ["assets/video", "assets/audio", "Resources", "adjust_mask",
                "common_attachment", "matting", "qr_upload", "smart_crop",
                "subdraft"]:
        os.makedirs(os.path.join(d_dir, sub), exist_ok=True)

    mats = {k: [] for k in [
        "ai_translates", "audio_balances", "audio_effects", "audio_fades",
        "audio_track_indexes", "audios", "beats", "canvases", "chromas",
        "color_curves", "digital_humans", "drafts", "effects", "flowers",
        "green_screens", "handwrites", "hsl", "images", "log_color_wheels",
        "loudnesses", "manual_deformations", "material_animations",
        "material_colors", "masks", "multi_language_refs", "placeholders",
        "plugin_effects", "primary_color_wheels", "realtime_denoises",
        "shapes", "smart_crops", "smart_relights", "sound_channel_mappings",
        "speeds", "stickers", "tail_leaders", "text_templates", "texts",
        "time_marks", "transitions", "video_effects", "video_trackings",
        "videos", "vocal_beautifys", "vocal_separations"]}

    vsegs, tsegs, asegs = [], [], []
    t0 = 0
    for sh in sb["shots"]:
        srcname = "%s_%s.mp4" % (sh["tag"], sh["source"][4:8])
        src = os.path.join(CUTS, srcname)
        if not os.path.exists(src):
            raise SystemExit(u"缺片段: %s" % src)
        dst = os.path.join(d_dir, "assets/video", srcname)
        shutil.copyfile(src, dst)
        dur, w, h = probe(dst)
        vm = video_material(os.path.join(mac_dir, "assets/video", srcname),
                            us(dur), w, h)
        mats["videos"].append(vm)
        sp = speed_material()
        mats["speeds"].append(sp)
        vsegs.append(seg(vm["id"], t0, us(dur), [sp["id"]]))

        for s in sh["subs"]:
            tm = text_material(s["text"])
            mats["texts"].append(tm)
            # y=-0.72：竖版里字幕压在底部安全区上方，避开各平台的底部按钮遮挡
            tsegs.append(seg(tm["id"], t0 + us(s["at"]), us(s["dur"]), [],
                             ty=-0.72, render_index=15000, has_src=False))
        t0 += us(dur)

    total = t0

    # 背景音乐：合成的那条，音量 0.7（全片没有人声，不用压太低）
    bgm = os.path.join(CUTS, "bgm.wav")
    if os.path.exists(bgm):
        shutil.copyfile(bgm, os.path.join(d_dir, "assets/audio", "bgm.wav"))
        adur, _, _ = probe(bgm)
        am = audio_material(os.path.join(mac_dir, "assets/audio", "bgm.wav"),
                            us(adur))
        mats["audios"].append(am)
        sp, scm, bt = speed_material(), scm_material(), beat_material()
        mats["speeds"].append(sp)
        mats["sound_channel_mappings"].append(scm)
        mats["beats"].append(bt)
        asegs.append(seg(am["id"], 0, min(us(adur), total),
                         [sp["id"], scm["id"], bt["id"]], volume=0.7))

    tid = UID()
    tracks = [
        {"attribute": 0, "flag": 0, "id": uid(), "is_default_name": False,
         "name": "video_main", "segments": vsegs, "type": "video"},
        {"attribute": 0, "flag": 0, "id": uid(), "is_default_name": False,
         "name": "audio_main", "segments": asegs, "type": "audio"},
        {"attribute": 0, "flag": 0, "id": uid(), "is_default_name": False,
         "name": "text_main", "segments": tsegs, "type": "text"},
    ]

    content = {
        "canvas_config": {"width": W, "height": H, "ratio": "original"},
        "color_space": 0,
        "config": {
            "adjust_max_index": 1, "attachment_info": [],
            "combination_max_index": 1, "export_range": None,
            "extract_audio_last_index": 1, "lyrics_recognition_id": "",
            "lyrics_sync": True, "lyrics_taskinfo": [],
            "maintrack_adsorb": True, "material_save_mode": 0,
            "multi_language_current": "none", "multi_language_list": [],
            "multi_language_main": "none", "multi_language_mode": "none",
            "original_sound_last_index": 1, "record_audio_last_index": 1,
            "sticker_max_index": 1, "subtitle_keywords_config": None,
            "subtitle_recognition_id": "", "subtitle_sync": True,
            "subtitle_taskinfo": [], "system_font_list": [],
            "video_mute": False, "zoom_info_params": None},
        "cover": None, "create_time": 0, "duration": total,
        "extra_info": None, "fps": FPS, "free_render_index_mode_on": False,
        "group_container": None, "id": tid, "keyframe_graph_list": [],
        "keyframes": {k: [] for k in ["adjusts", "audios", "effects",
                                      "filters", "handwrites", "stickers",
                                      "texts", "videos"]},
        "last_modified_platform": APP, "platform": APP,
        "materials": mats, "mutable_config": None, "name": "",
        "new_version": "110.0.0", "relationships": [],
        "render_index_track_mode_on": True, "retouch_cover": None,
        "source": "default", "static_cover_image_path": "",
        "time_marks": None, "tracks": tracks, "update_time": 0,
        "version": 360000,
    }

    body = json.dumps(content, ensure_ascii=False, indent=4)
    tl_dir = os.path.join(d_dir, "Timelines", tid)
    os.makedirs(os.path.join(tl_dir, "common_attachment"), exist_ok=True)
    for p in [os.path.join(d_dir, "draft_content.json"),
              os.path.join(tl_dir, "draft_content.json"),
              os.path.join(tl_dir, "draft_content.json.bak"),
              os.path.join(tl_dir, "template.tmp"),
              os.path.join(tl_dir, "template-2.tmp"),
              os.path.join(d_dir, "template.tmp")]:
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)

    # ⚠️ 这两个文件是"草稿能不能打开"的关键，2026-08-18 花了两小时才定位到：
    # 少了 Timelines/project.json，剪映首页能列出草稿、双击后界面会闪一下，
    # 然后**静默退回首页**，不报任何错 —— 因为它找不到时间线注册表。
    # timeline_layout.json 也必须带 activeTimeline，否则不知道该激活哪条。
    now_us = int(time.time() * 1000000)
    proj = {"config": {"color_space": -1, "mixed_track_mode_on": False,
                       "render_index_track_mode_on": False,
                       "use_float_render": False},
            "create_time": now_us, "id": tid, "main_timeline_id": tid,
            "timelines": [{"create_time": now_us, "id": tid,
                           "is_marked_delete": False, "name": u"时间线01",
                           "update_time": now_us}],
            "update_time": now_us, "version": 0}
    pbody = json.dumps(proj, ensure_ascii=False)
    for p in ["Timelines/project.json", "Timelines/project.json.bak"]:
        with open(os.path.join(d_dir, p), "w", encoding="utf-8") as f:
            f.write(pbody)

    with open(os.path.join(d_dir, "timeline_layout.json"), "w") as f:
        json.dump({"activeTimeline": tid,
                   "dockItems": [{"dockIndex": 0, "ratio": 1,
                                  "timelineIds": [tid],
                                  "timelineNames": [u"时间线01"]}],
                   "layoutOrientation": 1}, f, ensure_ascii=False)
    for p, v in [("draft_virtual_store.json",
                  {"key_values": [], "material_infos": []}),
                 ("key_value.json", {}),
                 ("draft_biz_config.json", {}),
                 ("attachment_pc_common.json", {}),
                 ("draft_settings", {})]:
        with open(os.path.join(d_dir, p), "w") as f:
            json.dump(v, f, ensure_ascii=False)
    with open(os.path.join(tl_dir, "attachment_editing.json"), "w") as f:
        json.dump({}, f)
    with open(os.path.join(tl_dir, "attachment_pc_common.json"), "w") as f:
        json.dump({}, f)

    # 首页要能看到这条草稿，靠的是 draft_meta_info：名字、时长、素材清单
    now = int(time.time() * 1000000)
    vals = []
    for m in mats["videos"] + mats["audios"]:
        vals.append({
            "create_time": int(now / 1000000), "duration": m["duration"],
            "extra_info": os.path.basename(m["path"]), "file_Path": m["path"],
            "height": m.get("height", 0), "width": m.get("width", 0),
            "id": uid(), "import_time": int(now / 1000000),
            "import_time_ms": now, "item_source": 1,
            "md5": "", "metetype": "video" if m["type"] == "video" else "music",
            "roughcut_time_range": {"duration": m["duration"], "start": 0},
            "sub_time_range": {"duration": -1, "start": -1}, "type": 0})
    meta = {
        "cloud_package_completed_time": "", "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False, "draft_cloud_materials": [],
        "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "", "draft_deeplink_url": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "",
                                  "draft_enterprise_id": "",
                                  "draft_enterprise_name": "",
                                  "enterprise_material": []},
        "draft_fold_path": mac_dir, "draft_id": tid,
        "draft_is_ai_shorts": False, "draft_is_article_video_draft": False,
        "draft_is_from_deeplink": "false", "draft_is_invisible": False,
        "draft_materials": [{"type": 0, "value": vals},
                            {"type": 1, "value": []}, {"type": 2, "value": []},
                            {"type": 3, "value": []}, {"type": 6, "value": []},
                            {"type": 7, "value": []}, {"type": 8, "value": []}],
        "draft_materials_copied_info": [], "draft_name": name,
        "draft_new_version": "", "draft_removable_storage_device": "",
        "draft_root_path": MAC_ROOT.replace("/", "\\") if False else MAC_ROOT,
        "draft_segment_extra_info": [], "draft_timeline_materials_size_": 0,
        "draft_type": "", "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0, "tm_draft_create": now,
        "tm_draft_modified": now, "tm_draft_removed": 0, "tm_duration": total,
    }
    with open(os.path.join(d_dir, "draft_meta_info.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=4)

    print(u"草稿: %s" % mac_dir)
    print(u"  时间线 %s" % tid)
    print(u"  视频 %d 段 / 字幕 %d 条 / 音乐 %d 条 / 总长 %.1f 秒"
          % (len(vsegs), len(tsegs), len(asegs), total / 1000000.0))
    return 0


if __name__ == "__main__":
    sys.exit(build())
