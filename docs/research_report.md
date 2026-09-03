# Select References 插件调研报告（Blender 5.2）

> 调研日期：2026-09-01。验证环境：本机 Blender **5.2.0 LTS**（GUI 会话，经 MCP socket 实测执行 Python），另以
> `blender --background --factory-startup --python` 独立 headless 实例复测。文档核对 docs.blender.org 4.2/5.0/5.2 API 页。
> 标注约定：**【实测】**=本机 Blender 5.2 中实际执行验证；**【文档】**=官方文档/源码提交佐证；**【推断】**=基于以上二者的合理推断，建议实现时复核。

---

## 1. 大纲 API

### 1.1 SpaceOutliner.display_mode 枚举【实测】

`bpy.types.SpaceOutliner.bl_rna.properties['display_mode'].enum_items`（5.2 实取）：

| identifier | 名称 | 说明 |
|---|---|---|
| `SCENES` | Scenes | 场景视图 |
| `VIEW_LAYER` | View Layer | View Layer 视图 |
| `SEQUENCE` | Video Sequencer | 序列编辑器 |
| **`LIBRARIES`** | **Blender File** | **"Blender File" 显示模式** |
| `DATA_API` | Data API | Data API 视图 |
| `LIBRARY_OVERRIDES` | Library Overrides | 库覆盖 |
| `ORPHAN_DATA` | Unused Data | 未使用数据 |

**重要更正**：题目猜测的 `DATA_API` 实际对应 UI 上的 "Data API"；**"Blender File" 模式对应 `LIBRARIES`**。
实测时用户 GUI 中的大纲正处于 `LIBRARIES` 模式，与 UI 一致。判断"当前大纲是 Blender File 模式"应写
`space.display_mode == 'LIBRARIES'`。

### 1.2 OUTLINER_MT_context_menu【实测】

- `hasattr(bpy.types, 'OUTLINER_MT_context_menu')` 为 True；`issubclass(..., bpy.types.Menu)` 为 True；
  `bl_label == 'Outliner'`；具备标准 `append`/`prepend` 类方法。
- 注册自定义项的标准写法【文档】：定义 `draw(self, context)` 函数，在其中用 `layout.operator(...)` 添加，
  `bpy.types.OUTLINER_MT_context_menu.append(fn)` 注册、`... .remove(fn)` 注销。函数内应先判断
  `context.selected_ids` 等上下文是否可用。
- 注意【文档】：历史源码注释（rBaf008f553293）指出大纲右键菜单"生成方式特殊"，但自 2.92 起 Outliner 会把
  选中数据块通过 context 成员传给真正的 operator，`OUTLINER_MT_context_menu` 是正规扩展点。

### 1.3 菜单置灰【文档】

菜单项调用的是 operator；**operator 的类方法 `poll(context)` 返回 False 时，菜单项自动显示为灰色不可点**，
无需在 draw 里手工处理。这是 Menu/operator 系统的标准行为（官方文档 "Operator plugins / poll" 一节）。
因此"多选类型混杂或含不支持类型 → 置灰"应全部实现在 operator 的 `poll()`/`draw()` 中：
poll 返回 False（整项灰死），或在 draw 中 `row.enabled = ...`（动态判断）。

---

## 2. bpy.context.selected_ids

### 2.1 本质：editor 区域回调成员，不是全局成员【实测+文档】

- 裸读 `bpy.context.selected_ids`（Text Editor / 无 Outliner 上下文）→ **AttributeError**【实测】。
- 通过 `temp_override(window=..., screen=..., area=<OUTLINER area>, region=<WINDOW region>,
  space_data=...)` 后读取**成功**；实测 5.2 中用户大纲（LIBRARIES 模式）当前选中行返回
  `[Object 'Cube']`【实测】。
- 4.2 官方文档仅注明类型 "sequence of bpy.types.ID"，未描述顺序/去重【文档】。
- 源码（`outliner_context_selected_ids_recursive`）【文档】：只收集**本身被选中**且 `tse->type == 0`
  （数据块行）或 `TSE_LAYER_COLLECTION` 的行的 `tse->id`——即：
  1) 返回**大纲行级选中**（TSE_SELECTED 标志），与视口 Object 选择是两套状态；
  2) 选中集合行只给 Collection 本身，**不会**递归带出其子对象；
  3) 按**大纲树遍历顺序**返回（深度优先），无显式去重步骤（同一 ID 一般只出现一行，LIBRARIES 模式下无重复行风险）。
