# -*- coding: utf-8 -*-
"""探针 12：定位 select_datablock_rows 的 restore 丢选根因并验证修复候选。

假设：还原过滤器（filter_text 清空）触发大纲树重建，已选行若处于折叠的
类型分节中则丢选（Mesh 分节当前展开故保留，Material 分节折叠故丢失）。

变体：
  A mat: 过滤+选中 → restore(全还原) → 泵 → 读（预期：复现丢失）
  B mesh: 同 A（预期：保留，对照）
  C mat: 过滤+选中 → 仅清 filter_text 保留 MATERIAL 限定 → 泵 → 读
         （分节限定下树是否保留选中）
  D mat: 过滤+选中 → expanded_toggle（对选中行）→ restore → 泵 → 读
  E mat: 过滤+选中 → restore → 泵 → 重新过滤+选中 → 泵 → 读（不二次还原，
         验证"保持过滤聚焦"终态可行）
  F mat: restore 后 show_one_level(open=True) → 泵 → 读（能否展开找回）
"""
import bpy
import traceback
import json

out = {"steps": {}, "conclusions": []}

mat = bpy.data.materials.get("SR_D12_Mat") or bpy.data.materials.new("SR_D12_Mat")
me = bpy.data.meshes.get("SR_D12_Mesh") or bpy.data.meshes.new("SR_D12_Mesh")

win = area = None
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        if a.type == "OUTLINER":
            win, area = w, a
            break
    if area is not None:
        break

if area is None:
    out["conclusions"].append("无 Outliner 区域")
    result = out
else:
    space = area.spaces.active
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig = {p: getattr(space, p) for p in
             ("display_mode", "filter_text", "use_filter_id_type",
              "filter_id_type", "use_filter_case_sensitive")}

    def _ovr():
        return bpy.context.temp_override(window=win, screen=win.screen,
                                         area=area, region=region,
                                         space_data=space)

    def _read():
        return sorted(i.name for i in bpy.context.selected_ids)

    def _pump(n=1):
        for _ in range(n):
            area.tag_redraw()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN")

    def _filter_select(idb, ftype):
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        space.use_filter_id_type = True
        space.filter_id_type = ftype
        space.use_filter_case_sensitive = True
        space.filter_text = idb.name
        with _ovr():
            _pump(1)
            bpy.ops.outliner.select_all(action="SELECT")
            return _read()

    def _restore_all():
        for k, v in _orig.items():
            if k != "display_mode":
                try:
                    setattr(space, k, v)
                except Exception:
                    pass

    try:
        space.display_mode = "LIBRARIES"

        # A: mat 全还原
        st = {"filtered": _filter_select(mat, "MATERIAL")}
        _restore_all()
        with _ovr():
            _pump(1)
            st["after_restore"] = _read()
        out["steps"]["A_mat_restore"] = st

        # B: mesh 全还原（对照）
        st = {"filtered": _filter_select(me, "MESH")}
        _restore_all()
        with _ovr():
            _pump(1)
            st["after_restore"] = _read()
        out["steps"]["B_mesh_restore"] = st

        # C: mat 仅清 filter_text，保留 MATERIAL 限定
        st = {"filtered": _filter_select(mat, "MATERIAL")}
        space.filter_text = ""
        with _ovr():
            _pump(1)
            st["after_clear_text_keep_type"] = _read()
        _restore_all()
        with _ovr():
            _pump(1)
            bpy.ops.outliner.select_all(action="DESELECT")
        out["steps"]["C_mat_keep_type"] = st

        # D: mat expanded_toggle 后还原
        st = {"filtered": _filter_select(mat, "MATERIAL")}
        try:
            with _ovr():
                bpy.ops.outliner.expanded_toggle()
                st["toggle_ok"] = True
        except Exception as exc:
            st["toggle_ok"] = repr(exc)
        _restore_all()
        with _ovr():
            _pump(1)
            st["after_restore"] = _read()
        out["steps"]["D_mat_toggle"] = st

        # E: mat 还原后重新过滤选中，终态保持过滤（不二次还原）
        st = {"filtered": _filter_select(mat, "MATERIAL")}
        _restore_all()
        with _ovr():
            _pump(1)
        st["reselect"] = _filter_select(mat, "MATERIAL")
        with _ovr():
            st["final_filtered_state"] = _read()
        out["steps"]["E_mat_reselect_keep_filter"] = st
        # 收尾还原
        _restore_all()
        with _ovr():
            _pump(1)
            st["after_final_restore"] = _read()

        # F: mat 还原丢选后 show_one_level 尝试找回
        st = {"filtered": _filter_select(mat, "MATERIAL")}
        _restore_all()
        with _ovr():
            _pump(1)
            st["after_restore"] = _read()
            try:
                bpy.ops.outliner.show_one_level(open=True)
                _pump(1)
                st["after_show_one_level"] = _read()
            except Exception as exc:
                st["show_one_level_error"] = repr(exc)
        out["steps"]["F_mat_show_one_level"] = st
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
    finally:
        try:
            for _k, _v in _orig.items():
                setattr(space, _k, _v)
            with _ovr():
                bpy.ops.outliner.select_all(action="DESELECT")
        except Exception:
            pass
        for _d, _c in ((mat, bpy.data.materials), (me, bpy.data.meshes)):
            try:
                if _d.users == 0:
                    _c.remove(_d)
            except Exception:
                pass
    result = out

print("[probe12]")
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
