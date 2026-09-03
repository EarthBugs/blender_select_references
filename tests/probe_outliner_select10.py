# -*- coding: utf-8 -*-
"""诊断：同一会话内 select_datablock_rows 对 Material/Mesh/Image 数据块的
行选中为何 Mesh 成功而 Material/Image 失败（v4 测试 7.1/7.3/7.4 输入选中失败）。

逐类型记录：函数返回、selected_ids 实际值、空间过滤器前后状态、
select_all 后可见行计数线索。结束清理夹具并还原空间设置。
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

mat = bpy.data.materials.get("SR_D10_Mat") or bpy.data.materials.new("SR_D10_Mat")
me = bpy.data.meshes.get("SR_D10_Mesh") or bpy.data.meshes.new("SR_D10_Mesh")
img = bpy.data.images.get("SR_D10_Img") or bpy.data.images.new("SR_D10_Img", 4, 4)

try:
    for tag, idb, ftype in (("mesh", me, "MESH"), ("material", mat, "MATERIAL"),
                            ("image", img, "IMAGE")):
        step = {}
        try:
            rows_ok, rows_failed, extras = sr.select_datablock_rows(
                bpy.context, {idb})
            step["rows_ok"] = [i.name for i in rows_ok]
            step["rows_failed"] = [i.name for i in rows_failed]
            step["extras"] = [i.name for i in extras]
        except Exception as exc:
            step["error"] = repr(exc)
        # 手动读一次真实 selected_ids（不注入的 override）
        try:
            found = sr._find_outliner_context(bpy.context)
            w, a, region, space = found
            with bpy.context.temp_override(window=w, screen=w.screen, area=a,
                                           region=region, space_data=space):
                step["sel_after"] = sorted(i.name for i in bpy.context.selected_ids)
            step["space_state"] = {
                "display_mode": space.display_mode,
                "filter_text": space.filter_text,
                "use_filter_id_type": space.use_filter_id_type,
                "filter_id_type": space.filter_id_type,
            }
        except Exception as exc:
            step["read_error"] = repr(exc)
        out["steps"][tag] = step

    # 附带实验：filter_id_type 合法值里 IMAGE 是否存在
    try:
        found = sr._find_outliner_context(bpy.context)
        space = found[3]
        prop = space.bl_rna.properties["filter_id_type"]
        out["steps"]["filter_id_type_items"] = [
            i.identifier for i in prop.enum_items]
    except Exception as exc:
        out["steps"]["filter_id_type_items"] = repr(exc)
    out["steps"]["plugin_id_type_map"] = {
        getattr(k, "__name__", str(k)): v
        for k, v in sr._ID_TYPE_FOR_FILTER.items()}
except Exception as exc:
    out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
finally:
    try:
        found = sr._find_outliner_context(bpy.context)
        w, a, region, space = found
        with bpy.context.temp_override(window=w, screen=w.screen, area=a,
                                       region=region, space_data=space):
            bpy.ops.outliner.select_all(action="DESELECT")
    except Exception:
        pass
    for _d, _coll in ((mat, bpy.data.materials), (me, bpy.data.meshes),
                      (img, bpy.data.images)):
        try:
            if _d.users == 0:
                _coll.remove(_d)
        except Exception:
            pass
    try:
        sr.register()
    except Exception:
        pass

result = out
print("[probe10]", out.get("steps", {}))
