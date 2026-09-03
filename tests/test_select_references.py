# -*- coding: utf-8 -*-
"""Select References 插件功能测试（Blender 内执行，v4，全同步）。

运行方式：由 tests/run_socket_test.py 读取本文件全文，经 Blender MCP socket 以
{"type": "execute", "code": <本文件内容>, "strict_json": true} 发送执行；
协议要求执行结束把汇总 dict 赋给 result 变量。

v4（对照 docs/design_v3.md，被测插件 v1.2.0，v3 一跳语义）：
- 扫描断言全部改到 find_direct_referencers 返回值的 objects/ids 分类：
  Image → ids={mat_a, mat_b(嵌套), cam_data}、objects={empty}，World 仅报告；
  Material(DATA) → ids={mesh_shared}（不含 obj_a/obj_b）；
  Material(OBJECT+DATA) → objects={obj_a}、ids={mesh_mat}；
  Mesh/Camera/Light/Curve/Curves → objects 同 v1；
  GN 子组 → ids={gn_parent}；GN 父组 → objects={obj_gn}；
- 选择落地（probe12/13 实测后的最终形态，全同步）：数据块引用者（单/多
  目标）→ select_datablock_rows 大纲行高亮（逐名过滤累加 + restore 后
  show_one_level 展开分节；早期"多目标丢选"系 selected_ids 只上报可见行
  的误判）；端到端直调 operator 类 execute 并以假 self 捕获 report 文本
  断言（bpy 类型禁止实例化、metaclass 使类级 monkeypatch 不生效）；
  端到端输入用 select_datablock_rows 真实选中输入行（等价用户点选），
  不用 temp_override 注入 selected_ids（注入会穿透嵌套 override 污染
  execute 内部的选中判定）；
- 模块导入陷阱（design_v3 §6 末条）：sys.modules 可能已有 addon 版
  select_references，须先 pop（并用其自身 unregister 清账本菜单项）再从工作区
  sys.path 导入，否则会测到旧代码；
- 保留：classify 五族、隐藏/排除防护、T19 注册幂等（置于 e2e 之前，避免
  reload 影响后续用例）、清理无残留（含 worlds/scenes）。

夹具全部使用 SR_TEST_ 前缀，测试结束后自动清理并恢复用户原选中状态。
"""

import bpy
import sys
import importlib
import traceback

PLUGIN_DIR = r"C:\Users\EarthBugs\Documents\current_working\20260901_blender_select_references"
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

# 模块导入陷阱：sys.modules 可能已有 addon 版（路径不同、代码更旧）。先 pop
# 并用其自身 unregister 按它自己的账本清掉菜单项，再从工作区导入最新代码。
_old_sr = sys.modules.pop("select_references", None)
if _old_sr is not None:
    try:
        _old_sr.unregister()
    except Exception:
        pass

import select_references as _sr

# 防御性注销后幂等注册一次（register 内部账本去重，重复调用无代价），
# 保证端到端 bpy.ops 测试与会话内 GUI 冒烟可用
try:
    _sr.unregister()
except Exception:
    pass
_sr.register()
sr = _sr

_results = []
_errors = []


def _ser(v):
    try:
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, (set, frozenset)):
            return sorted(str(getattr(x, "name", x)) for x in v)
        if isinstance(v, (list, tuple)):
            return [_ser(x) for x in v]
        if isinstance(v, dict):
            return {str(k): _ser(x) for k, x in v.items()}
        return str(v)
    except Exception:
        return "<unserializable>"


def check(name, expected, actual, note=""):
    try:
        ok = expected == actual
    except Exception:
        ok = False
    _results.append({"name": name, "expected": _ser(expected), "actual": _ser(actual),
                     "pass": bool(ok), "note": note})
    return ok


# ============================================================================
# 0. 用户状态快照 + 预清理历史遗留 SR_TEST_* 数据
# ============================================================================
_env = {
    "blender_version": ".".join(str(x) for x in bpy.app.version),
    "current_file": bpy.data.filepath or "<unsaved>",
    "scene": bpy.context.scene.name,
}
user_selected = [o.name for o in bpy.context.view_layer.objects if o.select_get()]
user_active = bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None


def _find_outliner():
    """定位会话内第一个 Outliner 区域：(window, area, region, space) 或 None。"""
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                if a.type == "OUTLINER":
                    region = next((r for r in a.regions if r.type == "WINDOW"), None)
                    return w, a, region, a.spaces.active
    except Exception:
        pass
    return None


_ow = _find_outliner()
_outliner_ok = (_ow is not None and _ow[2] is not None
                and getattr(_ow[3], "display_mode", None) == "LIBRARIES")
_env["outliner_libraries_available"] = _outliner_ok


def _read_outliner_sel():
    """经窗口扫描 override 读取大纲当前选中的 ID 名字列表（去重排序）。"""
    w, a, region, space = _ow
    with bpy.context.temp_override(window=w, screen=w.screen, area=a,
                                   region=region, space_data=space):
        return sorted({i.name for i in bpy.context.selected_ids})


