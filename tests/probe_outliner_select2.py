# -*- coding: utf-8 -*-
"""Select References v3 §4 探针第二轮：定位 filter_text + select_all hack
第一轮全 [] 的根因（tests/probe_outliner_select.py 的 P3b）。

第一轮事实：select_all 未抛错，但 override 内读 selected_ids 恒为空。
待区分假设：
  H1: select_all 在 temp_override 上下文中根本不改选中（op 空转）；
  H2: 过滤生效但 0 用户的新建材质不在 LIBRARIES 树中（Blender File 模式
      可能不列出孤儿数据）→ 换 use_fake_user 材质与真实被引用材质再测；
  H3: LIBRARIES 模式下过滤器本身不过滤（则空过滤 select_all 会全选）。

步骤（均带过滤器执行，尽量不动用户既有 outliner 选中）：
  S1 记录 override 内当前 outliner 选中基线；
  S2 空过滤 + SELECT（诊断 select_all 是否空转，会临时全选；随后空过滤
     DESELECT 还原为"全不选"——用户原选中无法逐行恢复，记录基线供报告）；
  S3 fake_user 探测材质（SR_PROBE2_FakeMat）过滤单选；
  S4 用户文件真实被引用材质（自动挑一个 users>0 的）过滤单选；
  S5 还原：DESELECT 本前缀 + 还原 filter_text / display_mode。
"""
import bpy
import traceback

out = {"env": {}, "steps": {}, "conclusions": []}


def _concl(text):
    out["conclusions"].append(text)


win = None
area = None
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        if a.type == "OUTLINER":
            win, area = w, a
            break
    if area is not None:
        break

out["env"] = {
    "has_outliner_area": area is not None,
    "outliner_display_mode": (area.spaces.active.display_mode if area else None),
}

if area is None:
    _concl("无 Outliner 区域，第二轮探针无法执行。")
    result = out
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig_mode = _space.display_mode
    _orig_filter = _space.filter_text
    _mats = []
    try:
        _space.display_mode = "LIBRARIES"

        def _ovr():
            return bpy.context.temp_override(window=win, screen=win.screen,
                                             area=area, region=_region,
                                             space_data=_space)

        def _read_sel():
            return sorted("{}:{}".format(type(i).__name__, i.name)
                          for i in bpy.context.selected_ids)

        def _sel_all(action):
            bpy.ops.outliner.select_all(action=action)

        # S1 基线
        with _ovr():
            out["steps"]["s1_baseline"] = _read_sel()[:30]

        # S2 空过滤 SELECT 全量（诊断 select_all 是否空转）
        _space.filter_text = ""
        with _ovr():
            _sel_all("SELECT")
            _after = _read_sel()
        out["steps"]["s2_select_all_count"] = len(_after)
        out["steps"]["s2_select_all_sample"] = _after[:15]
        # 还原为全不选（用户原选中见 s1_baseline，无法逐行恢复，报告中说明）
        with _ovr():
            _sel_all("DESELECT")
            out["steps"]["s2_after_deselect_count"] = len(_read_sel())

        # S3 fake_user 探测材质过滤单选
        _fm = bpy.data.materials.new("SR_PROBE2_FakeMat")
        _fm.use_fake_user = True
        _mats.append(_fm)
        _space.filter_text = "SR_PROBE2_FakeMat"
        with _ovr():
            _sel_all("SELECT")
            out["steps"]["s3_fake_mat_selected"] = _read_sel()

        # S4 真实被引用材质（users>0）过滤单选
        _real = next((m for m in bpy.data.materials
                      if m.users > 0 and not m.name.startswith("SR_PROBE2_")), None)
        if _real is not None:
            out["steps"]["s4_real_mat"] = {"name": _real.name, "users": _real.users}
            with _ovr():
                _sel_all("DESELECT")
            _space.filter_text = _real.name
            with _ovr():
                _sel_all("SELECT")
                out["steps"]["s4_real_selected"] = _read_sel()
            # 清理真实材质行的选中
            with _ovr():
                _sel_all("DESELECT")
        else:
            out["steps"]["s4_real_mat"] = None

        # 判定
        _s2_ok = out["steps"]["s2_select_all_count"] > 0
        _s3_hit = any("SR_PROBE2_FakeMat" in x
                      for x in out["steps"].get("s3_fake_mat_selected", []))
        _s4_list = out["steps"].get("s4_real_selected", [])
        _s4_hit = bool(_real is not None and any(
            x.endswith(":" + _real.name) or (":" + _real.name) in x for x in _s4_list))
        out["verdict"] = {
            "select_all_works_in_override": _s2_ok,
            "fake_user_mat_selectable": _s3_hit,
            "real_referenced_mat_selectable": _s4_hit,
        }
        if _s2_ok and _s4_hit:
            _concl("S2/S4: select_all 在 temp_override 上下文有效；"
                   "过滤单选真实被引用材质成功——filter_text hack 在 LIBRARIES "
                   "模式可行（第一轮失败根因是 0 用户孤儿材质不入树/不匹配）。")
        elif _s2_ok and not _s4_hit:
            _concl("S2: select_all 有效（空过滤选中 {} 行）；但 S4 过滤单选真实"
                   "材质仍为空——过滤器在 LIBRARIES 模式不对数据块行生效，"
                   "hack 不可行。".format(out["steps"]["s2_select_all_count"]))
        else:
            _concl("S2: 空过滤 select_all 后选中数仍={}——select_all 在 "
                   "temp_override 上下文空转，hack 不可行。".format(
                       out["steps"]["s2_select_all_count"]))
        if _s3_hit and not _s4_hit:
            _concl("S3 补充：fake_user 材质可选中，真实材质不可——现象异常，需人工复核。")
    except Exception as exc:
        out["error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
        _concl("第二轮探针异常：{}".format(repr(exc)))
    finally:
        try:
            _space.filter_text = _orig_filter
            _space.display_mode = _orig_mode
        except Exception:
            pass
        for _m in _mats:
            try:
                bpy.data.materials.remove(_m, do_unlink=True)
            except Exception:
                pass
    result = out

print("[probe_outliner_select2] conclusions:")
for _c in out["conclusions"]:
    print("  -", _c)
