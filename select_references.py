# -*- coding: utf-8 -*-
"""Select References —— 在大纲（Outliner）"Blender File" 模式下反选直接引用者（一跳语义）。

在 Blender 5.2 的 Outliner "Blender File"（display_mode == 'LIBRARIES'）显示模式下，
选中一个或多个同类型的 ID 数据块（Camera / Image / Light / Material / Mesh /
GeometryNodeTree / Curve / Curves）后，经右键菜单 "Select References" 选中
**直接引用**这些数据块的对象或数据块——沿引用链向上游走一跳，引用者是什么就选
什么（v3 语义；v1 的"一律传播到终端 Object"语义已废止）。用户可连续触发逐级
上溯，本功能不自动多跳。

引用边规范（目标 ← 直接引用者 → 结果，详见 docs/design_v3.md §3）：
- Mesh / Camera / Light / Curve / Curves
                         -> obj.data is 目标 -> Object（同 v1）；
- Material               -> DATA 槽（目标 ∈ data.materials，遍历 bpy.data.meshes /
                            curves / hair_curves）-> 对应 Mesh/Curve/Curves 数据块；
                            OBJECT 槽（slot.link=='OBJECT' 且 slot.material is 目标）
                            -> 该 Object；两类引用者取并集；
- Image                  -> 材质节点树直连 ∪ ShaderNodeGroup 嵌套（按 owner 判定，
                            内嵌树同名陷阱见 tests/test_report.md Bug B）-> Material
                            数据块；相机背景图（camera.background_images）-> Camera
                            数据块；Image Empty（obj.data is img）-> Object；
                            World 引用 -> 仅 INFO 提示，不进结果集；
- GeometryNodeTree       -> NODES 修改器 node_group 直接引用 -> Object；
                            组节点直接嵌套引用 -> 父 GN 组数据块（一跳，不递归）；
- Camera                 -> scene.camera -> 仅 INFO 提示。

选择落地（docs/design_v3.md §4，探针实测见 tests/probe_outliner_select*.py）：
- Object 引用者：视口选中 + 大纲 Objects 行同步高亮（execute_selection，
  隐藏/被排除对象防护保留）；
- 非 Object 数据块引用者：大纲 Blender File 模式行高亮。selected_ids 只读、
  SpaceOutliner 无选择接口、无按 ID 选中的 op（均实测），唯一可行机制为
  use_filter_id_type + filter_id_type 限定类型分节 + 大小写敏感 filter_text
  + 泵一次重绘 + outliner.select_all（逐名过滤累加，多目标同为该机制），
  结束后还原过滤器并调 outliner.show_one_level(open=True) 展开类型分节——
  折叠分节中的已选行不可见且 selected_ids 只上报可见行（probe12 实测，
  早期"多目标丢选"结论的误判根因），展开后全部目标选中恢复显示。
  机制不可用（无 LIBRARIES 模式 Outliner 区域等）时回退为 INFO 逐个列出。
  过滤器为子串匹配，同类型且名字包含目标名的数据块会被一并高亮
  （无逐行反选 API，仅汇报）。

形态：legacy bl_info 单文件插件（Blender 5.2 仍支持 legacy add-on）。
菜单项 append 到 OUTLINER_MT_context_menu；可用性完全由 Operator.poll 决定
（poll 返回 False 时菜单项自动置灰：可见但不可点）。
注册幂等：以模块级"守卫账本"（_APPENDED_DRAW_FNS，globals 守卫跨 reload 存活）
记录已 append 的绘制函数，register 前清账移除历史条目，杜绝反复
reload+register 导致的右键菜单项重复（详见 docs/architecture_plan.md §10.1）。

设计原则：业务逻辑全部下沉为模块级纯函数（输入 bpy 数据、返回集合/元组，
不碰 operator、不 report），Operator.execute 只做薄包装——因此测试可以完全
绕过 poll 与 UI，经 temp_override(selected_ids=...) 直接调用纯函数或 execute。

无网络访问、无文件读写，单文件自包含。
"""

bl_info = {
    "name": "Select References",
    "author": "Select References Contributors",
    "version": (1, 3, 0),
    "blender": (5, 2, 0),
    "location": "Outliner > Blender File 模式 > 右键菜单",
    "description": "在大纲 Blender File 模式下，选中直接引用了所选数据块的对象或数据块（一跳）",
    "support": "COMMUNITY",
    "category": "Object",
}

import bpy
from bpy.types import (
    Camera,
    Curve,
    Curves,
    GeometryNodeTree,
    Image,
    Light,
    Material,
    Mesh,
    Object,
)

# ============================================================================
# 模块级常量
# ============================================================================

# 受支持 ID 数据块的家族根类（isinstance 判定专用）。
# 注意：Light 必须用家族根类匹配——点/聚/日/面光源的 RNA identifier 是
# 'PointLight' / 'SpotLight' 等（实测），用类型名字符串比较会误判为异类；
# GeometryNodeTree 与 ShaderNodeTree 等为平级子类，针对具体类判定互不误染。
# Curve（legacy 贝塞尔曲线，对象 type=='CURVE'）与 Curves（新 hair/几何节点
# 曲线，对象 type=='CURVES'）互不继承【实测：双方 __mro__ 互不包含，Curves
# 直接继承 ID】，必须各自独立列出，漏一个该类型 get_family 就返回 None。
_SUPPORTED_FAMILY_ROOTS = (Camera, Image, Light, Material, Mesh, GeometryNodeTree,
                           Curve, Curves)