- VIEW_3D 区域也有自己的 `selected_ids` 回调（大致等于 selected_objects）；实测 5.2 下 VIEW_3D override
  读取返回空列表、不报错【实测】。⇒ 插件 operator 从 Outliner 右键菜单触发时，`context.selected_ids`
  **直接可用**（菜单调用自带 area/region），无需任何 override【文档+推断】。

### 2.2 用 temp_override 伪造选中【实测】

`with bpy.context.temp_override(selected_ids=[<ID>...])` 完全可行：
- GUI 会话与 headless 会话中均成功；override 内读 `bpy.context.selected_ids` 原样返回注入的 ID 列表
  （实测注入单个 Object 后返回 `[bpy.data.objects['SR_TEST_O']]`）。
- 传任意 ID 类型均可（实测 Material/Object）。
- **测试策略成立**：单元测试可不依赖 UI，直接 `temp_override(selected_ids=[mat1, mat2])` 后调用 operator
  的 `execute()`（注意绕过 poll，或直接调用扫描函数）。

---

## 3. 类型判定

### 3.1 六类 ID 的类名与继承【实测】

| UI 类型 | bpy.types 类名 | 继承链（bl_rna.base 逐级） |
|---|---|---|
| Camera | `bpy.types.Camera` | Camera → ID |
| Image | `bpy.types.Image` | Image → ID |
| Light | `bpy.types.Light` | Light → ID |
| Material | `bpy.types.Material` | Material → ID |
| Mesh | `bpy.types.Mesh` | Mesh → ID |
| Geometry Nodes | `bpy.types.GeometryNodeTree` | GeometryNodeTree → NodeTree → ID |

- Light 子类【实测】：`PointLight` / `SpotLight` / `SunLight` / `AreaLight`，均为 Light 的直接子类。
- NodeTree 平级子类【实测】：`ShaderNodeTree` / `CompositorNodeTree` / `GeometryNodeTree` / `TextureNodeTree`。

### 3.2 "同类型"判定的稳健写法【实测】

**关键坑**：点光源 `type(light).__name__` 与 `light.bl_rna.identifier` 都是 **`'PointLight'`** 而非 `'Light'`
（实测），即 Python 类型与 RNA identifier 都返回具体子类型。因此：

- `type(a) == type(b)`：会把"点光 + 聚光"的多选判为异类 → 不符合"同为 Light"的产品语义；
- `a.bl_rna.identifier == 'Light'`：同样错误（identifier 是 'PointLight'）；
- **推荐 `isinstance`**：`isinstance(id, bpy.types.Light)` 对四个子类均为 True（实测）。六类判定用
  `isinstance(id, (Camera, Image, Light, Material, Mesh, GeometryNodeTree))`，再单独确定家族
  （Light 家族内部不区分点/聚/日/面）；
- 若必须精确到 RNA 类型做比较，需沿 `bl_rna.base` 链匹配家族根类。注意 `GeometryNodeTree` 与
  `ShaderNodeTree` 等同为 NodeTree 子类，`isinstance(gnt, NodeTree)` 会把材质节点树也放进来 →
  判定必须针对六个具体类。
- **Object 特殊性**【实测】：Object 不是六类之一但 `isinstance(obj, ID)` 为 True；且大纲 LIBRARIES 模式
  中 Object 行（`tse->type == 0`）也会进入 selected_ids（实测选中 Cube 返回 Object）。⇒ poll 中必须显式
  拒绝 `bpy.types.Object`（否则选中 Cube+Mesh 会被误判为"含支持类型"）。
- 多选一致性写法（推断）：先过滤 `isinstance(x, Object)` 与不在六类者 → 有则 False；再取首元素的家族，
  其余元素逐个 `isinstance(x, family_root)` 比较。

---

## 4. 引用扫描方案（可实现的 API 路径）

### 4.1 Mesh / Camera / Light → Object【实测+文档】

