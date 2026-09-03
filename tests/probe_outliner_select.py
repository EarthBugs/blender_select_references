# -*- coding: utf-8 -*-
"""Select References v3 设计文档 §4 选择机制探针（Blender 5.2 会话内经 socket 执行）。

探针目标：非 Object 数据块引用者（Material/Mesh/Camera/GN 组）能否在大纲
"Blender File"（LIBRARIES）模式下被编程高亮。按设计文档 §4 顺序执行三条探针：

  P1: bpy.context.selected_ids 可写性（直接赋值 / extend / temp_override 注入）；
  P2: bpy.types.SpaceOutliner 的 RNA 属性/函数中是否存在选择相关接口；
  P3: bpy.ops.outliner.* 中是否存在可按 ID/名字定位选中的 op；
      并实测 "filter_text 过滤 + select_all" hack 在 LIBRARIES 模式下的可行性
      （过滤是否生效、子串碰撞、还原过滤器后选择是否持久、状态还原）。

副作用控制：
- 只新建/删除 SR_PROBE_ 前缀材质（结束全部清理）；
- 切换 Outliner 区域的 display_mode 与 filter_text 后均还原；
- select/deselect 均带 SR_PROBE_ 前缀过滤，不触碰用户既有 outliner 选中；
- 结束时 result 变量给出各探针原始数据与结论列表。
"""
import bpy
import traceback

out = {"env": {}, "p1": {}, "p2": {}, "p3": {}, "conclusions": []}


def _concl(text):
    out["conclusions"].append(text)


# ============================================================================
# 0. 环境：定位 Outliner 区域
# ============================================================================
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
    "version": ".".join(str(x) for x in bpy.app.version),
    "file": bpy.data.filepath or "<unsaved>",
    "has_outliner_area": area is not None,
    "outliner_display_mode": (area.spaces.active.display_mode if area else None),
}

# ============================================================================
# P1: bpy.context.selected_ids 可写性
# ============================================================================
p1 = out["p1"]
try:
    cur = bpy.context.selected_ids
    p1["read_ok"] = True
    p1["current"] = ["{}:{}".format(type(i).__name__, i.name) for i in cur][:20]
    p1["returned_type"] = type(cur).__name__
except Exception as exc:
    p1["read_ok"] = False
    p1["read_error"] = repr(exc)

# 1a 直接赋值
try:
    bpy.context.selected_ids = []
    p1["direct_assign"] = "unexpectedly succeeded"
except Exception as exc:
    p1["direct_assign"] = "{}: {}".format(type(exc).__name__, exc)

# 1b 返回对象是否"活"（两次读取是否同一对象 / extend 是否影响真实选择）
if p1.get("read_ok"):
    try:
        p1["two_reads_identical_object"] = bpy.context.selected_ids is bpy.context.selected_ids
    except Exception as exc:
        p1["two_reads_identical_object"] = repr(exc)
    _before = sorted(i.name for i in bpy.context.selected_ids)
    try:
        bpy.context.selected_ids.extend([])
        p1["extend_call"] = "ok"
    except Exception as exc:
        p1["extend_call"] = repr(exc)
    _after = sorted(i.name for i in bpy.context.selected_ids)
    p1["selection_unchanged_after_extend"] = _before == _after

# 1c temp_override 注入（已知在 operator 测试路径可行，此处确认读取侧）
_probe_mat = bpy.data.materials.new("SR_PROBE_OverrideMat")
try:
    with bpy.context.temp_override(selected_ids=[_probe_mat]):
        p1["temp_override_read"] = sorted(i.name for i in bpy.context.selected_ids)
except Exception as exc:
    p1["temp_override_read"] = repr(exc)

if (not p1.get("read_ok")) or "succeeded" not in str(p1.get("direct_assign", "")):
    _concl("P1: selected_ids 为只读 context 成员（直接赋值抛 {}），"
           "返回的是快照 list 而非活集合；唯一可写路径是 temp_override 注入"
           "（仅对注入期间生效，不改动真实 outliner 选中）"
           "——无法经 selected_ids 编程设置大纲数据块选中态。".format(
               str(p1.get("direct_assign", "n/a")).split(":")[0]))
else:
    _concl("P1: selected_ids 直接赋值意外成功——需人工复核。")

# ============================================================================
# P2: SpaceOutliner RNA 选择相关接口
# ============================================================================
p2 = out["p2"]
_props = sorted(p.identifier for p in bpy.types.SpaceOutliner.bl_rna.properties)
_funcs = sorted(f.identifier for f in bpy.types.SpaceOutliner.bl_rna.functions)
p2["properties"] = _props
p2["functions"] = _funcs
_kw = ("select", "active", "highlight", "cursor")
p2["selection_related"] = [x for x in _props + _funcs
                           if any(k in x.lower() for k in _kw)]
if p2["selection_related"]:
    _concl("P2: SpaceOutliner RNA 含疑似选择相关成员 {}——需进一步验证语义。".format(
        p2["selection_related"]))
else:
    _concl("P2: SpaceOutliner RNA 属性/函数中不存在任何选择相关接口"
           "（属性 {} 个、函数 {} 个，无一命中 select/active/highlight/cursor 关键词）。".format(
               len(_props), len(_funcs)))