# 着色器树内图像纹理节点的 bl_idname（材质 / World 节点树中的图像引用点）
_IMAGE_NODE_IDS = ("ShaderNodeTexImage", "ShaderNodeTexEnvironment")

# ============================================================================
# 双语文案（v1.3.0）：跟随 Blender 界面语言，仅中英两种
# ============================================================================
# - 运行时经 _t(key) 取词：每次调用实时读 preferences.view.language，
#   菜单文案与 report 无需重新启用插件即可跟随语言切换；
# - bl_label / bl_description 只能在 register_class 前定型（register 时取词，
#   之后改语言需重新启用插件才更新 tooltip——菜单与 report 不受影响）；
# - 语言判定：zh 开头（zh_CN/zh_TW/zh_HANS…）一律中文，其余（含偏好读取失败）
#   一律英文回退。
_STRINGS = {
    "zh": {
        "menu_label": "选中引用",
        "description": "选中直接引用了所选数据块的对象或数据块（一跳语义；支持"
                       " Camera / Image / Light / Material / Mesh /"
                       " GeometryNodeTree / Curve / Curves）",
        "reject_prefix": "Select References：{}，已取消",
        "reason_no_selection": "未选中任何数据块",
        "reason_unsupported": "选中项包含不支持的数据块类型（含 Object）",
        "reason_mixed": "选中项类型混杂",
        "scan_error": "扫描数据块 '{}' 时出错，已跳过：{}",
        "world_info": "World '{}' 也引用了图像 '{}'（World 不支持选中，仅提示）",
        "scene_camera_info": "Scene '{}' 的场景相机是 '{}'（Scene 不支持选中，仅提示）",
        "no_results": "没有找到直接引用所选数据块的对象或数据块",
        "selected_objects": "已选中 {} 个引用对象",
        "hidden_skipped": "{} 个对象因被隐藏而跳过：{}",
        "excluded_skipped": "{} 个对象位于被排除的集合中，无法选中：{}",
        "highlighted": "已在大纲高亮 {} 个引用数据块：{}",
        "extras": "附带高亮了 {} 个同名相关数据块：{}",
        "rows_failed": "以下引用数据块无法在大纲高亮（无 LIBRARIES 模式大纲区域"
                       "或机制不可用）：{}",
        "orphans": "以下引用数据块为无用户的孤儿数据，不入大纲树：{}",
        "execute_error": "Select References 执行失败：{}",
        "join_sep": "、",
    },
    "en": {
        "menu_label": "Select References",
        "description": "Select objects or datablocks that directly reference the"
                       " selection (one-hop semantics; supports Camera / Image /"
                       " Light / Material / Mesh / GeometryNodeTree / Curve /"
                       " Curves)",
        "reject_prefix": "Select References: {}, cancelled",
        "reason_no_selection": "nothing is selected",
        "reason_unsupported": "selection contains unsupported datablock types"
                              " (including Object)",
        "reason_mixed": "selection mixes datablock types",
        "scan_error": "Error scanning '{}', skipped: {}",
        "world_info": "World '{}' also references image '{}' (Worlds cannot be"
                      " selected; info only)",
        "scene_camera_info": "Scene '{}' uses '{}' as its scene camera (Scenes"
                             " cannot be selected; info only)",
        "no_results": "No objects or datablocks directly reference the selection",
        "selected_objects": "Selected {} referencing object(s)",
        "hidden_skipped": "{} object(s) skipped because hidden: {}",
        "excluded_skipped": "{} object(s) are in excluded collections and cannot"
                            " be selected: {}",
        "highlighted": "Highlighted {} referencing datablock(s) in the Outliner: {}",
        "extras": "Additionally highlighted {} similarly named datablock(s): {}",
        "rows_failed": "Could not highlight in the Outliner (no LIBRARIES-mode"
                       " Outliner area or mechanism unavailable): {}",
        "orphans": "These referencing datablocks are orphaned (zero users) and do"
                   " not appear in the Outliner: {}",
        "execute_error": "Select References failed: {}",
        "join_sep": ", ",
    },
}


def _lang() -> str:
    """跟随 Blender 界面语言：zh 开头 → "zh"，其余/读取失败 → "en"。"""
    try:
        lang = bpy.context.preferences.view.language or ""
    except Exception:
        lang = ""
    return "zh" if lang.startswith("zh") else "en"


def _t(key: str) -> str:
    """取当前语言文案；未知 key（理论上不会发生）回退英文表。"""
    table = _STRINGS[_lang()]
    return table.get(key, _STRINGS["en"].get(key, key))


# classify_selection 拒绝原因码 → 文案 key（execute 汇报用，poll 不产生文案）
_REJECT_REASON_KEY = {
    "no selection": "reason_no_selection",
    "unsupported/mixed": "reason_unsupported",
    "mixed": "reason_mixed",
}