遍历 `bpy.data.objects`，判断 `obj.data is <所选ID>`（三类的 `obj.data` 均直接指向对应数据块；
实测 Light 的 `obj.data` 为 PointLight 实例，`obj.type == 'LIGHT'`）。注意：
- 只遍历 `bpy.context.scene.view_layer.objects` 会漏掉其他 View Layer 的对象；要全场景覆盖应遍历
  `bpy.data.objects` 并按需检查 `obj.name in view_layer.objects` 过滤【推断】。
- 多用户/linked duplicate：两个 Object 共享同一 mesh 时（实测）各自独立出现，逐一返回即可。

### 4.2 Material【实测】

- `obj.material_slots[i]`：`MaterialSlot.link` 枚举为 `['OBJECT', 'DATA']`（实取）。
  - `link == 'DATA'`：材质来自 `obj.data.materials`（网格级）；
  - `link == 'OBJECT'`：材质是**对象级覆盖**，`slot.material` 才是实际引用，`obj.data.materials` 不反映
    该覆盖（实测：对 slot 设 OBJECT 级材质后，data.materials 仍只有网格级条目）。
- **结论**：只扫 `obj.data.materials` 会漏 object-linked 槽；正确做法是遍历每个 Object 的
  `material_slots`，取 `slot.material`（DATA 槽时二者一致）。
- 几何节点/修改器中引用材质：`GeometryNodeSetMaterial` 节点（实测该类存在）及材质 socket 的
  `default_value` 可引用材质；修饰器里的 Set Material 通常经节点组传入。覆盖性价比：中——按"值得覆盖"
  处理，可在节点组递归扫描中顺带收集 `node.inputs` 中 `socket_type == 'NodeSocketMaterial'` 的
  `default_value`【推断】。

### 4.3 Image【实测为主】

实测可覆盖的引用点（均验证可取到 `.image`）：

| 引用点 | API 路径 |
|---|---|
| 材质图像纹理 | `material.node_tree.nodes` 中 `ShaderNodeTexImage.image`、`ShaderNodeTexEnvironment.image` |
| 节点组内嵌套 | `ShaderNodeGroup.node_tree` 递归进子树再找上述节点 |
| World 环境 | `world.node_tree.nodes`（World.use_nodes）中同上节点；`World.node_tree` 为 ShaderNodeTree |
| Image Empty | `obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE'` 时 **`obj.data` 即 Image**（实测 `type(emp.data).__name__ == 'Image'`） |
| **相机背景图** | **`camera.background_images`**（Collection，元素类 `CameraBackgroundImage`），取 `.image`；相关属性：`source`（'IMAGE'/'MOVIE'/'SEQUENCE'）、`show_background_image`、`use_camera_clip`、`display_depth` 等（实取属性表） |

**相机背景图重点确认**：Blender 5.2 中背景图挂在 **Camera 数据块**的 `camera.background_images` 集合上
（2.8x 起从 View3D 迁移至此，5.x 未再变动；实测 RNA 存在该集合、`background_images.new()` 后
`.image` 可赋值、类型名 `CameraBackgroundImage`）。
另：遍历材质时应遍历 `bpy.data.materials`（或至少所有被 Object 引用的材质），不能只看场景对象槽位。
（VSE 序列条目的图像引用属边缘场景，暂不覆盖【推断】。）

### 4.4 GeometryNodeTree【实测】

- 入口：`bpy.data.objects` 遍历 → `obj.modifiers` → `mod.type == 'NODES'` → **`NodesModifier.node_group`**
  （实测赋值/读取正常）。
- 嵌套：节点树内 `GeometryNodeGroup` 类型节点（`node.bl_idname == 'GeometryNodeGroup'`）的
  **`node.node_tree`** 指向被嵌套的 GeometryNodeTree（实测）。
- **循环引用必须防护**：实测通过 Python 直接把 A 组内 Group 节点的 `node_tree` 设回 B→A 成环是
  **允许的**（UI 不给这么建，API 不拦）。递归扫描必须带 `visited` 集合（以 node_group 的
  `name`/`id` 为 key），否则死循环。