def _deselect_outliner():
    w, a, region, space = _ow
    with bpy.context.temp_override(window=w, screen=w.screen, area=a,
                                   region=region, space_data=space):
        bpy.ops.outliner.select_all(action='DESELECT')


def _clean_leftovers():
    """移除一切 SR_TEST_ 前缀的历史遗留数据。

    注意 Curves（新 hair/几何节点曲线）数据块在 bpy.data.hair_curves，
    不在 bpy.data.curves（实测），两处都要清。
    """
    removed = {"objects": 0, "collections": 0, "node_groups": 0, "materials": 0,
               "images": 0, "meshes": 0, "lights": 0, "cameras": 0,
               "curves": 0, "hair_curves": 0, "worlds": 0, "scenes": 0}
    for o in list(bpy.data.objects):
        if o.name.startswith("SR_TEST_"):
            bpy.data.objects.remove(o, do_unlink=True)
            removed["objects"] += 1
    for c in list(bpy.data.collections):
        if c.name.startswith("SR_TEST_"):
            bpy.data.collections.remove(c, do_unlink=True)
            removed["collections"] += 1
    for ng in list(bpy.data.node_groups):
        if ng.name.startswith("SR_TEST_"):
            bpy.data.node_groups.remove(ng, do_unlink=True)
            removed["node_groups"] += 1
    for m in list(bpy.data.materials):
        if m.name.startswith("SR_TEST_"):
            bpy.data.materials.remove(m, do_unlink=True)
            removed["materials"] += 1
    for i in list(bpy.data.images):
        if i.name.startswith("SR_TEST_") and not i.users:
            bpy.data.images.remove(i)
            removed["images"] += 1
    for me in list(bpy.data.meshes):
        if me.name.startswith("SR_TEST_") and not me.users:
            bpy.data.meshes.remove(me)
            removed["meshes"] += 1
    for li in list(bpy.data.lights):
        if li.name.startswith("SR_TEST_") and not li.users:
            bpy.data.lights.remove(li)
            removed["lights"] += 1
    for ca in list(bpy.data.cameras):
        if ca.name.startswith("SR_TEST_") and not ca.users:
            bpy.data.cameras.remove(ca)
            removed["cameras"] += 1
    for cu in list(bpy.data.curves):
        if cu.name.startswith("SR_TEST_") and not cu.users:
            bpy.data.curves.remove(cu)
            removed["curves"] += 1
    for hc in list(getattr(bpy.data, "hair_curves", [])):
        if hc.name.startswith("SR_TEST_") and not hc.users:
            bpy.data.hair_curves.remove(hc)
            removed["hair_curves"] += 1
    for wd in list(bpy.data.worlds):
        if wd.name.startswith("SR_TEST_") and not wd.users:
            bpy.data.worlds.remove(wd)
            removed["worlds"] += 1
    for sc in list(bpy.data.scenes):
        if sc.name.startswith("SR_TEST_"):
            bpy.data.scenes.remove(sc)
            removed["scenes"] += 1
    return removed


try:
    pre_clean = _clean_leftovers()
except Exception as exc:
    pre_clean = {}
    _errors.append("预清理异常: {}\n{}".format(exc, traceback.format_exc()))


def _restore_user_state():
    vl = bpy.context.view_layer
    for o in vl.objects:
        try:
            o.select_set(o.name in set(user_selected))
        except Exception:
            pass
    if user_active and user_active in vl.objects:
        vl.objects.active = vl.objects[user_active]


# ============================================================================
# 1. 构造夹具（全部 SR_TEST_ 前缀；期望值动态取实际对象名）
# ============================================================================
scene_coll = bpy.context.scene.collection

mesh_shared = bpy.data.meshes.new("SR_TEST_Mesh")
obj_a = bpy.data.objects.new("SR_TEST_ObjA", mesh_shared)
obj_b = bpy.data.objects.new("SR_TEST_ObjB", mesh_shared)   # linked duplicate

mesh_ctrl = bpy.data.meshes.new("SR_TEST_CtrlMesh")
obj_ctrl = bpy.data.objects.new("SR_TEST_CtrlObj", mesh_ctrl)

light_data = bpy.data.lights.new("SR_TEST_LightData", type='POINT')
obj_light = bpy.data.objects.new("SR_TEST_LightObj", light_data)
cam_data = bpy.data.cameras.new("SR_TEST_CamData")
obj_cam = bpy.data.objects.new("SR_TEST_CamObj", cam_data)

img = bpy.data.images.new("SR_TEST_Image", 16, 16)
mat_a = bpy.data.materials.new("SR_TEST_MatA")       # 直连 Image Texture
mat_a.use_nodes = True
tex_a = mat_a.node_tree.nodes.new("ShaderNodeTexImage")
tex_a.image = img
_out_a = mat_a.node_tree.nodes.get("Material Output")
if _out_a:
    mat_a.node_tree.links.new(tex_a.outputs["Color"], _out_a.inputs["Surface"])