# 大纲行高亮机制：数据块家族 → SpaceOutliner.filter_id_type 枚举值
# （探针实测枚举见 tests/probe_outliner_select5.py；扫描器只会产生这些类型的
# 数据块引用者：材质 DATA 槽的 Mesh/Curve/Curves、引用图像的 Material/Camera、
# GN 父组 NODETREE）
_ID_TYPE_FOR_FILTER = {
    Material: "MATERIAL",
    Mesh: "MESH",
    Camera: "CAMERA",
    Curve: "CURVE",
    Curves: "CURVES",
    GeometryNodeTree: "NODETREE",
    Image: "IMAGE",
}

# ============================================================================
# 类型判定（模块级纯函数，poll 与 execute 共用，单一判定源）
# ============================================================================


def get_family(id_obj) -> "type | None":
    """对单个 ID 判定其所属家族根类。

    规则（实测依据见 docs/research_report.md §3）：
    - 显式排除 bpy.types.Object：Object 也是 ID，且大纲 LIBRARIES 模式下选中
      Object 行会进入 selected_ids，必须拒绝，否则 Object 与数据块混选会被误判
      为"含支持类型"；
    - 仅认八个具体类：Camera / Image / Light / Material / Mesh / GeometryNodeTree /
      Curve / Curves；Light 用家族根类匹配（isinstance 对 PointLight/SpotLight/
      SunLight/AreaLight 均为 True，家族内部不区分点/聚/日/面）；Curve（legacy
      曲线）与 Curves（新 hair/几何节点曲线）互不继承，各自独立判定，二者混选
      由 classify_selection 判 mixed 拒绝；
    - 其余类型（Collection、World、ShaderNodeTree、Action 等）返回 None。

    :param id_obj: 任意 bpy 数据块（或 None）
    :return: 家族根类（八个具体类之一）；不支持则 None
    """
    if id_obj is None or isinstance(id_obj, Object):
        return None
    for root in _SUPPORTED_FAMILY_ROOTS:
        if isinstance(id_obj, root):
            return root
    return None


def classify_selection(ids: list) -> tuple:
    """校验选中列表：非空、全部为支持的八个具体类、且同一家族。

    poll 与 execute 共用本函数（单一判定源，避免两处逻辑漂移）。

    :param ids: selected_ids 序列（可为 None / 空 / 任意可迭代）
    :return: 四元组 (ok, reason, family, typed_ids)：
             - ok: 是否全部通过；
             - reason: 失败原因码（"no selection" / "unsupported/mixed" / "mixed"），
               成功时为 ""；
             - family: 成功时的家族根类，失败时 None；
             - typed_ids: 成功时的选中 ID 列表（原顺序），失败时 []。
    """
    if not ids:
        return False, "no selection", None, []
    family = None
    typed_ids = []
    for id_obj in ids:
        fam = get_family(id_obj)
        if fam is None:
            # 含 Object 或其他不支持类型（Collection/World/ShaderNodeTree 等）
            return False, "unsupported/mixed", None, []
        if family is None:
            family = fam
        elif fam is not family:
            # 类型混杂（如 Mesh + Material）
            return False, "mixed", None, []
        typed_ids.append(id_obj)
    return True, "", family, typed_ids


# ============================================================================
# 引用扫描（模块级纯函数，v3 一跳语义：直接引用者是什么就返回什么）
# ============================================================================


def _iter_all_objects():
    """全量对象薄封装：遍历 bpy.data.objects 而非 view_layer.objects。

    后者只含当前 View Layer 的对象，会漏掉其他 View Layer 的引用者（实测结论）。
    预留缓存挂点（Phase 1 不做缓存）。
    """
    return bpy.data.objects


def _objects_using_data(data) -> set:
    """Mesh / Camera / Light / Curve / Curves 共用扫描：obj.data 直接指向目标数据块的所有 Object。

    多用户 / linked duplicate（多个 Object 共享同一数据块）各自独立命中、
    逐一返回（实测 select_set 无联动，无需特殊处理）。
    Curve（legacy）与 Curves（新 hair/几何节点曲线）的 obj.data is target
    均成立【实测】，扫描遍历 bpy.data.objects，与 Curves 数据块存放于
    bpy.data.hair_curves 无关，直接复用本函数，无需任何特判。
    """
    return {obj for obj in _iter_all_objects() if obj.data is data}


def _ids_using_material(mat) -> tuple:
    """材质 mat 的直接引用者，按 DATA/OBJECT 槽分流，返回 (ids, objects)。

    - DATA 槽：目标 ∈ data.materials → 数据块本身是引用者（v3 选数据块而非
      宿主对象）。遍历 bpy.data.meshes / curves / hair_curves（后者是 Curves
      数据块的实际存放集合，bpy.data.curves 不含 Curves【实测】）；
    - OBJECT 槽：slot.link == 'OBJECT' 且 slot.material is mat → 对象级覆盖槽，
      引用者是该 Object【实测：OBJECT 覆盖只反映在 slot 上，data.materials
      不含该覆盖，与 DATA 槽判定互斥分流】。
    """
    ids = set()
    objects = set()
    for coll in (bpy.data.meshes, bpy.data.curves,
                 getattr(bpy.data, "hair_curves", ())):
        for data in coll:
            mats = getattr(data, "materials", None)
            if mats is None:
                continue
            if any(m is mat for m in mats):
                ids.add(data)
    for obj in _iter_all_objects():
        for slot in obj.material_slots:
            if slot.link == 'OBJECT' and slot.material is mat:
                objects.add(obj)
                break
    return ids, objects