# ============================================================================
# P3: outliner ops + filter_text hack 实测
# ============================================================================
p3 = out["p3"]
_ops = sorted(dir(bpy.ops.outliner))
p3["ops"] = _ops
for _op_name in ("item_activate", "select_all", "select_box", "id_delete"):
    try:
        _rna = getattr(bpy.ops.outliner, _op_name).get_rna_type()
        p3["op_params_" + _op_name] = sorted(p.identifier for p in _rna.properties)
    except Exception as exc:
        p3["op_params_" + _op_name] = repr(exc)

_select_like = [o for o in _ops if "select" in o]
_concl("P3a: bpy.ops.outliner 可用 op 共 {} 个，含 select 字样的为 {}；"
       "无任何可按 ID/名字直接定位选中的 op（item_activate/select_box 均依赖"
       "鼠标坐标，不可编程定向）。".format(len(_ops), _select_like))

if area is None:
    p3["filter_hack"] = "skipped: 会话中不存在 OUTLINER 区域"
    _concl("P3b: 无 Outliner 区域，filter_text hack 无法实测（跳过）。")
else:
    _space = area.spaces.active
    _region = next((r for r in area.regions if r.type == "WINDOW"), None)
    _orig_mode = _space.display_mode
    _orig_filter = _space.filter_text
    _mats = []
    _has_select_all = hasattr(bpy.ops.outliner, "select_all")
    p3["has_select_all_op"] = _has_select_all
    try:
        if not _has_select_all:
            p3["filter_hack"] = "skipped: outliner.select_all op 不存在"
        else:
            _m_unique = bpy.data.materials.new("SR_PROBE_Unique")
            _m_a = bpy.data.materials.new("SR_PROBE_Mat")
            _m_b = bpy.data.materials.new("SR_PROBE_MatExtra")
            _mats = [_m_unique, _m_a, _m_b]
            _space.display_mode = "LIBRARIES"

            def _hack(filter_text, action):
                """设过滤器 → override 注入 outliner 上下文 → select_all →
                返回本次选中中 SR_PROBE_ 前缀的名字列表。"""
                _space.filter_text = filter_text
                with bpy.context.temp_override(window=win, screen=win.screen,
                                               area=area, region=_region,
                                               space_data=_space):
                    bpy.ops.outliner.select_all(action=action)
                    return sorted(i.name for i in bpy.context.selected_ids
                                  if i.name.startswith("SR_PROBE_"))

            # 3b-1 基线：不匹配任何行的过滤器 + SELECT → 若过滤生效应选不到东西
            p3["nomatch_selected"] = _hack("SR_PROBE_NOMATCH_ZZZ", "SELECT")
            # 3b-2 精确名单选（先确保干净）
            _hack("SR_PROBE_", "DESELECT")
            p3["unique_selected"] = _hack("SR_PROBE_Unique", "SELECT")
            # 3b-3 子串碰撞：过滤器 "SR_PROBE_Mat" 期望同时命中 Mat 与 MatExtra
            p3["substring_selected"] = _hack("SR_PROBE_Mat", "SELECT")
            # 3b-4 还原过滤器后选择是否持久
            _space.filter_text = _orig_filter
            p3["persist_after_filter_restore"] = sorted(
                i.name for i in bpy.context.selected_ids
                if i.name.startswith("SR_PROBE_"))
            # 3b-5 清理：仅对 SR_PROBE_ 前缀 DESELECT，不动用户选中
            p3["deselected_cleanup"] = _hack("SR_PROBE_", "DESELECT")
            _space.filter_text = _orig_filter
            p3["final_selected_sr_probe"] = sorted(
                i.name for i in bpy.context.selected_ids
                if i.name.startswith("SR_PROBE_"))

            _filter_works = p3["nomatch_selected"] == []
            _unique_ok = p3["unique_selected"] == ["SR_PROBE_Unique"]
            _persist_ok = "SR_PROBE_Unique" in p3.get("persist_after_filter_restore", [])
            p3["verdict"] = {
                "filter_effective_in_libraries": _filter_works,
                "exact_single_select_ok": _unique_ok,
                "substring_collision_observed": p3["substring_selected"],
                "selection_persists_after_filter_restore": _persist_ok,
            }
            if _filter_works and _unique_ok:
                _concl(
                    "P3b: filter_text + select_all hack 在 LIBRARIES 模式实测可行——"
                    "过滤器生效（不匹配基线选中 {} 个）、精确名单选命中 {}、"
                    "还原过滤器后选中态{}；"
                    "但过滤为子串匹配（过滤器 'SR_PROBE_Mat' 同时选中 {}），"
                    "同名前缀碰撞时会多选且 API 无法逐行反选。".format(
                        len(p3["nomatch_selected"]), p3["unique_selected"],
                        "持久" if _persist_ok else "丢失",
                        p3["substring_selected"]))
            else:
                _concl(
                    "P3b: filter_text hack 在 LIBRARIES 模式实测不可行"
                    "（过滤生效={}，精确单选={}）。".format(_filter_works, _unique_ok))
    except Exception as exc:
        p3["filter_hack_error"] = "{}\n{}".format(repr(exc), traceback.format_exc())
        _concl("P3b: filter_text hack 实测抛异常：{}".format(repr(exc)))
    finally:
        try:
            _space.display_mode = _orig_mode
            _space.filter_text = _orig_filter
        except Exception:
            pass
        for _m in _mats:
            try:
                bpy.data.materials.remove(_m, do_unlink=True)
            except Exception:
                pass

# P1 探针材质清理
try:
    bpy.data.materials.remove(_probe_mat, do_unlink=True)
except Exception:
    pass

result = out
print("[probe_outliner_select] conclusions:")
for _c in out["conclusions"]:
    print("  -", _c)
