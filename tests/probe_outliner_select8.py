# -*- coding: utf-8 -*-
"""Select References v3 诊断探针第八轮：判定"过滤隐藏行是否丢失选中"与
"select_all 是否同步语义"——决定多目标行高亮的可行路径。

第七轮现象：四个变体一致只剩最后一个目标被选中。两种解释：
  E1: 树重建时被过滤隐藏的已选行丢失选中（rebuild drops hidden selection）；
  E2: select_all(SELECT) 把选中同步为当前可见行（deselects hidden）。
本实验直接区分：选中 A → 切过滤器到 B（不 select）→ 读 → 再 select_all → 读。

序列（同 exec 内）：
  R1: filter=MatA 泵+select_all → 读（期望 {MatA}）
  R2: filter=MatB 仅泵不 select → 读（MatA 还在？→ 区分 E1/E2）
  R3: select_all(SELECT)（filter 仍 MatB）→ 读
  R4: filter="" 泵 → 读（还原后谁存活）
"""
import bpy
import traceback

out = {"steps": {}, "conclusions": []}

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
    out["conclusions"].append("无 Outliner 区域。")
    result = out
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig = {
        "filter_text": _space.filter_text,
        "use_filter_id_type": _space.use_filter_id_type,
        "filter_id_type": _space.filter_id_type,
        "use_filter_case_sensitive": _space.use_filter_case_sensitive,
    }
    try:
        mesh = bpy.data.meshes.new("SR_DBG_Mesh")
        obj = bpy.data.objects.new("SR_DBG_Obj", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mat_a = bpy.data.materials.new("SR_DBG_MatA")
        mesh.materials.append(mat_a)
        mat_b = bpy.data.materials.new("SR_DBG_MatB")
        mesh.materials.append(mat_b)

        def _ovr():
            return bpy.context.temp_override(window=win, screen=win.screen,
                                             area=area, region=_region,
                                             space_data=_space)

        def _read():
            return sorted({"{}:{}".format(type(i).__name__, i.name)
                           for i in bpy.context.selected_ids})

        def _pump():
            area.tag_redraw()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN")

        _space.display_mode = "LIBRARIES"
        _space.use_filter_id_type = True
        _space.filter_id_type = "MATERIAL"
        _space.use_filter_case_sensitive = True
        with _ovr():
            _space.filter_text = ""
            bpy.ops.outliner.select_all(action="DESELECT")

            # R1
            _space.filter_text = "SR_DBG_MatA"
            _pump()
            bpy.ops.outliner.select_all(action="SELECT")
            out["steps"]["R1_after_select_A"] = _read()

            # R2：切过滤器到 B，不 select
            _space.filter_text = "SR_DBG_MatB"
            _pump()
            out["steps"]["R2_after_filter_B_no_select"] = _read()

            # R3：再 select_all
            bpy.ops.outliner.select_all(action="SELECT")
            out["steps"]["R3_after_select_B"] = _read()

            # R4：还原过滤器
            _space.filter_text = ""
            _pump()
            out["steps"]["R4_after_filter_clear"] = _read()

            bpy.ops.outliner.select_all(action="DESELECT")

        r2 = out["steps"]["R2_after_filter_B_no_select"]
        mat_a_kept = "Material:SR_DBG_MatA" in r2
        out["verdict"] = {
            "mat_a_survives_filter_B_without_select": mat_a_kept,
            "R3": out["steps"]["R3_after_select_B"],
            "R4": out["steps"]["R4_after_filter_clear"],
        }
        if mat_a_kept:
            out["conclusions"].append(
                "E2 成立：过滤隐藏不丢选中（R2 保留 MatA），select_all 之后"
                "选中变为 {}——多目标累加不可行的根因在 select_all/后续操作，"
                "需另寻累加路径。".format(out["steps"]["R3_after_select_B"]))
        else:
            out["conclusions"].append(
                "E1 成立：树重建时被过滤隐藏的已选行丢失选中（R2 丢了 MatA）"
                "——逐名过滤的多目标累加在原理上不可行，需单过滤器状态或"
                "放弃行高亮走 INFO 回退。")
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
    finally:
        try:
            for _k, _v in _orig.items():
                setattr(_space, _k, _v)
            with _ovr():
                bpy.ops.outliner.select_all(action="DESELECT")
        except Exception:
            pass
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
        for _d, _coll in ((mat_a, bpy.data.materials), (mat_b, bpy.data.materials),
                          (mesh, bpy.data.meshes)):
            try:
                _coll.remove(_d, do_unlink=True)
            except Exception:
                pass
    result = out

print("[probe_outliner_select8]")
for _c in out["conclusions"]:
    print("  -", _c)
