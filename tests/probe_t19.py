# -*- coding: utf-8 -*-
"""T19 失败诊断：register/unregister 状态机实测探针（Blender 内执行）。

逐步调用 register_class/unregister_class，记录每一步的异常类型与
hasattr(bpy.types, ...) 的真实语义，定位"连续两次 register 后
operator 类查不到"的根因。
"""
import bpy
import sys

sr = sys.modules.get("select_references")
out = {"module_found": sr is not None}

CLS_NAME = "SELECT_REFERENCING_OT_select_references"


def _has():
    return hasattr(bpy.types, CLS_NAME)


out["has_initial"] = _has()
out["ledger_len"] = len(getattr(sr, "_APPENDED_DRAW_FNS", [])) if sr else None

if sr is not None:
    cls = sr.SELECT_REFERENCING_OT_select_references

    # 步骤 1：unregister 当前类
    try:
        bpy.utils.unregister_class(cls)
        out["unreg1"] = "ok"
    except Exception as exc:
        out["unreg1"] = repr(exc)
    out["has_after_unreg1"] = _has()

    # 步骤 2：再 unregister 一次（未注册态 → 观察异常类型）
    try:
        bpy.utils.unregister_class(cls)
        out["unreg2"] = "ok"
    except Exception as exc:
        out["unreg2"] = repr(exc)

    # 步骤 3：register
    try:
        bpy.utils.register_class(cls)
        out["reg1"] = "ok"
    except Exception as exc:
        out["reg1"] = repr(exc)
    out["has_after_reg1"] = _has()

    # 步骤 4：同 py 类对象重复 register（观察异常类型）
    try:
        bpy.utils.register_class(cls)
        out["reg2_same_class"] = "ok"
    except Exception as exc:
        out["reg2_same_class"] = repr(exc)
    out["has_after_reg2"] = _has()

    # 步骤 5：走插件自己的 unregister + register 两轮，复现 T19 失败路径
    try:
        sr.unregister()
        out["plugin_unreg"] = "ok"
    except Exception as exc:
        out["plugin_unreg"] = repr(exc)
    out["has_after_plugin_unreg"] = _has()
    try:
        sr.register()
        out["plugin_reg1"] = "ok"
    except Exception as exc:
        out["plugin_reg1"] = repr(exc)
    out["has_after_plugin_reg1"] = _has()
    try:
        sr.register()
        out["plugin_reg2"] = "ok"
    except Exception as exc:
        out["plugin_reg2"] = repr(exc)
    out["has_after_plugin_reg2"] = _has()
    out["ledger_final"] = len(sr._APPENDED_DRAW_FNS)

result = out