# 材质 B：经 ShaderNodeGroup 嵌套引用同一 Image（扫描不需要连线/接口）
grp_tree = bpy.data.node_groups.new("SR_TEST_ShaderGroup", 'ShaderNodeTree')
grp_tex = grp_tree.nodes.new("ShaderNodeTexImage")
grp_tex.image = img
mat_b = bpy.data.materials.new("SR_TEST_MatB")
mat_b.use_nodes = True
grp_node = mat_b.node_tree.nodes.new("ShaderNodeGroup")
grp_node.node_tree = grp_tree

# World 引用同一 Image（按设计仅 INFO，不进结果集）
world = bpy.data.worlds.new("SR_TEST_World")
world.use_nodes = True
env_tex = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
env_tex.image = img

gn_child = bpy.data.node_groups.new("SR_TEST_GN_Child", 'GeometryNodeTree')
gn_parent = bpy.data.node_groups.new("SR_TEST_GN_Parent", 'GeometryNodeTree')
gn_ref = gn_parent.nodes.new("GeometryNodeGroup")
gn_ref.node_tree = gn_child

mesh_mat = bpy.data.meshes.new("SR_TEST_MatMesh")
obj_matc = bpy.data.objects.new("SR_TEST_MatObj", mesh_mat)
mesh_gn = bpy.data.meshes.new("SR_TEST_GNMesh")
obj_gn = bpy.data.objects.new("SR_TEST_GNObj", mesh_gn)
mesh_hid = bpy.data.meshes.new("SR_TEST_HidMesh")
obj_hidden = bpy.data.objects.new("SR_TEST_HiddenObj", mesh_hid)

for o in (obj_a, obj_b, obj_ctrl, obj_light, obj_cam, obj_matc, obj_gn, obj_hidden):
    scene_coll.objects.link(o)

# 材质引用：mat_a 挂在共用 Mesh 的 DATA 槽上（v3：引用者是 Mesh 数据块本身，
#            不再是两个 linked duplicate 对象）；
#            mat_b 同时走 ObjA 的 OBJECT 槽（对象级覆盖）与 MatMesh 的 DATA 槽
obj_a.data.materials.append(mat_a)
obj_a.data.materials.append(None)          # 追加 None 生成空槽
slot = obj_a.material_slots[1]
slot.link = 'OBJECT'
slot.material = mat_b
obj_matc.data.materials.append(mat_b)

obj_empty = bpy.data.objects.new("SR_TEST_ImageEmpty", None)
obj_empty.empty_display_type = 'IMAGE'
obj_empty.data = img
scene_coll.objects.link(obj_empty)

_bg_ok = True
try:
    bg = cam_data.background_images.new()
    bg.image = img
except Exception as exc:
    _bg_ok = False
    _errors.append("camera.background_images.new 失败: {!r}".format(exc))

mod = obj_gn.modifiers.new(name="SR_TEST_GNMod", type='NODES')
mod.node_group = gn_parent

obj_hidden.hide_set(True)

excl_coll = bpy.data.collections.new("SR_TEST_ExclColl")
scene_coll.children.link(excl_coll)
mesh_excl = bpy.data.meshes.new("SR_TEST_ExclMesh")
obj_excl = bpy.data.objects.new("SR_TEST_ExclObj", mesh_excl)
excl_coll.objects.link(obj_excl)


def _find_lc(lc, name):
    if lc.collection.name == name:
        return lc
    for child in lc.children:
        r = _find_lc(child, name)
        if r is not None:
            return r
    return None


try:
    lc_excl = _find_lc(bpy.context.view_layer.layer_collection, "SR_TEST_ExclColl")
    lc_excl.exclude = True
except Exception as exc:
    lc_excl = None
    _errors.append("设置 exclude 失败: {!r}".format(exc))

# Scene 夹具：scene.camera 是 Object 指针（不是 Camera 数据块【实测】），
# _scenes_using_camera 按 scene.camera.data is cam 判定（仅 INFO 路径）
scene_fx = bpy.data.scenes.new("SR_TEST_Scene")
scene_fx.camera = obj_cam

# ---- 曲线类夹具 -----------------------------------------------------------
curve_data = bpy.data.curves.new("SR_TEST_Curve", 'CURVE')
curve_data.splines.new('BEZIER')
obj_curve = bpy.data.objects.new("SR_TEST_CurveObj", curve_data)
scene_coll.objects.link(obj_curve)

# Curves：只能经 bpy.ops.object.curves_empty_hair_add() 创建（前置：活跃
# mesh 对象）；数据块落在 bpy.data.hair_curves。
# 【实测副作用，2026-09-03】该 op 会拉入整套内置毛发/仿真节点组（数十个
# XPBD/Hair 系 GeometryNodeTree），并可能在毛发附着网格上挂 NODES 修改器
# （曾污染用户 Cube，被挂 "Capture Rest Geometry" 修改器）。创建前快照，
# 清理阶段按快照还原，杜绝污染用户场景。
_ng_before_hair = {ng.name for ng in bpy.data.node_groups}
_mods_before_hair = {o.name: {m.name for m in o.modifiers}
                     for o in bpy.data.objects
                     if not o.name.startswith("SR_TEST_")}