def _tree_owner_uses_image(owner, img) -> bool:
    """判定 owner（材质或 World）的根节点树及其嵌套组中是否存在引用 img 的节点。

    身份模型（实测，见 tests/test_report.md）：
    - 材质/World 的内嵌节点树不在 bpy.data.node_groups 中，且所有内嵌树的
      name 都是 "Shader Nodetree"（跨 owner 重名，且 id_data 是树自身）——
      因此"树的身份"只在其所属 owner 上下文内才有意义：本函数按 owner 逐个
      判定，绝不做跨 owner 的树身份比较（否则同名内嵌树会互相污染，实测导致
      无关对象被误报为图像引用者）；
    - 嵌套子树必然是 bpy.data.node_groups 的成员（ShaderNodeGroup.node_tree
      只能指向组库中的树，内嵌树不可能被子组反向引用），组与组之间可能成环，
      visited 以 ("ng", 树名) 为键防环（bpy.data.node_groups 内 name 唯一，
      且 "ng" 前缀与根树隔离，避免根树名与组名同名的理论碰撞）。

    :param owner: 具有 use_nodes / node_tree 属性的数据块（Material 或 World）
    :param img: 目标 Image 数据块
    :return: 是否引用
    """
    if not getattr(owner, "use_nodes", False):
        return False
    tree = owner.node_tree
    if tree is None:
        return False
    for node in tree.nodes:
        if node.bl_idname in _IMAGE_NODE_IDS and node.image is img:
            return True
    visited = set()
    for node in tree.nodes:
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
            if _group_tree_has_image(node.node_tree, img, visited):
                return True
    return False


def _group_tree_has_image(tree, img, visited: set) -> bool:
    """递归判定组树 tree（bpy.data.node_groups 成员）及其嵌套组中，
    是否存在引用图像 img 的图像纹理节点。visited 以 ("ng", 树名) 为键防环。"""
    if tree is None:
        return False
    key = ("ng", tree.name)
    if key in visited:
        return False
    visited.add(key)
    for node in tree.nodes:
        if node.bl_idname in _IMAGE_NODE_IDS:
            if node.image is img:
                return True
        elif node.bl_idname == "ShaderNodeGroup" and node.node_tree is not None:
            if _group_tree_has_image(node.node_tree, img, visited):
                return True
    return False


def _materials_using_image(img) -> set:
    """根节点树（含 ShaderNodeGroup 嵌套组）引用图像 img 的 Material 数据块集合。

    逐材质按 owner 判定（_tree_owner_uses_image）：内嵌树只在自身材质上下文
    内判定，规避跨材质同名内嵌树误报（实测见 tests/test_report.md Bug B）。
    """
    return {m for m in bpy.data.materials if _tree_owner_uses_image(m, img)}


def _cameras_using_image(img) -> set:
    """背景图引用图像 img 的 Camera 数据块集合
    （camera.background_images，元素 CameraBackgroundImage.image【实测】）。"""
    result = set()
    for cam in bpy.data.cameras:
        for bg in cam.background_images:
            if bg.image is img:
                result.add(cam)
                break
    return result


def _objects_using_image_empty(img) -> set:
    """Image Empty 对象：obj.type == 'EMPTY' 且 empty_display_type == 'IMAGE'
    时 obj.data 即图像本身（实测，勿凭旧版本记忆写成 empty_display 之类）。"""
    return {obj for obj in _iter_all_objects()
            if obj.type == "EMPTY" and obj.empty_display_type == "IMAGE"
            and obj.data is img}


def _worlds_using_image(img) -> list:
    """单独探测引用图像 img 的 World 列表。

    World 被场景引用而非被 Object 引用，按设计只进 INFO 提示，不进结果集。
    """
    result = []
    for world in bpy.data.worlds:
        if _tree_owner_uses_image(world, img):
            result.append(world)
    return result


def _scenes_using_camera(cam) -> list:
    """场景相机使用 Camera 数据块 cam 的 Scene 列表（仅 INFO 提示，不进结果集）。

    注意 scene.camera 是 Object 指针而非 Camera 数据块【实测】，必须经
    scene.camera.data 比对，直接 s.camera is cam 永远不命中。
    """
    return [s for s in bpy.data.scenes
            if getattr(s.camera, "data", None) is cam]


def _gn_direct_referencers(tree) -> tuple:
    """几何节点树的直接引用者（一跳），返回 (objects, ids)。

    - objects：NODES 修改器的 node_group 直接是 tree 的对象【实测入口】；
    - ids：树内 GeometryNodeGroup 节点的 node_tree 直接是 tree 的父 GN 组
      （bpy.data.node_groups 成员，name 唯一；只走一跳，不再递归到对象——
      连续触发即可逐级上溯，与 v3 链路心智一致）。
    """
    objects = set()
    for obj in _iter_all_objects():
        for mod in obj.modifiers:
            if mod.type != "NODES":
                continue
            if getattr(mod, "node_group", None) is tree:
                objects.add(obj)
                break
    parents = set()
    for ng in bpy.data.node_groups:
        if ng is tree or not isinstance(ng, GeometryNodeTree):
            continue
        for node in ng.nodes:
            if node.bl_idname == "GeometryNodeGroup" and node.node_tree is tree:
                parents.add(ng)
                break
    return objects, parents


