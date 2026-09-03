# -*- coding: utf-8 -*-
"""Select References v3 §4 探针第三轮：设过滤器后泵一次重绘再 select_all。

第二轮实测：filter_text 设置后同步 select_all 选中了全部行（过滤器被无视）。
假设：outliner 树在 draw 时才按新过滤器重建，同步 exec 中 select_all 看到的是
旧树。本轮换证：filter_text → tag_redraw → bpy.ops.wm.redraw_timer（同步泵
一次绘制）→ select_all，观察是否只选中过滤命中行。

副作用：仅改动 outliner 行选中（结束 DESELECT 清空并还原过滤器/显示模式）。
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
    out["conclusions"].append("无 Outliner 区域，第三轮探针无法执行。")
    result = out
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig_mode = _space.display_mode
    _orig_filter = _space.filter_text
    try:
        _space.display_mode = "LIBRARIES"

        def _ovr():
            return bpy.context.temp_override(window=win, screen=win.screen,
                                             area=area, region=_region,
                                             space_data=_space)

        def _read_sel():
            return sorted("{}:{}".format(type(i).__name__, i.name)
                          for i in bpy.context.selected_ids)

        # 起点清空
        _space.filter_text = ""
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
            out["steps"]["clean_count"] = len(_read_sel())

        # 设过滤器 → 泵重绘 → select_all
        _space.filter_text = "m2"
        area.tag_redraw()
        redraw_results = {}
        for rtype in ("DRAW", "DRAW_WIN"):
            try:
                with _ovr():
                    bpy.ops.wm.redraw_timer(type=rtype)
                redraw_results[rtype] = "ok"
            except Exception as exc:
                redraw_results[rtype] = repr(exc)
        out["steps"]["redraw_timer"] = redraw_results

        with _ovr():
            bpy.ops.outliner.select_all(action="SELECT")
            out["steps"]["after_redraw_selected"] = _read_sel()

        # 对照：不泵重绘直接再来一次（先清空）
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        _space.filter_text = "m2"
        with _ovr():
            bpy.ops.outliner.select_all(action="SELECT")
            out["steps"]["no_redraw_selected"] = _read_sel()

        # 清理
        _space.filter_text = ""
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")

        sel = out["steps"]["after_redraw_selected"]
        only_m2 = sel and all(x.endswith(":m2") for x in sel)
        out["verdict"] = {
            "after_redraw_count": len(sel),
            "after_redraw_only_m2": bool(only_m2),
            "no_redraw_count": len(out["steps"]["no_redraw_selected"]),
        }
        if only_m2:
            out["conclusions"].append(
                "泵重绘后 select_all 仅命中过滤行 {}——filter hack 需先泵一次 "
                "redraw_timer 才生效，技术可行。".format(sel))
        else:
            out["conclusions"].append(
                "泵重绘后 select_all 仍选中 {} 行（非仅 m2）——过滤器对 "
                "select_all 无效并非重绘时序问题，filter hack 确认不可行。".format(
                    len(sel)))
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
        out["conclusions"].append("第三轮探针异常：{}".format(repr(exc)))
    finally:
        try:
            _space.filter_text = _orig_filter
            _space.display_mode = _orig_mode
        except Exception:
            pass
    result = out

print("[probe_outliner_select3]")
for _c in out["conclusions"]:
    print("  -", _c)