- 顺带可收集材质 socket（见 4.2）【推断】。

---

## 5. 选中执行 API

### 5.1 正确用法【实测】

```python
bpy.ops.object.select_all(action='DESELECT')   # 或 for o in context.view_layer.objects: o.select_set(False)
for obj in targets:
    obj.select_set(True)
context.view_layer.objects.active = targets[0]  # 激活对象，属性栏同步
```

- `select_set(False)` 等价 deselect；`bpy.ops.object.select_all` 在 headless 也可运行（实测）。

### 5.2 边界行为（重要）【实测】

| 情形 | `select_set(True)` 结果 |
|---|---|
| `hide_set(True)`（视口手动隐藏） | **静默失败**：`select_get()` 返回 False，不进 selected_objects |
| `hide_viewport = True`（对象级显示器图标） | **静默失败**，同上 |
| 所在集合被 View Layer **exclude** | **抛 RuntimeError**："Object ... cannot be selected because it is not in View Layer" |

- 但 `view_layer.objects.active = <隐藏对象>` **可以**成功（实测）。
- 设计建议：目标对象先检查 `obj.name in view_layer.objects`（排除集合成员不在其中），对隐藏对象可先
  `obj.hide_set(False)`（或记录并跳过，按产品语义定）【推断】。

### 5.3 linked duplicate【实测】

两个 Object 共享同一 mesh（`obj.data` 相同）时，`select_set` 只选中被操作的那个对象，**不会**自动联动
另一个 —— 逐个选中目标 Objects 即可，无特殊处理。

---

## 6. Blender 5.2 插件形态

- **legacy bl_info add-on 仍受支持**【文档+实测】：官方手册（Advanced → Extensions → Add-ons）明言
  4.2 起 legacy add-on "deprecated 但将继续被支持"，经 Preferences 的 "Install legacy Add-on" 安装。
  实测用户 5.2 会话中 legacy 插件（MP7Tools、node_wrangler、pose_library）与扩展
  （`bl_ext.user_default.mcp` 等）同时启用，证明两形态共存。
- **用户级目录**【实测】：
  - legacy：`%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons` —— **正确**，
    `bpy.utils.user_resource('SCRIPTS', path='addons')` 实测返回该路径且目录存在；
  - 扩展：`%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default`
    （`bpy.utils.user_resource('EXTENSIONS', path='user_default')`）。
- **与 Extensions 的关系**【文档】：扩展用 `blender_manifest.toml` 替代 bl_info，模块名进命名空间
  `bl_ext.<repository>.<name>`，子模块必须相对导入。对本插件的建议：结构简单（一个 operator + 菜单
  append），**legacy 形态最省事**；若要上 extensions.blender.org 分发再补 manifest【推断】。

---

## 7. headless 测试

实测命令：`blender --background --factory-startup --python test.py`（5.2）：

- `bpy.context.selected_ids` → AttributeError（无 GUI 无 Outliner 上下文）【实测】；
- `temp_override(selected_ids=[...])` 伪造 → **可用**【实测】，测试应一律走这条路；
- `select_set` / `view_layer.objects.active` / `bpy.ops.object.select_all` / 数据 API
  （materials/node_groups/modifiers）全部正常【实测】；
- `addon_utils.enable("<module_name>")`：参数是模块名（不是显示名），返回 (found, enabled) 元组；
  扩展模块名须写全 `bl_ext.user_default.<name>`。相关函数：`enable/disable/check/module_bl_info/
  extensions_refresh`（实测列出）。headless 启用插件正常【实测+文档】；
- 无 GUI 限制：依赖区域上下文的 operator（如需 window/screen 的 UI 类 op）poll 会失败；纯数据
  operator 与直接调用 execute 不受影响【实测+推断】；
- 注意 `--factory-startup` 才是干净环境（默认启动文件会带 Cube 等对象，实测 selected_objects 出现
  Cube）【实测】。

---

## 8. 其他坑

- **selected_ids 已知问题**【文档】：仅在有 Outliner（或 View3D）上下文时存在；裸用报 AttributeError
  是 StackExchange 高频问题；旧版本（4.x→5.x）从"文档列出"变为"必须经区域回调解析"，升级用户脚本
  时易踩。它只含数据块行与 LayerCollection 行，选中集合不会展开子对象。