curves_obj = None
curves_data = None
try:
    _before_curves = {o.name for o in bpy.data.objects if o.type == 'CURVES'}
    with bpy.context.temp_override(active_object=obj_ctrl,
                                   selected_editable_objects=[obj_ctrl],
                                   selected_objects=[obj_ctrl]):
        bpy.ops.object.curves_empty_hair_add()
    _new_curves = sorted({o.name for o in bpy.data.objects if o.type == 'CURVES'}
                         - _before_curves)
    if _new_curves:
        curves_obj = bpy.data.objects[_new_curves[0]]
        curves_obj.name = "SR_TEST_CurvesObj"
        curves_data = curves_obj.data
        curves_data.name = "SR_TEST_CurvesData"
    else:
        _errors.append("curves_empty_hair_add 未产生新 CURVES 对象")
except Exception as exc:
    _errors.append("Curves 夹具创建失败: {!r}\n{}".format(exc, traceback.format_exc()))

# 动态名字（预清理后不应再有后缀，但不硬编码以防万一）
A, B, CTRL = obj_a.name, obj_b.name, obj_ctrl.name
LIGHT, CAM = obj_light.name, obj_cam.name
MATC, EMPTY, GN = obj_matc.name, obj_empty.name, obj_gn.name
HID, EXCL = obj_hidden.name, obj_excl.name
CURVE_OBJ = obj_curve.name
CURVES_OBJ = curves_obj.name if curves_obj is not None else None

# ============================================================================
# 2. 断言：classify_selection（与 v1 一致，零改动回归）
# ============================================================================
vl = bpy.context.view_layer

ok, reason, family, typed = sr.classify_selection([mesh_shared])
check("classify: 单 Mesh 通过", (True, "", bpy.types.Mesh), (ok, reason, family))

ok, reason, family, typed = sr.classify_selection([mesh_shared, mat_a])
check("classify: Mesh+Material 混合拒绝", (False, "mixed"), (ok, reason))

ok, reason, family, typed = sr.classify_selection([obj_a])
check("classify: 含 Object 拒绝", (False, "unsupported/mixed"), (ok, reason))

ok, reason, family, typed = sr.classify_selection([])
check("classify: 空列表拒绝", (False, "no selection"), (ok, reason))

ok, reason, family, typed = sr.classify_selection([light_data])
check("classify: PointLight 判为 Light 家族", (True, bpy.types.Light), (ok, family))

# ============================================================================
# 3. 断言：find_direct_referencers（v3 一跳语义，objects/ids 分类）
# ============================================================================
r = sr.find_direct_referencers(mesh_shared)
check("v3: Mesh → objects 两个 Object", {A, B}, {o.name for o in r["objects"]})
check("v3: Mesh → ids 为空", set(), {i.name for i in r["ids"]})

r = sr.find_direct_referencers(cam_data)
check("v3: Camera → objects 其 Object", {CAM}, {o.name for o in r["objects"]})
check("v3: Camera → ids 为空", set(), {i.name for i in r["ids"]})
check("v3: Camera → Scene 仅 INFO 探测", [scene_fx.name],
      [s.name for s in sr._scenes_using_camera(cam_data)])

r = sr.find_direct_referencers(light_data)
check("v3: Light → objects 其 Object", {LIGHT}, {o.name for o in r["objects"]})

# 关键新语义：DATA 槽材质的引用者是 Mesh 数据块本身，不是宿主对象
r = sr.find_direct_referencers(mat_a)
check("v3: Material(DATA 槽) → ids 含 Mesh 数据块", {mesh_shared.name},
      {i.name for i in r["ids"]})
check("v3: Material(DATA 槽) → objects 为空（不再选宿主对象）", set(),
      {o.name for o in r["objects"]})

# OBJECT 槽 + DATA 槽并存：对象与数据块两路分流取并集
r = sr.find_direct_referencers(mat_b)
check("v3: Material(OBJECT+DATA) → objects 含 OBJECT 槽对象", {A},
      {o.name for o in r["objects"]})
check("v3: Material(OBJECT+DATA) → ids 含 DATA 槽 Mesh", {mesh_mat.name},
      {i.name for i in r["ids"]})

# Image：材质直连 ∪ 嵌套组 → Material 数据块；相机背景图 → Camera 数据块；
# Image Empty → Object；World 仅报告
expected_img_ids = {mat_a.name, mat_b.name}
if _bg_ok:
    expected_img_ids.add(cam_data.name)
r = sr.find_direct_referencers(img)
check("v3: Image → ids 材质∪嵌套组∪相机数据块", expected_img_ids,
      {i.name for i in r["ids"]},
      note="相机背景图构造" + ("成功" if _bg_ok else "失败，已从期望剔除"))
check("v3: Image → objects 仅 Image Empty", {EMPTY}, {o.name for o in r["objects"]})
check("v3: Image → World 仅 INFO 探测（不进结果集）", [world.name],
      [w.name for w in sr._worlds_using_image(img)])
