# -*- coding: utf-8 -*-
"""Select References v3 §4 探针第五轮（最终轮）：filter_id_type 限定类型分节后
select_all 是否只选中目标类型行。

第四轮实测：use_filter_children/complete 均无法消除父级链过选（Scene/
Collection/Object 行被一并选中）。SpaceOutliner 另有 use_filter_id_type +
filter_id_type 两个属性——若能把 LIBRARIES 树限定到单一类型分节，对象层级
里的同名行消失，父级链过选即消除。本轮实测之，并枚举 filter_id_type 合法值。

结束还原全部空间设置与选中状态。
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
    out["conclusions"].append("无 Outliner 区域，第五轮探针无法执行。")
    result = out
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)

    # 枚举 filter_id_type 合法值
    try:
        _prop = _space.bl_rna.properties["filter_id_type"]
        out["steps"]["filter_id_type_items"] = [
            i.identifier for i in _prop.enum_items]
    except Exception as exc:
        out["steps"]["filter_id_type_items"] = repr(exc)

    _orig = {
        "display_mode": _space.display_mode,
        "filter_text": _space.filter_text,
        "use_filter_id_type": _space.use_filter_id_type,
        "filter_id_type": _space.filter_id_type,
        "use_filter_case_sensitive": _space.use_filter_case_sensitive,
    }
    out["steps"]["orig_settings"] = {k: str(v) for k, v in _orig.items()}
    try:
        _space.display_mode = "LIBRARIES"

        def _ovr():
            return bpy.context.temp_override(window=win, screen=win.screen,
                                             area=area, region=_region,
                                             space_data=_space)

        def _read_sel():
            return sorted("{}:{}".format(type(i).__name__, i.name)
                          for i in bpy.context.selected_ids)

        def _pump():
            area.tag_redraw()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN")

        # 起点清空
        _space.filter_text = ""
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")

        # V1: 限定 MATERIAL 分节 + 过滤 "m2" + 泵重绘
        _space.use_filter_id_type = True
        try:
            _space.filter_id_type = "MATERIAL"
            out["steps"]["set_id_type"] = "ok"
        except Exception as exc:
            out["steps"]["set_id_type"] = repr(exc)
        _space.use_filter_case_sensitive = True
        _space.filter_text = "m2"
        with _ovr():
            _pump()
            bpy.ops.outliner.select_all(action="SELECT")
            v1 = _read_sel()
        out["steps"]["v1_material_only_selected"] = v1

        # V2: 还原过滤器后的持久性与 selected_ids 构成
        _space.filter_text = ""
        with _ovr():
            _pump()
            out["steps"]["v2_persist"] = _read_sel()

        # 清理选中
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")

        v1_types = sorted({x.split(":")[0] for x in v1})
        v1_names = sorted({x for x in v1})
        out["verdict"] = {
            "v1_row_types": v1_types,
            "v1_unique_rows": v1_names,
            "v1_only_target_material": v1_names == ["Material:m2"] if v1 else False,
            "persist_ok": any(x == "Material:m2" for x in out["steps"]["v2_persist"]),
        }
        if out["verdict"]["v1_only_target_material"]:
            out["conclusions"].append(
                "filter_id_type=MATERIAL + filter_text 精确单选可行：select_all "
                "唯一命中 {}（重复行同 ID 已去重）；还原过滤器后选中{}。"
                "——选择机制落地路径成立：限定类型分节 + 名字过滤 + 泵重绘 + "
                "select_all，结束后还原空间设置。".format(
                    v1_names, "持久" if out["verdict"]["persist_ok"] else "丢失"))
        else:
            out["conclusions"].append(
                "filter_id_type 限定后 select_all 命中 {}（类型 {}）——"
                "仍非精确单选，确认走回退方案（INFO 列出数据块引用者）。".format(
                    v1_names, v1_types))
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
        out["conclusions"].append("第五轮探针异常：{}".format(repr(exc)))
    finally:
        try:
            for _k, _v in _orig.items():
                setattr(_space, _k, _v)
            with _ovr():
                bpy.ops.outliner.select_all(action="DESELECT")
        except Exception:
            pass
    result = out

print("[probe_outliner_select5]")
for _c in out["conclusions"]:
    print("  -", _c)