def find_direct_referencers(target_id) -> dict:
    """核心分发器（v3）：返回目标数据块的直接引用者，按落地方式分两类。

    :param target_id: 八类受支持的数据块之一
    :return: {"objects": set[Object], "ids": set[ID]}：
             - objects：Object 引用者（视口 + 大纲 Objects 行选中）；
             - ids：非 Object 数据块引用者（大纲 Blender File 模式行高亮，
               或机制不可用时 INFO 列出）；
             未知类型返回两个空集（poll 已拦，此处防御）。
             World / Scene 引用者按设计不在返回值内（execute 单独 INFO）。
    """
    fam = get_family(target_id)
    if fam is Material:
        ids, objects = _ids_using_material(target_id)
        return {"objects": objects, "ids": ids}
    if fam is Image:
        ids = _materials_using_image(target_id) | _cameras_using_image(target_id)
        return {"objects": _objects_using_image_empty(target_id), "ids": ids}
    if fam is GeometryNodeTree:
        objects, ids = _gn_direct_referencers(target_id)
        return {"objects": objects, "ids": ids}
    if fam in (Mesh, Camera, Light, Curve, Curves):
        return {"objects": _objects_using_data(target_id), "ids": set()}
    return {"objects": set(), "ids": set()}


def find_direct_referencers_many(typed_ids) -> dict:
    """多目标并集版：{"objects": set[Object], "ids": set[ID]}（set 天然去重）。"""
    objects = set()
    ids = set()
    for target_id in typed_ids:
        r = find_direct_referencers(target_id)
        objects |= r["objects"]
        ids |= r["ids"]
    return {"objects": objects, "ids": ids}


# ============================================================================
# 选中执行（模块级纯函数，只依赖传入的 context.view_layer）
# ============================================================================


def execute_selection(context, targets: set) -> tuple:
    """执行选中：全清 → 按对象名排序逐个选中 → 汇总跳过项 → 设激活对象。

    顺序与边界（实测依据见 docs/research_report.md §5.2）：
    1. 先查 obj.name in view_layer.objects：所在集合被 View Layer exclude 的对象
       不在当前层，对其 select_set 会抛 RuntimeError，必须预先拦下（计入 excluded）；
    2. 再查隐藏：hide_set（视口级）与 hide_viewport（对象级）都会让 select_set
       静默失败，直接跳过（计入 hidden），不主动取消隐藏（避免副作用）；
    3. select_set 仍包一层 RuntimeError 防御（库链接对象等边缘情形并入 excluded）。

    :param context: bpy context（只用 context.view_layer；选中只作用于当前
                    View Layer，其他层的引用者不选中也不报错）
    :param targets: 待选中 Object 集合（扫描阶段返回 set，已去重）
    :return: (selected, hidden, excluded) 三个列表，元素均按对象名排序
    """
    vl = context.view_layer
    ordered = sorted(targets, key=lambda o: o.name)
    selected = []
    hidden = []
    excluded = []
    # 先全清当前 View Layer 的选中状态（目标之外不受影响的前提）
    for obj in vl.objects:
        obj.select_set(False)
    for obj in ordered:
        if obj.name not in vl.objects:
            # 典型：所在集合被 exclude；select_set 对其抛 RuntimeError，预先拦下
            excluded.append(obj)
            continue
        if obj.hide_get(view_layer=vl) or obj.hide_viewport:
            # 两种隐藏都会静默失败：跳过并汇报，不自动取消隐藏
            hidden.append(obj)
            continue
        try:
            obj.select_set(True)
        except RuntimeError:
            # 防御兜底（如库链接对象边缘情形），并入 excluded 汇总
            excluded.append(obj)
            continue
        selected.append(obj)
    if selected:
        # 激活对象取排序后第一个成功选中者（属性栏同步）
        vl.objects.active = selected[0]
    return selected, hidden, excluded


# ============================================================================
# 大纲数据块行高亮（v3 新增；机制由 §4 探针五轮实测确定）
# ============================================================================


def _find_outliner_context(context) -> "tuple | None":
    """定位 LIBRARIES 模式的 Outliner 上下文，返回 (window, area, region, space)。

    优先取当前 context.area（operator 真实触发路径）；否则扫描全部窗口
    （测试经 temp_override 注入 selected_ids、裸 context 无 outliner 时仍能
    工作）。非 LIBRARIES 模式的 outliner 不适用（其树不含数据块分节，
    select_all 会误选对象行），找不到即返回 None → 调用方回退 INFO。
    """
    candidates = []
    try:
        area = getattr(context, "area", None)
        window = getattr(context, "window", None)
        if area is not None:
            candidates.append((window, area))
    except Exception:
        pass
    try:
        for w in bpy.context.window_manager.windows:
            for a in w.screen.areas:
                candidates.append((w, a))
    except Exception:
        pass
    for w, a in candidates:
        if w is None or a is None or a.type != "OUTLINER":
            continue
        space = a.spaces.active
        if getattr(space, "display_mode", None) != "LIBRARIES":
            continue
        region = next((r for r in a.regions if r.type == "WINDOW"), None)
        if region is None:
            continue
        return (w, a, region, space)
    return None