check("v3: Image → ids 不含 World", False,
      world.name in {i.name for i in r["ids"]})

# GN 一跳：子组 → 父组数据块（不再递归到对象）；父组 → 挂修改器对象
r = sr.find_direct_referencers(gn_parent)
check("v3: GN 父组 → objects 挂修改器对象", {GN}, {o.name for o in r["objects"]})
check("v3: GN 父组 → ids 为空", set(), {i.name for i in r["ids"]})
r = sr.find_direct_referencers(gn_child)
check("v3: GN 子组 → ids 父组数据块（一跳）", {gn_parent.name},
      {i.name for i in r["ids"]})
check("v3: GN 子组 → objects 为空（不再递归到对象）", set(),
      {o.name for o in r["objects"]})

r = sr.find_direct_referencers(mesh_ctrl)
check("v3: 无关 Mesh 只含对照对象", {CTRL}, {o.name for o in r["objects"]})

# 多目标并集
r = sr.find_direct_referencers_many([mesh_shared, cam_data])
check("v3: many 并集 objects", {A, B, CAM}, {o.name for o in r["objects"]})
r = sr.find_direct_referencers_many([mat_a, mat_b])
check("v3: many 并集 objects(OBJECT 槽)", {A}, {o.name for o in r["objects"]})
check("v3: many 并集 ids(DATA 槽)", {mesh_shared.name, mesh_mat.name},
      {i.name for i in r["ids"]})

# ---- 曲线族 ---------------------------------------------------------------
check("get_family: legacy Curve 判为 Curve 家族", bpy.types.Curve,
      sr.get_family(curve_data))
r = sr.find_direct_referencers(curve_data)
check("v3: legacy Curve → objects 其 Object", {CURVE_OBJ},
      {o.name for o in r["objects"]})

if curves_data is not None:
    check("get_family: Curves 判为 Curves 家族", bpy.types.Curves,
          sr.get_family(curves_data))
    check("夹具: Curves 数据块在 bpy.data.hair_curves", True,
          curves_data.name in bpy.data.hair_curves)
    r = sr.find_direct_referencers(curves_data)
    check("v3: Curves → objects 其 Object", {CURVES_OBJ},
          {o.name for o in r["objects"]})
else:
    check("v3: Curves → objects 其 Object", "fixture created", "fixture missing",
          note="Curves 夹具创建失败，见 env_errors")

ok, reason, family, typed = sr.classify_selection([curve_data])
check("classify: 单 legacy Curve 通过", (True, bpy.types.Curve), (ok, family))
if curves_data is not None:
    ok, reason, family, typed = sr.classify_selection([curves_data])
    check("classify: 单 Curves 通过", (True, bpy.types.Curves), (ok, family))
    ok, reason, family, typed = sr.classify_selection([curve_data, curves_data])
    check("classify: Curve+Curves 混选拒绝（不同家族根类）", (False, "mixed"),
          (ok, reason))
ok, reason, family, typed = sr.classify_selection([curve_data, mesh_shared])
check("classify: Curve+Mesh 混选拒绝", (False, "mixed"), (ok, reason))

# ============================================================================
# 4. 断言：execute_selection（正常/隐藏/被排除，v1 逻辑零改动回归）
# ============================================================================
targets = {obj_a, obj_b, obj_hidden, obj_excl}
try:
    selected, hidden, excluded = sr.execute_selection(bpy.context, targets)
    check("执行: 选中集合（排序、去重）", sorted([A, B]), [o.name for o in selected])
    check("执行: active 为排序后首个", A,
          vl.objects.active.name if vl.objects.active else None)
    check("执行: 隐藏对象跳过", [HID], [o.name for o in hidden])
    check("执行: 被排除集合对象跳过", [EXCL], [o.name for o in excluded])
    check("执行: 对照对象未被选中", False, obj_ctrl.select_get())
except Exception as exc:
    _errors.append("execute_selection 异常: {}\n{}".format(exc, traceback.format_exc()))
_restore_user_state()

# ============================================================================
# 5. 断言：select_datablock_rows 同步直调（单目标 + 多目标跨类型——
#    probe13 实测多目标可行：折叠分节已选行只是不可见、选中持久，
#    restore 后 show_one_level 展开即恢复，probe8/E1"丢选"系误判）
# ============================================================================
if not _outliner_ok:
    check("行高亮: 机制可用性", "available", "skipped",
          note="无 LIBRARIES 模式 Outliner 区域（headless），行高亮用例跳过")
