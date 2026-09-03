# -*- coding: utf-8 -*-
"""Select References v3 §4 探针第四轮：use_filter_children=False 能否让
select_all 只选中过滤命中行（去掉父级链过选）。

第三轮实测：泵 redraw_timer 后过滤器生效，但 select_all 选中了全部"可见行"
——含命中行的父级链（Scene/Collection/Object），会污染高亮与 selected_ids。
本轮验证：use_filter_children=False（及 use_filter_case_sensitive）配合下，
select_all 是否只命中过滤行本身；并验证还原过滤器后选中态持久、以及
selected_ids 去重语义（同一 ID 多处出现只算一次引用者）。

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
    out["conclusions"].append("无 Outliner 区域，第四轮探针无法执行。")
    result = out
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig = {
        "display_mode": _space.display_mode,
        "filter_text": _space.filter_text,
        "use_filter_children": _space.use_filter_children,
        "use_filter_complete": _space.use_filter_complete,
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

        # V1: use_filter_children=False + 大小写敏感 + 泵重绘
        _space.use_filter_children = False
        _space.use_filter_case_sensitive = True
        _space.filter_text = "m2"
        with _ovr():
            _pump()
            bpy.ops.outliner.select_all(action="SELECT")
            v1 = _read_sel()
        out["steps"]["v1_no_children_selected"] = v1

        # V2: 再叠 use_filter_complete=False
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")
        _space.use_filter_complete = False
        with _ovr():
            _pump()
            bpy.ops.outliner.select_all(action="SELECT")
            v2 = _read_sel()
        out["steps"]["v2_no_complete_selected"] = v2

        # V3: 还原过滤器后选中持久性 + selected_ids 去重（以 V2 结果继续）
        _space.filter_text = _orig["filter_text"]
        _space.use_filter_children = _orig["use_filter_children"]
        _space.use_filter_complete = _orig["use_filter_complete"]
        with _ovr():
            _pump()
            after = _read_sel()
        out["steps"]["v3_persist_after_restore"] = after
        out["steps"]["v3_unique_ids"] = sorted({x for x in after})

        # 清理选中
        _space.filter_text = ""
        with _ovr():
            bpy.ops.outliner.select_all(action="DESELECT")

        v1_types = sorted({x.split(":")[0] for x in v1})
        v2_types = sorted({x.split(":")[0] for x in v2})
        out["verdict"] = {
            "v1_row_types": v1_types,
            "v2_row_types": v2_types,
            "v1_only_material": v1_types == ["Material"] if v1 else False,
            "v2_only_material": v2_types == ["Material"] if v2 else False,
            "persist_ok": "Material:m2" in after,
        }
        if out["verdict"]["v1_only_material"] or out["verdict"]["v2_only_material"]:
            out["conclusions"].append(
                "filter hack 精简单选可行：V1(children=False) 行类型 {} / "
                "V2(再+complete=False) 行类型 {}；还原过滤器后选中{}。".format(
                    v1_types, v2_types,
                    "持久" if out["verdict"]["persist_ok"] else "丢失"))
        else:
            out["conclusions"].append(
                "父级链过选无法消除：V1 行类型 {}、V2 行类型 {}——filter hack "
                "无法精确单选数据块行，走回退方案。".format(v1_types, v2_types))
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
        out["conclusions"].append("第四轮探针异常：{}".format(repr(exc)))
    finally:
        try:
            for _k, _v in _orig.items():
                setattr(_space, _k, _v)
        except Exception:
            pass
    result = out

print("[probe_outliner_select4]")
for _c in out["conclusions"]:
    print("  -", _c)