def select_datablock_rows(context, ids) -> tuple:
    """在大纲 Blender File 模式下高亮数据块行（§4 探针确定的唯一可行机制）。

    机制（tests/probe_outliner_select*.py 五轮实测）：
    - selected_ids 只读（赋值抛 AttributeError），SpaceOutliner RNA 无选择
      接口，bpy.ops.outliner.* 无按 ID/名字定位选中的 op；
    - 可行路径：use_filter_id_type + filter_id_type 限定类型分节（消除对象
      层级同名行与父级链过选）+ 大小写敏感 filter_text 精确名 + tag_redraw
      后 bpy.ops.wm.redraw_timer 泵一次重绘（树在 draw 时才按新过滤器重建）
      + outliner.select_all；还原过滤器后选中态持久；
    - 多目标可行（probe13 实测）：逐名过滤累加后被过滤隐藏的已选行只是
      不可见、选中持久；还原过滤器后 show_one_level(open=True) 展开类型
      分节，全部目标恢复显示（probe8/E1 的"丢选"系 selected_ids 只上报
      可见行造成的误判）；
    - 已知限制：过滤器为子串匹配，同类型且名字包含目标名的数据块会被一并
      高亮（无逐行反选 API，extras 汇报）；0 用户孤儿数据不入树，选中失败
      进 rows_failed 由调用方 INFO 列出。

    链式上溯语义：先清空全部大纲行选中（结果替换输入），再逐个目标累加选中。

    :param ids: 待高亮的非 Object 数据块集合
    :return: (rows_ok, rows_failed, extras) 三个按名字排序的列表；
             机制不可用（无 LIBRARIES Outliner / op 失败 / 灾难性过选）时
             rows_ok 为空、rows_failed 为全部目标
    """
    targets = sorted(set(ids), key=lambda i: i.name)
    if not targets:
        return [], [], []
    found = _find_outliner_context(context)
    if found is None:
        return [], targets, []
    window, area, region, space = found
    saved = {}
    for prop in ("filter_text", "use_filter_id_type", "filter_id_type",
                 "use_filter_case_sensitive"):
        try:
            saved[prop] = getattr(space, prop)
        except Exception:
            pass
    target_set = set(targets)

    def _restore():
        for prop, val in saved.items():
            try:
                setattr(space, prop, val)
            except Exception:
                pass

    try:
        with bpy.context.temp_override(window=window, screen=window.screen,
                                       area=area, region=region,
                                       space_data=space):
            bpy.ops.outliner.select_all(action='DESELECT')
            for target in targets:
                ftype = _ID_TYPE_FOR_FILTER.get(get_family(target))
                if ftype is None:
                    continue
                space.use_filter_id_type = True
                space.filter_id_type = ftype
                space.use_filter_case_sensitive = True
                space.filter_text = target.name
                area.tag_redraw()
                bpy.ops.wm.redraw_timer(type='DRAW_WIN')
                bpy.ops.outliner.select_all(action='SELECT')
            # 还原过滤器设置后再泵一次重绘（探针实测还原后选中持久）
            _restore()
            area.tag_redraw()
            bpy.ops.wm.redraw_timer(type='DRAW_WIN')
            # 关键（probe12/13 实测）：还原过滤器触发树重建后，处于折叠的
            # 类型分节中的已选行不可见——选中状态本身持久，但 selected_ids
            # 只上报可见行（表现为"丢选"，probe8/E1 的误判根因）。展开一层
            # 让所有类型分节可见，选中即恢复显示与上报，多目标随之成立
            try:
                bpy.ops.outliner.show_one_level(open=True)
                area.tag_redraw()
                bpy.ops.wm.redraw_timer(type='DRAW_WIN')
            except Exception:
                pass
            got = set(bpy.context.selected_ids)
    except Exception:
        # 机制失败（headless 无窗口 / op 不可用等）：尽力还原后整体回退 INFO
        _restore()
        return [], targets, []
    rows_ok = [t for t in targets if t in got]
    rows_failed = [t for t in targets if t not in got]
    extras = sorted((i for i in got if i not in target_set),
                    key=lambda i: i.name)
    if len(extras) > 50:
        # 灾难性过选（过滤器失效选中整树）：清空行选中并整体回退 INFO
        try:
            with bpy.context.temp_override(window=window, screen=window.screen,
                                           area=area, region=region,
                                           space_data=space):
                bpy.ops.outliner.select_all(action='DESELECT')
        except Exception:
            pass
        return [], targets, []
    return rows_ok, rows_failed, extras


def _id_label(id_obj) -> str:
    """report 文案用："Material 'Material'" 样式标签。"""
    return "{} '{}'".format(type(id_obj).__name__, getattr(id_obj, "name", id_obj))


# 大纲数据块行高亮的能力边界（tests/probe_outliner_select*.py 十三轮实测）：
# - selected_ids 只读、SpaceOutliner 无选择接口、无按 ID 选中的 op；
# - 可行机制：filter_id_type 限定类型分节 + 大小写敏感 filter_text 精确名
#   + 泵重绘 + outliner.select_all，逐名过滤累加，结束后还原过滤器；
# - 多目标：可行（probe13 实测）。早期"切过滤器重建树丢已选行"（probe8/E1）
#   系误判——被过滤隐藏/折叠分节中的已选行只是不可见，选中状态持久
#   （probe12/F）；selected_ids 只上报可见行。还原过滤器后调
#   outliner.show_one_level(open=True) 展开类型分节，全部目标选中恢复显示；
# - 已知限制：filter_text 仅子串匹配、不支持正则（probe9），同名前缀数据块
#   会被附带高亮（extras 汇报）；users==0 孤儿数据不入 LIBRARIES 树。


