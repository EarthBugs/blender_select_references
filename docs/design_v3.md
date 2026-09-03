# Select References v3 设计：直接引用者选择（一跳语义）

- 日期：2026-09-02
- 触发：用户 GUI 实测反馈"不完全正确"，并给出三个验收例子
- 性质：**语义重构**（替换 v1 的"终端 Object"语义），非缺陷修复
- 架构判断：核心架构（模块级纯函数 + 薄 Operator + poll 单一判定源 + 账本幂等注册）**不变**；重构范围为"扫描函数返回什么"与"execute 如何落地选择"

## 1. 用户场景与验收例子

用户工程（`sel_ref_test.blend` 变体）：

- Mesh 数据块 "Cube" 的 **DATA 槽**引用材质 "Material"；"Material" 的节点树引用图像 "test_image"；
- 对象 "Sphere" 引用 Mesh "Sphere"，且以 **OBJECT 槽**引用材质 "m2"；Mesh "Sphere" **不**引用 "m2"。

| # | 输入 | 期望结果 | 说明 |
|---|------|---------|------|
| 1 | 图像 test_image | 选中**材质 "Material"**（引用它的数据块），**不**选中 Cube 对象 | 引用者是数据块 → 选数据块 |
| 2 | 材质 Material | 选中 **Mesh "Cube"**（DATA 槽引用者），**不**选中 Cube 对象 | DATA 槽引用挂在 Mesh 上 |
| 3 | 材质 m2 | 选中**对象 "Sphere"**（OBJECT 槽引用者） | OBJECT 槽引用挂在对象上 |

**核心语义**：每次触发，把选中沿引用链**向上游走一跳**——直接引用者是什么就选什么。
三个例子连成链：`test_image → Material → Cube(Mesh) → Cube(Object)`；OBJECT 槽特例：`m2 → Sphere(Object)`。
用户可连续触发逐级上溯，本功能不自动多跳。

与 v1 语义的区别：v1 一律走到终端 Object（例 1 会选中 Cube 对象——被用户否定）。

## 2. 需求拆解

- **R1 一跳语义**：结果为目标的**直接引用者集合**，不再向终端 Object 传播。
- **R2 引用者可为数据块**：Material/Mesh/Camera/GN 组等数据块作为引用者时，选中数据块本身（呈现于大纲 Blender File 模式对应分节），而非其宿主对象。
- **R3 DATA/OBJECT 槽分流**：材质被 Mesh 等数据块的 DATA 槽引用 → 选该数据块；被对象 OBJECT 槽引用 → 选该对象。同一材质可同时有两类引用者，结果取并集。
- **R4 输入规则不变**：仍限同一家族多选（Camera/Image/Light/Material/Mesh/GN树/Curve/Curves），混杂或含 Object 置灰；Object 不作为输入类型。
- **R5 对象引用者仍按 v1 方式选中**（视口 + 大纲 Objects 高亮），隐藏/被排除对象的防护逻辑保留。
- **R6 结果可为空或仅含不可呈现引用者**（如 World、Scene）：INFO 报告说明，不视为错误。

## 3. 引用边规范（目标 ← 直接引用者 → 结果）

| 目标类型 | 直接引用者 | 结果实体 | 备注 |
|---|---|---|---|
| Image | Material（节点树直连 ∪ ShaderNodeGroup 嵌套） | **Material 数据块** | 沿用按 owner 判定法（内嵌树同名陷阱见 §10.3/测试报告 Bug B） |
| Image | Camera（background_images） | **Camera 数据块** | |
| Image | Object（image empty，`obj.data is img`） | Object | |
| Image | World（环境纹理） | World → 仅 INFO 列出 | World 无可视选中态 |
| Material | Mesh / Curve / Curves（DATA 槽：目标 ∈ data.materials） | **对应数据块** | 遍历 bpy.data.meshes / curves / hair_curves |
| Material | Object（slot.link=='OBJECT' 且 slot.material 是目标） | Object | 与 DATA 槽判定互斥分流 |
| Mesh / Camera / Light / Curve / Curves | Object（`obj.data is 目标`） | Object | 与 v1 相同 |
| Camera | Scene（scene.camera） | 仅 INFO | |
| GeometryNodeTree | Object（NodesModifier.node_group 是目标） | Object | 直接引用，不递归 |
| GeometryNodeTree | GeometryNodeTree（组节点嵌套引用） | **父 GN 组数据块** | 一跳：子组 → 父组；不再递归到对象 |

注意 GN 变化：v1 选中间接挂修改器的对象（递归到底）；v3 只走一跳——选子组得到父组，选父组得到挂修改器的对象。连续触发即可上溯，与用户的链路心智一致。

## 4. 选择落地机制（关键技术风险点）

结果分两类落地：

