# -*- coding: utf-8 -*-
"""Select References v3 探针第九轮：单次过滤多目标。

已证实（probe8/E1）：逐名过滤多目标不可行——切换 filter_text/filter_id_type
会触发大纲树重建，被过滤隐藏的已选行丢失选中，最终只保留最后一个目标。

本轮验证替代路径：单次过滤同时命中全部目标，一次 select_all 完成多选——
  V1: filter_text 子串基线（公共前缀），确认多行同时可见可全选；
  V2: filter_text 正则交替 "A|B" 是否被支持；
  V3: filter_text 正则 "^(A|B)$" 整名锚定；
  V4: 不设 filter_id_type 时跨类型（Material+Camera）正则单次过滤；
  V5: 不设 filter_id_type 时跨类型公共前缀子串过滤。

自建夹具（SR_PROBE_ 前缀），结束清理并还原空间设置。
"""
import bpy
import traceback

out = {"steps": {}, "conclusions": []}

# ---- 夹具 ----
mat_a = bpy.data.materials.get("SR_PROBE_MatA") or bpy.data.materials.new("SR_PROBE_MatA")
mat_b = bpy.data.materials.get("SR_PROBE_MatB") or bpy.data.materials.new("SR_PROBE_MatB")
cam = bpy.data.cameras.get("SR_PROBE_CamData") or bpy.data.cameras.new("SR_PROBE_CamData")

win = None
area = None
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        if a.type == "OUTLINER":
            win, area = w, a
            break
    if area is not None:
        break

if area is None:
    out["conclusions"].append("无 Outliner 区域，第九轮探针无法执行。")
    result = out
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig = {
        "display_mode": _space.display_mode,
        "filter_text": _space.filter_text,
        "use_filter_id_type": _space.use_filter_id_type,
        "filter_id_type": _space.filter_id_type,
        "use_filter_case_sensitive": _space.use_filter_case_sensitive,
    }
    try:
        _space.display_mode = "LIBRARIES"

        def _ovr():
            return bpy.context.temp_override(window=win, screen=win.screen,
                                             area=area, region=_region,
                                             space_data=_space)

        def _read_sel():
            return sorted("{}:{}".format(type(i).__name__, i.name)
                          for i in bpy.context.selected_ids)

        def _pump():
            area.tag_redraw()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN")

        def _run_variant(tag, id_type, ftext):
            """设过滤 → 泵 → 全选 → 读选中 → 清空。返回选中行列表。"""
            with _ovr():
                bpy.ops.outliner.select_all(action="DESELECT")
            if id_type is None:
                _space.use_filter_id_type = False
            else:
                _space.use_filter_id_type = True
                _space.filter_id_type = id_type
            _space.use_filter_case_sensitive = True
            _space.filter_text = ftext
            with _ovr():
                _pump()
                bpy.ops.outliner.select_all(action="SELECT")
                got = _read_sel()
            _space.filter_text = ""
            with _ovr():
                _pump()
                bpy.ops.outliner.select_all(action="DESELECT")
            out["steps"][tag] = got
            return got

        _run_variant("v1_prefix_material", "MATERIAL", "SR_PROBE_Mat")
        _run_variant("v2_regex_alt", "MATERIAL", "SR_PROBE_MatA|SR_PROBE_MatB")
        _run_variant("v3_regex_anchor", "MATERIAL", "^(SR_PROBE_MatA|SR_PROBE_MatB)$")
        _run_variant("v4_regex_crosstype", None,
                     "^(SR_PROBE_MatA|SR_PROBE_CamData)$")
        _run_variant("v5_prefix_crosstype", None, "SR_PROBE_")

        v1 = out["steps"]["v1_prefix_material"]
        v2 = out["steps"]["v2_regex_alt"]
        v3 = out["steps"]["v3_regex_anchor"]
        v4 = out["steps"]["v4_regex_crosstype"]
        v5 = out["steps"]["v5_prefix_crosstype"]

        two_mats = {"Material:SR_PROBE_MatA", "Material:SR_PROBE_MatB"}
        out["verdict"] = {
            "v1_prefix_two_mats": two_mats.issubset(set(v1)),
            "v2_regex_alt_two_mats": two_mats.issubset(set(v2)),
            "v3_regex_anchor_two_mats": two_mats.issubset(set(v3)),
            "v4_crosstype_both": (
                "Material:SR_PROBE_MatA" in v4
                and "Camera:SR_PROBE_CamData" in v4),
            "v5_crosstype_all_three": (
                two_mats.issubset(set(v5))
                and "Camera:SR_PROBE_CamData" in v5),
        }
        vd = out["verdict"]
        if vd["v3_regex_anchor_two_mats"] or vd["v2_regex_alt_two_mats"]:
            out["conclusions"].append(
                "filter_text 支持正则：单次过滤可同时命中多目标，一次 select_all "
                "完成多选——多目标行高亮可行（v2={}, v3={}）。".format(v2, v3))
        elif vd["v1_prefix_two_mats"]:
            out["conclusions"].append(
                "filter_text 仅子串匹配：正则不被支持（v2={}）；公共前缀可同选 "
                "（v1={}），但对任意名字集合不通用。".format(v2, v1))
        else:
            out["conclusions"].append(
                "单次过滤多目标亦不可行：v1={} v2={} v3={}。".format(v1, v2, v3))
        out["conclusions"].append(
            "跨类型（不设 filter_id_type）：正则 v4={}；前缀 v5={}。".format(v4, v5))
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
        out["conclusions"].append("第九轮探针异常：{}".format(repr(exc)))
    finally:
        try:
            for _k, _v in _orig.items():
                setattr(_space, _k, _v)
            with bpy.context.temp_override(window=win, screen=win.screen,
                                           area=area, region=_region,
                                           space_data=_space):
                bpy.ops.outliner.select_all(action="DESELECT")
        except Exception:
            pass
        for _d in (mat_a, mat_b, cam):
            try:
                if _d.users == 0:
                    (bpy.data.materials if hasattr(_d, "diffuse_color")
                     else bpy.data.cameras).remove(_d)
            except Exception:
                pass
    result = out

print("[probe_outliner_select9]")
for _c in out["conclusions"]:
    print("  -", _c)