# ============================================================================
# Operator
# ============================================================================


class SELECT_REFERENCING_OT_select_references(bpy.types.Operator):
    """选中直接引用了所选数据块的对象或数据块（一跳）"""

    bl_idname = "object.select_references"
    bl_label = "Select References"
    bl_description = (
        "选中直接引用了所选数据块的对象或数据块（一跳语义；支持 Camera / Image /"
        " Light / Material / Mesh / GeometryNodeTree / Curve / Curves）"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context) -> bool:
        """置灰逻辑的唯一判定层：三段校验，任一失败返回 False，
        菜单项自动显示为灰色不可点（可见不可点），draw 中不做任何手工置灰。

        严禁抛异常：selected_ids / space_data 解析失败等任何意外一律返回 False。
        """
        try:
            # 第 1 段：selected_ids 非空（未选中任何数据块 → 置灰）
            # 注意：selected_ids 只在有 Outliner 上下文时可解析（裸读会
            # AttributeError），一律 getattr 防御取值
            ids = getattr(context, "selected_ids", None)
            if not ids:
                return False
            # 第 2 段：当前空间为大纲（Outliner）且处于 "Blender File" 显示模式
            # 注意："Blender File" 对应 LIBRARIES，不是 DATA_API（实测更正）
            sd = getattr(context, "space_data", None)
            if sd is None or sd.type != "OUTLINER" or sd.display_mode != "LIBRARIES":
                return False
            # 第 3 段：同类型判定（isinstance 八具体类 + 显式排除 Object，见 get_family）
            ok, _reason, _family, _typed_ids = classify_selection(ids)
            return ok
        except Exception:
            # poll 不得向菜单系统抛任何异常
            return False

    def execute(self, context) -> set:
        """薄壳：取上下文 → 调模块级纯函数 → 对象选中 + 数据块行高亮 → 分级 report。

        只依赖 selected_ids、不依赖 space_data——保证 headless /
        temp_override(selected_ids=...) 测试路径可行（绕过 poll 直接调 execute）。
        poll 与 execute 之间状态可能变化，故再校验一次 classify_selection。
        """
        try:
            # 非 Outliner 入口（keymap 等）触发时 selected_ids 可能不存在，getattr 防御
            ids = getattr(context, "selected_ids", [])
            ok, reason, family, typed_ids = classify_selection(ids)
            if not ok:
                self.report({'WARNING'}, _t("reject_prefix").format(
                    _t(_REJECT_REASON_KEY.get(reason, reason))))
                return {'CANCELLED'}

            # 逐 ID 扫描直接引用者；单 ID 异常记录跳过，不中断整体
            objects = set()
            id_refs = set()
            for id_obj in typed_ids:
                try:
                    r = find_direct_referencers(id_obj)
                    objects |= r["objects"]
                    id_refs |= r["ids"]
                except Exception as exc:
                    self.report({'WARNING'}, _t("scan_error").format(
                        id_obj.name, exc))

            # World / Scene 引用者：按设计仅 INFO 提示，不进结果集
            if family is Image:
                for img in typed_ids:
                    try:
                        for world in _worlds_using_image(img):
                            self.report({'INFO'}, _t("world_info").format(
                                world.name, img.name))
                    except Exception:
                        pass
            if family is Camera:
                for cam in typed_ids:
                    try:
                        for scene in _scenes_using_camera(cam):
                            self.report({'INFO'}, _t("scene_camera_info").format(
                                scene.name, cam.name))
                    except Exception:
                        pass

            if not objects and not id_refs:
                self.report({'INFO'}, _t("no_results"))
                return {'FINISHED'}

            # Object 引用者：视口 + 大纲 Objects 行选中（v1 逻辑与防护不变）；
            # 无 Object 引用者时不动视口选中（纯数据块结果不清空用户对象选择）
            if objects:
                selected, hidden, excluded = execute_selection(context, objects)
                if selected:
                    self.report({'INFO'}, _t("selected_objects").format(len(selected)))
                if hidden:
                    self.report({'WARNING'}, _t("hidden_skipped").format(
                        len(hidden), _t("join_sep").join(o.name for o in hidden)))
                if excluded:
                    self.report({'WARNING'}, _t("excluded_skipped").format(
                        len(excluded), _t("join_sep").join(o.name for o in excluded)))

            # 非 Object 数据块引用者：大纲 Blender File 模式行高亮（多目标
            # 逐名过滤累加，probe13 实测可行）；无法高亮的回退 INFO 逐个列出
            if id_refs:
                present = sorted((i for i in id_refs
                                  if getattr(i, "users", 1) > 0),
                                 key=lambda i: i.name)
                orphans = sorted((i for i in id_refs
                                  if getattr(i, "users", 1) == 0),
                                 key=lambda i: i.name)
                if present:
                    rows_ok, rows_failed, extras = select_datablock_rows(
                        context, set(present))
                    if rows_ok:
                        self.report({'INFO'}, _t("highlighted").format(
                            len(rows_ok), _t("join_sep").join(
                                _id_label(i) for i in rows_ok)))
                    if extras:
                        self.report({'INFO'}, _t("extras").format(
                            len(extras), _t("join_sep").join(
                                _id_label(i) for i in extras)))
                    if rows_failed:
                        self.report({'INFO'}, _t("rows_failed").format(
                            _t("join_sep").join(_id_label(i) for i in rows_failed)))
                if orphans:
                    self.report({'INFO'}, _t("orphans").format(
                        _t("join_sep").join(_id_label(i) for i in orphans)))
            return {'FINISHED'}
        except Exception as exc:
            # 兜底：不产生半选状态（execute_selection 先全清再逐个选中，
            # 中断时最多"少选"，不误选）
            self.report({'ERROR'}, _t("execute_error").format(exc))
            return {'CANCELLED'}


