# -*- coding: utf-8 -*-
"""诊断 11：单步复现 select_datablock_rows 对 Material 失败、Mesh 成功。

逐步骤记录：过滤设置 → 泵 → select_all → 读 selected_ids；
失败时尝试 expand_all / 多次泵后再选。枚举 outliner 展开相关 ops。
"""
import bpy
import traceback

out = {"steps": {}, "conclusions": []}

mat = bpy.data.materials.get("SR_D11_Mat") or bpy.data.materials.new("SR_D11_Mat")
me = bpy.data.meshes.get("SR_D11_Mesh") or bpy.data.meshes.new("SR_D11_Mesh")

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
    try:
        space.display_mode = "LIBRARIES"

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

        out["steps"]["expand_ops"] = sorted(
            op for op in dir(bpy.ops.outliner)
            if "expand" in op or "open" in op or "show" in op)

        for tag, idb, ftype in (("mat", mat, "MATERIAL"),
                                ("mesh", me, "MESH")):
            st = {}
            with _ovr():
                bpy.ops.outliner.select_all(action="DESELECT")
            space.use_filter_id_type = True
            space.filter_id_type = ftype
            space.use_filter_case_sensitive = True
            space.filter_text = idb.name
            with _ovr():
                _pump(1)
                bpy.ops.outliner.select_all(action="SELECT")
                st["after_1_pump"] = _read()
                # 再泵两次后重选
                _pump(2)
                bpy.ops.outliner.select_all(action="SELECT")
                st["after_3_pump"] = _read()
                # expand_all 尝试
                try:
                    bpy.ops.outliner.expand_all()
                    _pump(1)
                    bpy.ops.outliner.select_all(action="SELECT")
                    st["after_expand_all"] = _read()
                except Exception as exc:
                    st["expand_all_error"] = repr(exc)
            out["steps"][tag] = st
            space.filter_text = ""
            with _ovr():
                _pump(1)
                bpy.ops.outliner.select_all(action="DESELECT")
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

print("[probe11]")
import json
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