else:
    try:
        # 5.1 单目标
        rows_ok, rows_failed, extras = sr.select_datablock_rows(
            bpy.context, {mesh_shared})
        check("行高亮(单目标): 目标命中", [mesh_shared.name],
              [i.name for i in rows_ok])
        check("行高亮(单目标): 无失败目标", [], [i.name for i in rows_failed])
        check("行高亮(单目标): 无附带选中", [], [i.name for i in extras])
        check("行高亮(单目标): 大纲 selected_ids 即目标", [mesh_shared.name],
              _read_outliner_sel())

        # 5.2 多目标跨类型（Material×2 + Camera，逐名过滤累加）
        _multi = sorted([mat_a.name, mat_b.name, cam_data.name])
        rows_ok, rows_failed, extras = sr.select_datablock_rows(
            bpy.context, {mat_a, mat_b, cam_data})
        check("行高亮(多目标): 全部命中", _multi,
              sorted(i.name for i in rows_ok))
        check("行高亮(多目标): 无失败目标", [], [i.name for i in rows_failed])
        check("行高亮(多目标): 无附带选中", [], [i.name for i in extras])
        check("行高亮(多目标): 大纲 selected_ids 即三目标", _multi,
              _read_outliner_sel())
        _deselect_outliner()
    except Exception as exc:
        _errors.append("select_datablock_rows 异常: {}\n{}".format(
            exc, traceback.format_exc()))

# ============================================================================
# 6. T19 菜单注册幂等（须在 Blender 内执行；置于 e2e 之前，避免 reload
#    重置模块级异步状态）
# ============================================================================
_t19_module = sys.modules["select_references"]
_t19_menu = bpy.types.OUTLINER_MT_context_menu
try:
    _t19_module.register()
except Exception:
    pass


def _sr_stale_draw_1(self, context):
    pass


def _sr_stale_draw_2(self, context):
    pass


_t19_menu.append(_sr_stale_draw_1)
_t19_menu.append(_sr_stale_draw_2)
_t19_module._APPENDED_DRAW_FNS.extend([_sr_stale_draw_1, _sr_stale_draw_2])
check("T19: 脏状态构造（账本 = 1 正常 + 2 陈旧）", 3,
      len(_t19_module._APPENDED_DRAW_FNS))

_t19_rounds_ok = True
for _i in range(3):
    _t19_module = importlib.reload(_t19_module)
    for _old in list(_t19_module._APPENDED_DRAW_FNS):
        try:
            _t19_menu.remove(_old)
        except Exception as exc:
            _t19_rounds_ok = False
            _errors.append("T19 第 {} 轮 remove 异常: {!r}".format(_i + 1, exc))
    _t19_module.register()
check("T19: 三轮逐个 remove 无异常", True, _t19_rounds_ok)
check("T19: 三轮 reload+register 后账本长度为 1", 1,
      len(_t19_module._APPENDED_DRAW_FNS))
check("T19: 账本唯一元素 is 当前模块 _draw_menu", True,
      bool(_t19_module._APPENDED_DRAW_FNS)
      and _t19_module._APPENDED_DRAW_FNS[0] is _t19_module._draw_menu)

_t19_module.unregister()
check("T19: unregister 后账本为空", 0, len(_t19_module._APPENDED_DRAW_FNS))

_t19_reg_exc = None
try:
    _t19_module.register()
    _t19_module.register()
except Exception as exc:
    _t19_reg_exc = exc
    _errors.append("T19 连续 register 外抛异常: {!r}".format(exc))
check("T19: 连续两次 register 无外抛（ValueError 被定点防御）", None, _t19_reg_exc)
check("T19: 连续两次 register 后账本仍为 1", 1,
      len(_t19_module._APPENDED_DRAW_FNS))
# 注册状态判据：hasattr(bpy.types, ...) 在 5.2 恒 False（probe_t19 实测），
# 改用 ValueError 探针——同 py 类对象重复 register 抛 ValueError 即证明已注册
_t19_reg_probe = None
try:
    bpy.utils.register_class(_t19_module.SELECT_REFERENCING_OT_select_references)
    _t19_reg_probe = "not-registered"
except ValueError:
    _t19_reg_probe = "registered"
check("T19: operator 类处于已注册状态", "registered", _t19_reg_probe,
      note="5.2 不能用 hasattr(bpy.types,...) 判定注册状态（probe_t19 实测）")
# 后续端到端/清理/重注册统一使用最新重载的模块
sr = _t19_module

# ============================================================================
# 7. Operator 端到端（全 outliner 上下文 temp_override，poll 真实通过，
#    全同步；report 经 monkeypatch 类方法捕获用于 INFO 分支断言）
# ============================================================================
import types
_reports = []
_op_cls = sr.SELECT_REFERENCING_OT_select_references


def _capture_report_bound(typ, msg):
    _reports.append((tuple(sorted(typ)), str(msg)))


def _safe(fn):
    try:
        fn()
    except Exception as exc:
        _errors.append("清理异常: {!r}".format(exc))


if not _outliner_ok:
    check("端到端: operator 执行", "FINISHED", "skipped",
          note="无 LIBRARIES 模式 Outliner 区域（headless），端到端跳过")