- **多 View Layer**【文档+推断】：`view_layer.objects` 只含当前 View Layer 可见对象；excluded 集合对象
  不在其中（select_set 抛错，见 5.2）。跨 View Layer 的"引用选中"应遍历 `bpy.data.objects`，对不在
  当前 View Layer 的对象明确策略（跳过或临时启用）。
- **库链接（linked library）数据**【推断】：链接数据块 `id.library` 非 None（实测本地对象为 None）；
  LIBRARIES 模式正是展示外部库数据的主视图，**大概率会被用户在该模式下使用本插件**。Objects 若为
  链接对象，`select_set` 在其位于 View Layer 时可用，但修改属性（hide_set 可，改数据不行）受限；
  扫描引用本身只读，安全。
- **多用户数据**【实测】：`id.users > 1`、`use_fake_user` 行为验证正常（置 fake user 后 users+1）。
  扫描无需关心 users；但注意孤儿数据（0 用户）不会出现在 LIBRARIES 默认过滤视图之外的场景树里。
- **对象隐藏 vs 数据块隐藏**：ID 级（如 mesh 的 hide_viewport 语义在对象上）与对象级 hide_set 是两套；
  置灰逻辑只看数据块类型，执行逻辑才涉及可见性（见 5.2）。
- **operator 上下文**：从右键菜单触发时 `context.selected_ids` 直接可用；但同一 operator 若被从
  其他区域/快捷键触发（如注册了 keymap 到 window），`selected_ids` 可能不存在 —— execute 里要做
  `getattr(context, 'selected_ids', [])` 防御【推断】。

---

## 未验证项

1. GUI 中真实点击右键菜单 → operator 触发链路（无自动化 UI 测试手段；由 1.2/2.1 的文档与源码佐证）。
2. 大纲 LIBRARIES 模式下选中 Material/Image/NodeTree 行返回对应 ID 实例 —— 由源码 `tse->type == 0`
   逻辑与实测（Object 行返回 Object）强佐证，未对六类逐一 UI 实测。
3. VSE 序列条目、Light node tree 内的图像引用（Light.node_tree/use_nodes 存在性已实测，内部节点
   扫描为推断）。
4. 跨 .blend 库链接文件的实际扫描行为（无链接库测试环境）。

---

## 给架构师的要点清单

1. **"Blender File" = `LIBRARIES`**，不是 `DATA_API`；`OUTLINER_MT_context_menu.append()` 注册，poll 返回
   False 自动置灰。
2. **`selected_ids` 只在 Outliner 上下文可解析**（5.2 裸读抛 AttributeError）；从右键菜单触发时直接可用；
   兜底写 `getattr(context, 'selected_ids', [])`。
3. **测试可用 `temp_override(selected_ids=[...])` 伪造选中**，GUI/headless 均验证通过 —— 单元测试不依赖 UI。
4. 类型判定用 **isinstance 六个具体类**（Light 用家族根类，子类 identifier 是 'PointLight' 等）；
   **必须显式排除 Object**。
5. 相机背景图 API 实名：**`camera.background_images`**（元素 `CameraBackgroundImage.image`）。
6. Image Empty 的图像在 **`obj.data`**（`empty_display_type == 'IMAGE'`）。
7. Material 扫描要经 **`obj.material_slots`**（OBJECT-linked 槽在 `data.materials` 之外）；
   GeometryNodeSetMaterial / 材质 socket 可作为进阶覆盖。
8. 节点组嵌套扫描：`NodesModifier.node_group` + `GeometryNodeGroup.node_tree` 递归；
   **API 允许成环**，必须带 visited 集合防死循环。
9. 选中执行：`select_set` 对 hide_set/hide_viewport 对象**静默失败**、对 excluded 集合对象**抛
   RuntimeError** —— 先过滤 `obj in view_layer.objects` 并按策略处理隐藏。
10. 插件形态：legacy bl_info 仍受支持（用户级目录
    `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons`，实测存在）；扩展形态需
    blender_manifest.toml + 相对导入 + `bl_ext` 命名空间，按分发需求选。