- **Object 引用者**：沿用 v1 `execute_selection`（去重、排序、隐藏/排除防护、active 设置）。
- **非 Object 数据块引用者（Material/Mesh/Camera/GN 组）**：需要在大纲 Blender File 模式下**高亮对应行**。Blender Python 是否可编程设置大纲数据块选中态**未验证**，按以下顺序探针（在 Blender 5.2 会话内经 socket 实测，记录每条结论）：
  1. `bpy.context.selected_ids` 是否可写（赋值/extend）；
  2. `bpy.types.SpaceOutliner` 的 RNA 属性中是否存在选择相关接口（`bl_rna.properties` 枚举）；
  3. `bpy.ops.outliner.*` 中是否存在可按 ID/名字定位选中的 op；`select_all` 配合 `space_data.filter_text`（过滤后全选再还原过滤器）的 hack 是否可行（temp_override 注入 outliner area/region/space_data）。
- **回退方案（探针全部不可行时）**：非 Object 引用者以 INFO report 逐个列出（"引用者：Material 'Material'、Mesh 'Cube'"），同时 Object 引用者正常选中；报告中明确"大纲行高亮不受 API 支持"。**若走回退，必须在最终汇报中显式告知用户该限制。**

业务逻辑与 UI 机制解耦：核心纯函数 `find_direct_referencers(target) -> dict`，返回
`{"objects": set[Object], "ids": set[ID]}`（ids 为非 Object 数据块引用者）——无论选择机制探针结果如何，该函数都可完整自动化测试。

## 5. 实现改动点

1. 新增 `find_direct_referencers(target)`（单目标）与 `find_direct_referencers_many(typed_ids)`（并集），替换/重构 `find_referencing_objects` 的调用链；按 §3 边表逐个实现分流函数（`_ids_using_material` 拆 DATA/OBJECT；`_materials_using_image`、`_cameras_using_image`、`_objects_using_image_empty`、`_worlds_using_image`；`_objects_using_data` 保留；`_gn_direct_referencers`）。
2. Operator.execute 重构：对象部分走原选择逻辑；ids 部分走 §4 探针确定的机制（或回退 INFO）；report 汇总。
3. poll/classify/菜单/账本注册：**零改动**。
4. `bl_info["version"]` 升 (1, 2, 0)，docstring 语义描述同步。
5. **发布同步**：改完工作区 `select_references.py` 后，必须同步覆盖 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\select_references.py`（用户实际加载的是 addons 副本），并经 socket `addon_disable`+`addon_enable` 刷新会话内代码。

## 6. 测试计划（tests/test_select_references.py 升级为 v4）

- 扫描断言全部改到 `find_direct_referencers` 的返回值（objects/ids 分类断言）：
  - Image → ids={mat_a, mat_b(嵌套), cam_data}, objects={empty}；World 仅报告；
  - Material(DATA) → ids={mesh_shared}（**不含** obj_a/obj_b）；
  - Material(OBJECT+DATA) → objects={obj_a}, ids={mesh_mat}；
  - Mesh/Camera/Light/Curve/Curves → objects 同 v1；
  - GN 子组 → ids={gn_parent}；GN 父组 → objects={obj_gn}；
- 选择落地：对象部分沿用 execute 断言；ids 部分按探针结果断言（可行则验大纲选中态，回退则验 report 文本含数据块名）；
- 保留：classify 五族、隐藏/排除防护、T19 注册幂等、清理无残留；
- 环境陷阱（已实测，沿用）：`hasattr(bpy.types,…)` 恒 False 用 ValueError 探针；reload 后需幂等 register；Curves 夹具 `curves_empty_hair_add` 创建、`batch_remove` 清理、`bpy.data.hair_curves`；**测试前 sys.modules 已有 addon 版 select_references，须先 pop 再从工作区 sys.path 导入，或先同步 addons 再 reload**——否则会测到旧代码。

## 7. 风险与开放问题

- **最大风险**：大纲数据块行选中可能无 API（§4 探针决定）。回退时用户体验为"对象高亮 + INFO 列出数据块名"。
- filter_text hack 若可行，需注意：精确名匹配、多结果逐个过滤、还原用户原过滤器与选中、LIBRARIES 模式下过滤器是否生效。
- Scene/World 引用者永远只能 INFO（无选中态），属预期。
- 用户既有习惯变化：v1 场景（选材质想直接拿到对象）现在需要多触发一次（材质→Mesh→再→Object）。符合用户新表述，不再兼容旧语义。

## 8. 交接给执行 agent 的必读资料

- 本文件（语义与验收标准的唯一来源）；
- `docs/architecture_plan.md` §10（注册幂等、Curves 实测细节、GUI 排查脚本）；
- `tests/test_report.md`（v1 修复存档：hide_get、内嵌树同名 Bug B 的按 owner 判定法）；
- socket 协议：`C:\Users\EarthBugs\.workbuddy\skills\blender-mcp-socket-test\SKILL.md`；
- Python：`C:\Users\EarthBugs\.workbuddy\binaries\python\versions\3.13.12\python.exe`；发送器 `tests/run_socket_test.py`。