else:
    w, area, region, space = _ow
    _orig_filter_text = space.filter_text
    _orig_use_id_type = space.use_filter_id_type

    def _e2e(sel_ids):
        """真实选中输入数据块行后直调 execute（模拟用户在大纲点选后触发）。

        不用 temp_override 注入 selected_ids：注入值会穿透嵌套 override，
        污染 execute 内部 select_datablock_rows 对 bpy.context.selected_ids
        的结果判定（实测：rows_ok 被误判为空）。select_datablock_rows 真实
        高亮输入行后，selected_ids 为 RNA 原生值，与真实用户操作完全一致。
        execute 只用到 self.report，以携带捕获闭包的假 self 调用（bpy 类型
        禁止 _op_cls() 实例化，metaclass 使类级 monkeypatch report 不生效）。
        """
        del _reports[:]
        in_ok, in_failed, _extras = sr.select_datablock_rows(
            bpy.context, set(sel_ids))
        if sorted(i.name for i in in_ok) != sorted(i.name for i in sel_ids):
            _errors.append("端到端输入行选中失败: ok={} failed={}".format(
                [i.name for i in in_ok], [i.name for i in in_failed]))
        op = types.SimpleNamespace(report=_capture_report_bound)
        with bpy.context.temp_override(window=w, screen=w.screen, area=area,
                                       region=region, space_data=space):
            return _op_cls.execute(op, bpy.context)

    try:
        # poll 真实验证：真实选中 mat_a 行（等价用户在大纲点选）后判定
        sr.select_datablock_rows(bpy.context, {mat_a})
        with bpy.context.temp_override(window=w, screen=w.screen, area=area,
                                       region=region, space_data=space):
            check("端到端: poll 通过（LIBRARIES 大纲选中同族数据块）", True,
                  _op_cls.poll(bpy.context))

        # 7.1 验收例 2：DATA 槽材质（单数据块引用者）→ 行高亮 Mesh 数据块,
        #     视口不误选
        ret = _e2e([mat_a])
        check("端到端: mat_a 执行返回 FINISHED", True, 'FINISHED' in ret)
        check("端到端: mat_a 无对象引用者 → 视口不误选", [],
              sorted(o.name for o in vl.objects
                     if o.select_get() and o.name.startswith("SR_TEST_")))
        check("端到端: mat_a → 大纲行选中即 Mesh 数据块", [mesh_shared.name],
              _read_outliner_sel())
        check("端到端: mat_a report 含已高亮信息", True,
              any(sr._t("highlighted").split("{}")[0] in m
                  and mesh_shared.name in m
                  for _, m in _reports),
              note="captured={}".format([m for _, m in _reports]))

        # 7.2 链式上溯：用上一步结果（Mesh 数据块）再触发 → 选中两个对象
        ret = _e2e([mesh_shared])
        check("链式: mesh_shared 执行返回 FINISHED", True, 'FINISHED' in ret)
        check("链式: mesh_shared → 视口选中两个引用对象", sorted([A, B]),
              sorted(o.name for o in vl.objects
                     if o.select_get() and o.name.startswith("SR_TEST_")))

        # 7.3 验收例 3：OBJECT+DATA 槽材质 → 视口对象 obj_a + 行高亮 MatMesh
        ret = _e2e([mat_b])
        check("端到端: mat_b 执行返回 FINISHED", True, 'FINISHED' in ret)
        check("端到端: mat_b → 视口选中 OBJECT 槽对象", [A],
              sorted(o.name for o in vl.objects
                     if o.select_get() and o.name.startswith("SR_TEST_")))
        check("端到端: mat_b → 大纲行选中即 DATA 槽 Mesh", [mesh_mat.name],
              _read_outliner_sel())

        # 7.4 验收例 1：图像 → 视口选中 Empty（对象部分）+ 大纲三数据块
        #     行高亮（多目标逐名过滤累加，probe13 实测可行）
        _img_rows = sorted(expected_img_ids)
        ret = _e2e([img])
        check("端到端: img 执行返回 FINISHED", True, 'FINISHED' in ret)
        check("端到端: img → 视口选中 Image Empty", [EMPTY],
              sorted(o.name for o in vl.objects
                     if o.select_get() and o.name.startswith("SR_TEST_")))
        check("端到端: img 结果不含无关 Cube 系对象", True,
              not any(o.select_get() for o in (obj_matc, obj_gn, obj_ctrl)))
        check("端到端: img → 大纲行选中即三个引用数据块", _img_rows,
              _read_outliner_sel())
        check("端到端: img report 含已高亮信息", True,
              any(sr._t("highlighted").split("{}")[0] in m
                  and all(n in m for n in _img_rows) for _, m in _reports),
              note="captured={}".format([m for _, m in _reports]))
        check("端到端: img → World 仅 INFO 提示", True,
              any("World" in m and world.name in m for _, m in _reports))
        check("端到端: 过滤器设置已还原", (_orig_filter_text, _orig_use_id_type),
              (space.filter_text, space.use_filter_id_type))
    except Exception as exc:
        _errors.append("端到端异常: {}\n{}".format(exc, traceback.format_exc()))
    _restore_user_state()

# ---- v1.3.0 双语机制断言（不强依赖会话语言，验证机制本身）------------------
check("i18n: _lang 与偏好语言一致", True,
      (bpy.context.preferences.view.language or "").startswith("zh")
      == (sr._lang() == "zh"))
