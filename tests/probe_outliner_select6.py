# -*- coding: utf-8 -*-
"""Select References v3 诊断探针第六轮：MATERIAL 行高亮在端到端失败定位。

v4 测试现象：select_datablock_rows({mat_a, mat_b, cam_data}) 只命中 cam_data
（CAMERA 成功、两个 MATERIAL 失败）；而 MESH 目标（mesh_shared/mesh_mat）与
探针第五轮的 MATERIAL m2（OBJECT 槽用户）均成功。待区分：
  H1: DATA 槽材质（users 仅来自 mesh.materials）在 LIBRARIES 树中不可见；
  H2: 可见但逐名过滤失败（过滤器/时序问题）；
  H3: select_datablock_rows 循环内状态污染（前一目标的过滤设置残留）。

步骤：新建 DATA 槽材质夹具 → 空过滤全选 MATERIAL 分节（可见性）→
逐名过滤单选（精确性）→ 直接调插件 select_datablock_rows（复现）→ 清理。
"""
import bpy
import sys
import traceback

PLUGIN_DIR = r"C:\Users\EarthBugs\Documents\current_working\20260901_blender_select_references"
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)
_old = sys.modules.pop("select_references", None)
if _old is not None:
    try:
        _old.unregister()
    except Exception:
        pass
import select_references as sr

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
    _fx = []
    try:
        # 夹具：DATA 槽材质 + 相机数据块
        mesh = bpy.data.meshes.new("SR_DBG_Mesh")
        obj = bpy.data.objects.new("SR_DBG_Obj", mesh)
        bpy.context.scene.collection.objects.link(obj)
        mat = bpy.data.materials.new("SR_DBG_Mat")
        mesh.materials.append(mat)
        cam = bpy.data.cameras.new("SR_DBG_Cam")
        _fx = [obj, mesh, mat, cam]
        out["steps"]["mat_users"] = mat.users

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
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")

        # S1 可见性：MATERIAL 分节空过滤全选
        _space.use_filter_id_type = True
        _space.filter_id_type = "MATERIAL"
        _space.use_filter_case_sensitive = True
        _space.filter_text = ""
        with _ovr():
            _pump()
            bpy.ops.outliner.select_all(action="SELECT")
            s1 = _read()
        out["steps"]["s1_all_material_rows"] = s1
        out["steps"]["s1_mat_visible"] = "Material:SR_DBG_Mat" in s1

        # S2 逐名过滤单选
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        _space.filter_text = "SR_DBG_Mat"
        with _ovr():
            _pump()
            bpy.ops.outliner.select_all(action="SELECT")
            out["steps"]["s2_named_select"] = _read()

        # S3 直接调插件函数复现
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        rows_ok, rows_failed, extras = sr.select_datablock_rows(
            bpy.context, {mat, cam})
        out["steps"]["s3_plugin_rows_ok"] = [i.name for i in rows_ok]
        out["steps"]["s3_plugin_rows_failed"] = [i.name for i in rows_failed]
        out["steps"]["s3_plugin_extras"] = ["{}:{}".format(type(i).__name__, i.name)
                                            for i in extras]

        out["verdict"] = {
            "data_slot_mat_visible_in_tree": out["steps"]["s1_mat_visible"],
            "named_select_ok": out["steps"]["s2_named_select"] == ["Material:SR_DBG_Mat"],
            "plugin_ok": sorted(out["steps"]["s3_plugin_rows_ok"]) == ["SR_DBG_Cam", "SR_DBG_Mat"],
        }
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
        for _d, _coll in ((mat, bpy.data.materials), (cam, bpy.data.cameras),
                          (mesh, bpy.data.meshes)):
            try:
                _coll.remove(_d, do_unlink=True)
            except Exception:
                pass
    result = out

print("[probe_outliner_select6]")
import json as _json
print(_json.dumps(out.get("verdict", {}), ensure_ascii=False))