# ============================================================================
# 菜单注册
# ============================================================================


def _draw_menu(self, context):
    """OUTLINER_MT_context_menu 附加绘制函数。

    不做任何可用性判断：poll 失败时菜单项仍会绘制并自动置灰（可见但不可点），
    置灰判定单一来源在 poll，避免 draw 与 poll 逻辑漂移。
    """
    self.layout.operator(
        SELECT_REFERENCING_OT_select_references.bl_idname,
        text=_t("menu_label"),
    )


# 已 append 到 OUTLINER_MT_context_menu 的绘制函数账本（幂等注册的生命线）。
#
# 必须用 `if ... not in globals()` 守卫，不能写成普通赋值 `_APPENDED_DRAW_FNS = []`：
# importlib.reload 会保留模块 __dict__（同一字典对象）并重新执行源码，普通赋值会把
# 账本重置为空，导致 reload 前已 append 的旧绘制函数失联——register 里无条件
# append 每轮净增一个菜单项（用户实测"右键出现多个 Select References"的根因）。
# 守卫写法下账本跨 reload 存活【实测：reload 后非源码普通赋值键存活】，
# register/unregister 据此清账移除历史条目。
# 注意：菜单类上不存在 _items 属性（实测 hasattr False），Python 侧无法枚举菜单
# 已 append 的函数，本账本是唯一可维护状态；且 reload 后新旧函数共享同一 globals
# 字典，任何基于 __globals__ 指纹的清理判据在 reload 场景下恒为 False，不可靠。
if "_APPENDED_DRAW_FNS" not in globals():
    _APPENDED_DRAW_FNS = []


def register():
    """幂等注册：清账移除历史菜单条目 → 注册 Operator → append 并记账。

    - ① 先防御性调一次 unregister：unregister_class 对未注册新类抛 RuntimeError
      【实测】、remove(未 append 的函数) 静默 no-op【实测】，整体 try/except 吞掉；
    - ② 按账本逐个 remove 历史 append 的 draw 函数（含跨 reload 残留），清空账本；
      menu.remove 对未 append 的函数不报错、多次 remove 同一函数也不报错【实测】，
      无需精确去重判断；
    - ③ register_class：同一 Python 类对象重复注册抛 ValueError【实测】→ 定点
      捕获；同 bl_idname 的新类对象注册由 Blender 静默替换（打印 Info）【实测】
      → 无需处理；
    - ④ append 当前 _draw_menu 并记入账本。

    原 §5.9"重复注册由 Blender 抛错自然暴露，不吞异常"由本幂等方案废止
    （docs/architecture_plan.md §10.1）。
    """
    # ① 防御性注销
    try:
        unregister()
    except Exception:
        pass
    # ② 清账：移除历史（含跨 reload 残留）append 的 draw 函数
    for old in _APPENDED_DRAW_FNS:
        try:
            bpy.types.OUTLINER_MT_context_menu.remove(old)
        except Exception:
            pass
    _APPENDED_DRAW_FNS.clear()
    # ③ 注册 Operator（同 py 类对象重复注册抛 ValueError → 定点防御）。
    #    bl_label / bl_description 在 register_class 前按当前语言定型（tooltip
    #    静态；菜单与 report 经 _t 运行时取词，不受此限制）
    _op_cls = SELECT_REFERENCING_OT_select_references
    _op_cls.bl_label = _t("menu_label")
    _op_cls.bl_description = _t("description")
    try:
        bpy.utils.register_class(_op_cls)
    except ValueError:
        pass
    # ④ append 并记账
    bpy.types.OUTLINER_MT_context_menu.append(_draw_menu)
    _APPENDED_DRAW_FNS.append(_draw_menu)


def unregister():
    """注销：按账本移除全部菜单绘制函数 → 注销 Operator 类（严格逆序）。

    - 账本逐个 remove：对未 append 的函数静默 no-op【实测】，整体 try/except
      防御极端情形；remove 后清空账本；
    - unregister_class 对未注册类抛 RuntimeError【实测，非静默】→ 定点捕获。
    """
    for old in _APPENDED_DRAW_FNS:
        try:
            bpy.types.OUTLINER_MT_context_menu.remove(old)
        except Exception:
            pass
    _APPENDED_DRAW_FNS.clear()
    try:
        bpy.utils.unregister_class(SELECT_REFERENCING_OT_select_references)
    except RuntimeError:
        # 未注册类【实测 RuntimeError，非静默】
        pass


if __name__ == "__main__":
    # 便于在 Blender Text Editor 中直接运行调试
    register()