check("i18n: 中英文案表键集合一致", set(sr._STRINGS["zh"]),
      set(sr._STRINGS["en"]))
check("i18n: menu_label 中英不同词", False,
      sr._STRINGS["zh"]["menu_label"] == sr._STRINGS["en"]["menu_label"])

# ============================================================================
# 8. 清理夹具 → T15 残留验证 → 重注册（供会话内 GUI 冒烟）→ 恢复用户状态
# ============================================================================
for o in (obj_a, obj_b, obj_ctrl, obj_light, obj_cam, obj_matc, obj_gn,
          obj_hidden, obj_empty, obj_excl, obj_curve):
    _safe(lambda o=o: bpy.data.objects.remove(o, do_unlink=True))
if curves_obj is not None:
    _safe(lambda: bpy.data.objects.remove(curves_obj, do_unlink=True))
if lc_excl is not None:
    _safe(lambda: setattr(lc_excl, "exclude", False))
_safe(lambda: bpy.data.collections.remove(excl_coll, do_unlink=True))
for m in (mat_a, mat_b):
    _safe(lambda m=m: bpy.data.materials.remove(m, do_unlink=True))
for ng in (gn_parent, gn_child, grp_tree):
    _safe(lambda n=ng: bpy.data.node_groups.remove(n, do_unlink=True))
_safe(lambda: bpy.data.images.remove(img, do_unlink=True))
for me in (mesh_shared, mesh_ctrl, mesh_mat, mesh_gn, mesh_hid, mesh_excl):
    _safe(lambda m=me: bpy.data.meshes.remove(m, do_unlink=True))
_safe(lambda: bpy.data.lights.remove(light_data, do_unlink=True))
_safe(lambda: bpy.data.cameras.remove(cam_data, do_unlink=True))
_safe(lambda: bpy.data.curves.remove(curve_data))
if curves_data is not None:
    # Curves 数据块：bpy.data.curves.remove 会抛 TypeError，必须 batch_remove
    _safe(lambda: bpy.data.batch_remove(ids=[curves_data]))
_safe(lambda: bpy.data.worlds.remove(world, do_unlink=True))
_safe(lambda: bpy.data.scenes.remove(scene_fx, do_unlink=True))
# curves_empty_hair_add 副作用还原（按创建前快照）：移除新增的节点组、
# 以及被挂到非夹具对象上的新增 NODES 修改器
for _ng in list(bpy.data.node_groups):
    if _ng.name not in _ng_before_hair and not _ng.name.startswith("SR_TEST_"):
        _safe(lambda n=_ng: bpy.data.node_groups.remove(n, do_unlink=True))
for _o in list(bpy.data.objects):
    if not _o.name.startswith("SR_TEST_"):
        _keep = _mods_before_hair.get(_o.name, set())
        for _m in list(_o.modifiers):
            if _m.type == 'NODES' and _m.name not in _keep:
                _safe(lambda o=_o, m=_m: o.modifiers.remove(m))
if _outliner_ok:
    try:
        _deselect_outliner()
    except Exception:
        pass

# 毛发 op 副作用残留验证：清理后不应存在快照之外的节点组，
# 非夹具对象上不应存在快照之外的 NODES 修改器
check("清理: 毛发 op 副作用无残留（节点组/修改器按快照还原）", (True, True),
      (all(ng.name.startswith("SR_TEST_") or ng.name in _ng_before_hair
           for ng in bpy.data.node_groups),
       all(all(m.type != 'NODES' or m.name in _mods_before_hair.get(o.name, set())
               for m in o.modifiers)
           for o in bpy.data.objects if not o.name.startswith("SR_TEST_"))))

# T15 残留验证：所有 SR_TEST_ 前缀数据应为 0
_residual = {}
for _cname in ("objects", "collections", "node_groups", "materials", "images",
               "meshes", "lights", "cameras", "curves", "hair_curves",
               "worlds", "scenes"):
    _coll = getattr(bpy.data, _cname, None)
    if _coll is not None:
        _residual[_cname] = sum(1 for _x in _coll
                                if _x.name.startswith("SR_TEST_"))
check("清理: 全部 SR_TEST_ 夹具无残留", {k: 0 for k in _residual}, _residual)

try:
    sr.register()
except Exception as exc:
    _errors.append("重新注册插件失败: {!r}".format(exc))
_restore_user_state()

# ============================================================================
# 9. 汇总（socket 协议要求：result 变量）
# ============================================================================
passed = sum(1 for r in _results if r["pass"])
failed = len(_results) - passed
result = {
    "status": "ok" if failed == 0 and not _errors else ("ok_with_env_errors" if failed == 0 else "has_failures"),
    "env": _env,
    "plugin_version": "{}.{}.{}".format(*sr.bl_info["version"]),
    "pre_clean_removed": pre_clean,
    "passed": passed,
    "failed": failed,
    "failures": [r for r in _results if not r["pass"]],
    "all_checks": _results,
    "env_errors": _errors,
}
print("[Select References TEST v4] PASS={} FAIL={} env_errors={}".format(
    passed, failed, len(_errors)))
