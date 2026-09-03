# -*- coding: utf-8 -*-
"""发布验证：addon_disable + addon_enable 刷新 addons 副本，验证 v1.2.0 注册。

- 刷新后模块文件路径必须是 addons 副本；
- bl_info version 必须 (1, 2, 0)；
- operator 注册状态用 ValueError 探针（5.2 hasattr(bpy.types,...) 恒 False）；
- 新函数 find_direct_referencers / select_datablock_rows 存在（v3 代码生效）。
"""
import bpy
import sys
import traceback

out = {"steps": {}, "conclusions": []}
try:
    try:
        bpy.ops.preferences.addon_disable(module="select_references")
        out["steps"]["disable"] = "ok"
    except Exception as exc:
        out["steps"]["disable"] = repr(exc)
    # 清掉所有缓存模块，强制从 addons 重新加载；
    # 临时从 sys.path 移除工作区路径（之前测试脚本插入的），避免 import
    # 命中工作区同名副本而非 addons 副本
    for name in [n for n in list(sys.modules) if n == "select_references"]:
        sys.modules.pop(name, None)
    _ws = r"C:\Users\EarthBugs\Documents\current_working\20260901_blender_select_references"
    _removed = []
    for p in list(sys.path):
        if p.rstrip("\\/").lower() == _ws.lower():
            sys.path.remove(p)
            _removed.append(p)
    try:
        bpy.ops.preferences.addon_enable(module="select_references")
    finally:
        sys.path.extend(_removed)
    out["steps"]["enable"] = "ok"

    mod = sys.modules.get("select_references")
    if mod is None:
        import select_references as mod
    out["steps"]["module_file"] = getattr(mod, "__file__", None)
    out["steps"]["version"] = list(mod.bl_info.get("version", ()))
    out["steps"]["has_find_direct_referencers"] = hasattr(
        mod, "find_direct_referencers")
    out["steps"]["has_select_datablock_rows"] = hasattr(
        mod, "select_datablock_rows")
    out["steps"]["id_type_filter_has_image"] = (
        "IMAGE" in getattr(mod, "_ID_TYPE_FOR_FILTER", {}).values())

    try:
        bpy.utils.register_class(mod.SELECT_REFERENCING_OT_select_references)
        out["steps"]["operator_registered"] = "not-registered"
    except ValueError:
        out["steps"]["operator_registered"] = "registered"

    ok = (out["steps"]["operator_registered"] == "registered"
          and out["steps"]["version"] == [1, 2, 0]
          and out["steps"]["has_find_direct_referencers"]
          and out["steps"]["has_select_datablock_rows"]
          and out["steps"]["id_type_filter_has_image"]
          and "addons" in str(out["steps"]["module_file"]).lower())
    out["conclusions"].append(
        "发布验证{}：version={} operator={} module={}".format(
            "通过" if ok else "失败", out["steps"]["version"],
            out["steps"]["operator_registered"], out["steps"]["module_file"]))
    out["publish_ok"] = bool(ok)
except Exception as exc:
    out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
    out["publish_ok"] = False
result = out
print("[publish_verify]", out.get("conclusions"))
