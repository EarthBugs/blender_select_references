# -*- coding: utf-8 -*-
"""Select References v3 诊断探针第七轮：泵重绘可靠性变体对比。

第六轮定位：select_datablock_rows 逐目标循环中，过滤器变更后单次
redraw_timer(DRAW_WIN) 不保证 outliner 树重建（偶发用陈旧树 select_all），
且失败模式随迭代顺序变化。本轮对比四个变体在同一目标序列
（CAMERA→MATERIAL→MATERIAL→MESH）上的可靠性：
  V_A: 单次 DRAW_WIN（现状基线）；
  V_B: 连续两次 DRAW_WIN；
  V_C: DRAW + DRAW_WIN；
  V_D: verify-retry：泵+选+读，目标未命中则重试（最多 4 次）。
记录每个变体最终命中与附带选中（extras）。
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
        # 夹具
        mesh = bpy.data.meshes.new("SR_DBG_Mesh")
        obj = bpy.data.objects.new("SR_DBG_Obj", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mat = bpy.data.materials.new("SR_DBG_Mat")
        mesh.materials.append(mat)
        mat_b = bpy.data.materials.new("SR_DBG_MatB")
        mesh.materials.append(mat_b)
        cam = bpy.data.cameras.new("SR_DBG_Cam")

        targets = [(cam, "CAMERA"), (mat, "MATERIAL"),
                   (mat_b, "MATERIAL"), (mesh, "MESH")]

        def _ovr():
            return bpy.context.temp_override(window=win, screen=win.screen,
                                             area=area, region=_region,
                                             space_data=_space)

        def _read():
            return sorted({"{}:{}".format(type(i).__name__, i.name)
                           for i in bpy.context.selected_ids})

        def _pump(kind):
            area.tag_redraw()
            bpy.ops.wm.redraw_timer(type=kind)

        def _reset():
            with _ovr():
                _space.filter_text = ""
                _space.use_filter_id_type = False
                bpy.ops.outliner.select_all(action="DESELECT")

        def _run_variant(name, pump_fn, retries):
            _reset()
            with _ovr():
                _space.use_filter_id_type = True
                _space.use_filter_case_sensitive = True
                for target, ftype in targets:
                    _space.filter_id_type = ftype
                    _space.filter_text = target.name
                    for _try in range(retries):
                        pump_fn()
                        bpy.ops.outliner.select_all(action="SELECT")
                        if retries == 1:
                            break
                        if any(i is target for i in bpy.context.selected_ids):
                            break
                got = _read()
            target_names = {"{}:{}".format(type(t).__name__, t.name)
                            for t, _ in targets}
            out["steps"][name] = {
                "got": got,
                "hit_all": target_names.issubset(set(got)),
                "extras": sorted(set(got) - target_names),
            }

        _run_variant("V_A_single_draw_win", lambda: _pump("DRAW_WIN"), 1)
        _run_variant("V_B_double_draw_win",
                     lambda: (_pump("DRAW_WIN"), _pump("DRAW_WIN")), 1)
        _run_variant("V_C_draw_then_draw_win",
                     lambda: (_pump("DRAW"), _pump("DRAW_WIN")), 1)
        _run_variant("V_D_verify_retry", lambda: _pump("DRAW_WIN"), 4)

        out["verdict"] = {k: {"hit_all": v["hit_all"], "extras": v["extras"]}
                          for k, v in out["steps"].items()}
        good = [k for k, v in out["verdict"].items()
                if v["hit_all"] and not v["extras"]]
        out["conclusions"].append(
            "可靠变体（全命中且无附带选中）：{}".format(good if good else "无"))
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
        for _d, _coll in ((mat, bpy.data.materials), (mat_b, bpy.data.materials),
                          (cam, bpy.data.cameras), (mesh, bpy.data.meshes)):
            try:
                _coll.remove(_d, do_unlink=True)
            except Exception:
                pass
    result = out

print("[probe_outliner_select7]")
for _c in out["conclusions"]:
    print("  -", _c)
