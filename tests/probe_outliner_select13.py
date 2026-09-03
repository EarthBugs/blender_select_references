# -*- coding: utf-8 -*-
"""探针 13：验证多目标行高亮的最终可行形态。

probe12/F 发现：restore 后"丢选"只是已选行处于折叠分节中不可见，
show_one_level(open=True) 展开后选中恢复显示——选中状态本身持久。

若逐名过滤多目标累加时"被过滤隐藏的已选行"同样只是不可见而非真丢，
则最终 restore + show_one_level 可让所有目标行重新可见且保持选中，
多目标高亮成立（推翻 probe8/E1 的"不可行"结论）。

变体：
  G 两目标跨类型：mat(MATERIAL) → cam(CAMERA) 逐名过滤累加
  H 三目标两类型：mat_a + mat_b(MATERIAL) → cam(CAMERA)
  I 两目标跨类型逆序：cam → mat（顺序敏感性）
每个变体：逐名过滤累加 → restore 全还原 → 泵 → 读 →
          show_one_level(open=True) → 泵 → 读。
"""
import bpy
import traceback
import json

out = {"steps": {}, "conclusions": []}

mat_a = bpy.data.materials.get("SR_D13_MatA") or bpy.data.materials.new("SR_D13_MatA")
mat_b = bpy.data.materials.get("SR_D13_MatB") or bpy.data.materials.new("SR_D13_MatB")
cam = bpy.data.cameras.get("SR_D13_Cam") or bpy.data.cameras.new("SR_D13_Cam")

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

    def _restore_all():
        for k, v in _orig.items():
            if k != "display_mode":
                try:
                    setattr(space, k, v)
                except Exception:
                    pass

    def _multi_variant(targets):
        """targets: [(idb, ftype), ...] 逐名过滤累加 → restore → show_one_level。"""
        st = {}
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        for i, (idb, ftype) in enumerate(targets):
            space.use_filter_id_type = True
            space.filter_id_type = ftype
            space.use_filter_case_sensitive = True
            space.filter_text = idb.name
            with _ovr():
                _pump(1)
                bpy.ops.outliner.select_all(action="SELECT")
                st["after_step_{}".format(i)] = _read()
        _restore_all()
        with _ovr():
            _pump(1)
            st["after_restore"] = _read()
            bpy.ops.outliner.show_one_level(open=True)
            _pump(1)
            st["after_show_one_level"] = _read()
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        return st

    try:
        space.display_mode = "LIBRARIES"
        out["steps"]["G_mat_then_cam"] = _multi_variant(
            [(mat_a, "MATERIAL"), (cam, "CAMERA")])
        out["steps"]["H_matA_matB_cam"] = _multi_variant(
            [(mat_a, "MATERIAL"), (mat_b, "MATERIAL"), (cam, "CAMERA")])
        out["steps"]["I_cam_then_mat"] = _multi_variant(
            [(cam, "CAMERA"), (mat_a, "MATERIAL")])
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
        for _d, _c in ((mat_a, bpy.data.materials), (mat_b, bpy.data.materials),
                       (cam, bpy.data.cameras)):
            try:
                if _d.users == 0:
                    _c.remove(_d)
            except Exception:
                pass
    result = out

print("[probe13]")
print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
