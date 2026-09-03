# Select References 插件架构与实现路径规划（Blender 5.2）

> 依据：`docs/research_report.md`（2026-09-01，含【实测】/【文档】/【推断】标注）。本文所有技术结论以该报告为准；
> 报告中标注【推断】或未验证的点，本文均给出保守回退方案（在文中标注"回退"）。
> 本文档为纯规划：不含完整插件代码，仅含关键 API 用法小片段。

---

## 1. 总体设计

### 1.1 形态决策：单文件 legacy bl_info 插件 —— **确认**

推荐 **单文件 `select_references.py`**，理由：

1. 功能面窄：1 个 Operator + 1 个菜单 append 函数 + 若干模块级纯函数，无 UI 面板、无持久状态、无第三方依赖，拆包（多文件/扩展形态）只有成本没有收益；
2. legacy `bl_info` 在 5.2 仍受支持【实测：用户会话中 legacy 与扩展共存】，用户级安装目录
   `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons` 实测存在【实测】；
3. 扩展（Extensions）形态要求 `blender_manifest.toml` + 相对导入 + `bl_ext` 命名空间【文档】，仅在要上
   extensions.blender.org 分发时才值得——回退路径：若未来需转扩展，只需加 manifest 并把模块改为包结构，
   核心逻辑可整体平移，故现在不为它预留结构。

bl_info 建议字段：`"name": "Select References"`、`"author"`、`"version": (1, 0, 0)`、
`"blender": (5, 2, 0)`、`"location": "Outliner > Blender File 模式右键菜单"`、`"category": "Object"`。

### 1.2 数据流

```
用户在大纲 LIBRARIES 模式选中若干 ID 行 → 右键
  → OUTLINER_MT_context_menu 附加项显示 "Select References"
  → 点击 → Operator.poll（置灰判定，见 2.3）通过 → execute()
      ├─ 1. getattr(context, 'selected_ids', []) 取选中 ID（防御非 Outliner 上下文【推断】）
      ├─ 2. classify_selection(ids) → 同类型校验（isinstance 六具体类 + 显式排除 Object）
      ├─ 3. 逐 ID 调 find_referencing_objects(id) -> set[Object]（类型→扫描器分发，见 §3）
      ├─ 4. 并集 → 去重 → 按对象名排序 → execute_selection()（select_set 执行，见 §4）
      └─ 5. self.report 汇总结果（选中数 / 跳过原因），返回 {'FINISHED'} 或 {'CANCELLED'}
  → 视口选中 + 大纲 Objects 行高亮（大纲行高亮由视口选中状态自动同步，无需额外操作）
```

核心原则：**业务逻辑全部下沉为模块级纯函数**（输入 bpy 数据、返回集合/元组，不碰 operator、不 report），
Operator.execute 只做薄包装（取上下文 → 调纯函数 → 汇报）。这样测试可以完全绕过 poll 与 UI
（`temp_override(selected_ids=…)` 直接调纯函数/execute【实测】），GUI 链路只剩一层壳。

---

## 2. 模块结构：类与函数清单

```
select_references.py
├── bl_info                                  # legacy 插件元数据
├── 模块级常量 SUPPORTED_FAMILIES             # 家族根类 → 扫描器映射
├── 模块级纯函数（§2.2）                      # 可独立单测
├── SELECT_REFERENCING_OT_select_references  # 唯一 Operator（§2.1）
├── _draw_menu(self, context)                # 菜单附加绘制函数（§2.4）
├── register() / unregister()
└── if __name__ == "__main__": register()    # 便于 Text Editor 直接运行调试
```

### 2.1 Operator

```python
class SELECT_REFERENCING_OT_select_references(bpy.types.Operator):
    bl_idname = "object.select_references"
    bl_label = "Select References"
    bl_description = "选中场景中引用了所选数据块的所有对象"
    bl_options = {'REGISTER', 'UNDO'}   # 选择状态可撤销；出现在 F9/撤销信息里

    @classmethod
    def poll(cls, context) -> bool: ...
    def execute(self, context) -> set: ...   # 返回 {'FINISHED'} / {'CANCELLED'}
```

- `bl_idname` 用 `object.select_references`（动作域在对象，且避免与 Outliner 原生 op 冲突）。
- **poll 职责（置灰逻辑的唯一判定层）**，全部返回 False 时菜单项自动置灰【文档】：
  1. `ids = getattr(context, 'selected_ids', None)`；为 `None` 或空列表 → False（未选中任何项 → 可见但灰）；
  2. `sd = getattr(context, 'space_data', None)`；`sd is None or sd.type != 'OUTLINER'
     or sd.display_mode != 'LIBRARIES'` → False（"Blender File" 模式 = `LIBRARIES`【实测更正】）；
  3. `classify_selection(ids)` 失败（含不支持类型 / 类型混杂 / 含 Object）→ False；
  4. 通过 → True。
- **execute 职责**：不重复 poll 的抛错逻辑，但要做运行时防御（poll 与 execute 之间状态可能变化）：
  1. 再取一次 `selected_ids`（`getattr` 默认 `[]`【推断：从 keymap 等其他入口触发时可能不存在】），
     `classify_selection` 失败 → `report({'WARNING'}, 原因)` → `{'CANCELLED'}`；
  2. 逐 ID 调 `find_referencing_objects`，单 ID 扫描异常被捕获记录（见 §5.5），不中断整体；
  3. 并集为空 → `report({'INFO'}, "没有找到引用所选数据块的对象")` → `{'FINISHED'}`（操作本身成功）；
  4. 调 `execute_selection(context, targets)`；按返回的 selected/hidden/excluded 分级 report（§4.3）；
  5. 整体兜底 `try/except Exception` → `report({'ERROR'}, …)` → `{'CANCELLED'}`。
- execute 内**不要**再对 `poll` 调用判失败就 return——测试经 `temp_override` 直接调 execute（无
  Outliner space_data）时必须仍能工作【实测：override 可注入 selected_ids，GUI/headless 均通过】。
  即 execute 只依赖 `selected_ids`，不依赖 `space_data`。

### 2.2 模块级纯函数

| 函数 | 签名 | 职责 |
|---|---|---|
| `get_family` | `(id_obj) -> type \| None` | 对单个 ID 判家族：`isinstance` 六具体类
`Camera / Image / Light / Material / Mesh / GeometryNodeTree`【实测：Light 子类 identifier 是 'PointLight' 等，不能用类型名字符串匹配】；**`isinstance(x, bpy.types.Object)` 显式排除**【实测：Object 也是 ID，且 LIBRARIES 模式选中 Object 行会进 selected_ids】；非六类 → None。注意 `GeometryNodeTree` 与 `ShaderNodeTree` 平级，判定只针对六具体类【实测】 |
| `classify_selection` | `(ids: list) -> tuple[bool, str, type \| None, list]` | `(ok, reason, family, typed_ids)`：空列表 → (False, "no selection")；逐个 `get_family`，出现 None（含 Object）→ (False, "unsupported/mixed")；家族不一致 → (False, "mixed")；全一致 → (True, "", family, ids)。**poll 与 execute 共用此函数** |
| `find_referencing_objects` | `(target_id) -> set[bpy.types.Object]` | **核心分发器**：按 `get_family(target)` 查 `SUPPORTED_FAMILIES` 路由到 `_scan_*`（§3），返回引用者对象并集。未知类型 → 返回空集（poll 已拦，此处防御） |
| `_objects_using_data` | `(data) -> set` | Mesh/Camera/Light 共用：遍历 `bpy.data.objects`，`obj.data is data`【实测：三类 obj.data 直接指向数据块；多用户/linked duplicate 各自独立出现，逐一返回】 |
| `_objects_using_material` | `(mat) -> set` | 遍历 `bpy.data.objects` → `obj.material_slots` → `slot.material is mat`【实测：必须扫 material_slots，OBJECT-linked 槽在 obj.data.materials 之外】 |
| `_objects_using_image` | `(img) -> set` | Image 扫描（§3.4）：材质节点（含嵌套组）∪ image empty ∪ 相机背景图 |
| `_worlds_using_image` | `(img) -> list[bpy.types.World]` | 单独探测 World 引用（§3.4 注），供 execute 做 INFO 提示，不进对象集合 |
| `_shader_trees_with_image` | `(img) -> list[ShaderNodeTree]` | 遍历 `bpy.data.materials`（各 `mat.node_tree`）+ 递归 `ShaderNodeGroup.node_tree` 子树，收集含 `ShaderNodeTexImage / ShaderNodeTexEnvironment` 且 `.image is img` 的树【实测路径】 |
| `_objects_with_shader_trees` | `(trees: list) -> set` | 对每个树反查其所属材质/组，再经 `_objects_using_material` 或 GN 修改器入口映射到 Object |
| `_objects_using_gn_tree` | `(tree) -> set` | 遍历 `bpy.data.objects` → `modifiers` → `mod.type == 'NODES'` → `_tree_references(mod.node_group, tree, visited)`【实测入口】 |
| `_tree_references` | `(tree, target, visited: set) -> bool` | 递归：`tree.name in visited` → False（**防环【实测：API 允许 A↔B 成环】**）；`visited.add(tree.name)`；`tree is target` → True；对 `node.bl_idname == 'GeometryNodeGroup'` 且 `node.node_tree` 非空递归【实测嵌套路径】 |

性能辅助（可选，见 §3.6）：`_iter_all_objects()`（`bpy.data.objects` 的薄封装，留缓存挂点）。

> 签名约定：所有 `_scan_*` 返回 `set`，`find_referencing_objects` 保持题目要求的
> `(id) -> set[Object]`。World 引用因映射不到 Object，用独立函数 + report 提示（见 §3.4 注）。

### 2.3 置灰逻辑放哪一层 —— 结论

**只放 Operator.poll**（`poll` 返回 False → 菜单项自动灰死【文档】），不在 `_draw_menu` 里手工
`row.enabled`。理由：单一判定源，避免 draw 与 poll 判定漂移；`display_mode == 'LIBRARIES'` 限制也放在
poll（其他 Outliner 显示模式下同样置灰，可见但不响应，符合"必须可见但置灰"的产品要求）。

### 2.4 菜单注册

```python
def _draw_menu(self, context):
    # 不做任何可用性判断：poll 失败时项仍绘制、自动置灰（可见但不可点）
    self.layout.operator(SELECT_REFERENCING_OT_select_references.bl_idname,
                         text="Select References")

def register():
    bpy.utils.register_class(SELECT_REFERENCING_OT_select_references)
    bpy.types.OUTLINER_MT_context_menu.append(_draw_menu)

def unregister():
    bpy.types.OUTLINER_MT_context_menu.remove(_draw_menu)
    bpy.utils.unregister_class(SELECT_REFERENCING_OT_select_references)
```

`OUTLINER_MT_context_menu` 是 2.92 起的正规扩展点【文档】，具备标准 `append/remove`【实测】。

---

## 3. 类型 → 引用解析矩阵

统一入口 `find_referencing_objects(target)`；`SUPPORTED_FAMILIES = {
bpy.types.Camera: _objects_using_data, bpy.types.Light: _objects_using_data,
bpy.types.Mesh: _objects_using_data, bpy.types.Material: _objects_using_material,
bpy.types.Image: _objects_using_image, bpy.types.GeometryNodeTree: _objects_using_gn_tree }`。

### 3.1 Mesh / Camera / Light（同一路径）

- 扫描：`for obj in bpy.data.objects: if obj.data is target → 收集`。
- **遍历 `bpy.data.objects` 而非 `context.view_layer.objects`**：后者只含当前 View Layer，会漏其他
  View Layer 的引用者【推断，报告 4.1】。回退：若实测发现跨 View Layer 场景异常，仍保持全量遍历（只读安全），
  仅在选中阶段按 View Layer 过滤（§4）。
- Light 家族：`obj.data is <PointLight/SpotLight/...>` 天然成立，无需区分子类【实测】。

### 3.2 Material

- 扫描：`obj.material_slots` → `slot.material is target`（DATA 槽与 OBJECT 槽统一处理，`slot.material`
  在两种 link 下都返回实际引用【实测】）。**禁止**只扫 `obj.data.materials`【实测会漏 object-linked】。
- 进阶覆盖（Phase 2，可选，报告标注【推断】）：GN 树内 `GeometryNodeSetMaterial` 节点与
  `NodeSocketMaterial` 的 `default_value`。实现时在 `_tree_references` 的遍历中顺带收集材质引用。
  回退：Phase 1 不做，仅文档标注"节点内材质引用暂未覆盖"（风险清单 §7）。

### 3.3 GeometryNodeTree

- 入口：`bpy.data.objects` → `obj.modifiers` → `mod.type == 'NODES'` → `NodesModifier.node_group`【实测】。
- 递归：`_tree_references(tree, target, visited)`，**visited 以 node_group 的 `name` 为 key**
  （`bpy.data.node_groups` 内 name 唯一；用 Python `id()` 会在文件重载后失效，name 更稳）。
- **防环是硬要求**：API 允许直接把 A→B→A 成环【实测】，无 visited 必死循环。
- 直接引用（`mod.node_group is target`）由递归第一层 `tree is target` 覆盖，无需特判。

### 3.4 Image（引用点最多的类型）

| 引用点 | API 路径 | 归属 Object |
|---|---|---|
| 材质图像纹理 | `bpy.data.materials[*].node_tree` 及嵌套 `ShaderNodeGroup.node_tree` 中
`ShaderNodeTexImage.image` / `ShaderNodeTexEnvironment.image is img`【实测】 | 材质 → `_objects_using_material` |
| Image Empty | `obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE' and obj.data is img`【实测：图像挂 obj.data】 | 该 empty 自身 |
| 相机背景图 | `obj.type == 'CAMERA'` → `obj.data.background_images` → 元素 `.image is img`
【实测：集合挂在 Camera 数据块上，元素类 CameraBackgroundImage】 | 使用该 Camera 的 Object |
| World 环境 | `bpy.data.worlds[*].node_tree` 中同款纹理节点【实测路径】 | **映射不到任何 Object** |

- **World 的设计决策**：World 被场景引用而非被 Object 引用，无法进入"引用该图像的 Object 并集"。
  处理：`_objects_using_image` 不含 World；execute 阶段额外调 `_worlds_using_image(img)`，命中则
  `report({'INFO'}, "World '<name>' 也引用了该图像（World 不属于对象，无法自动选中）")`。
  回退：若产品接受不提示，可整体去掉此探测（扫描只读，去掉无副作用）。
- 材质遍历范围：`bpy.data.materials` 全量（不能只看场景对象槽位上的材质【实测/报告 4.3】）。
  VSE 序列条目、Light 节点树内图像【报告未验证项 3】不覆盖（§7）。

### 3.5 库链接数据

- `id.library is not None` 判链接【推断：本地对象实测为 None】。**扫描全部只读，对链接数据块安全**【推断】；
  LIBRARIES 模式正是展示外部库的主视图，必须假设用户在此选中链接块。
- 链接 Object 作为引用者：`select_set` 在其位于 View Layer 时可用【推断】；选中阶段不做 library 特判，
  与本地对象走同一 `execute_selection`（excluded/hidden 过滤天然覆盖异常情形）。
  回退：若实测链接对象 select_set 抛错，把错误并入 §4.3 的 excluded 汇总分支。

### 3.6 性能

- 规模假设：`bpy.data.objects` 千级、材质百级——每类型一次 O(N) 遍历在毫秒级，**Phase 1 不做缓存、
  不做 users 剪枝**（报告 8：扫描无需关心 users；0 用户孤儿数据不出现在常规视图但保守起见照样扫，
  代价可忽略）。【回退】若用户反馈大文件卡顿，再做两项优化：
  1. 多选 Image / GN 时先建一次性缓存（`dict[id.name -> set[Object]]`，遍历 bpy.data 一轮回填）再查表；
  2. `users == 0 and not use_fake_user` 的材质/世界跳过节点扫描（选中态数据块 users ≥ 1，不影响正确性，
     属纯剪枝，需加单测验证多用户与 fake user 路径【实测：users/use_fake_user 行为已验证正常】）。

---

## 4. 选中执行算法

### 4.1 流程（`execute_selection(context, targets) -> (selected, hidden, excluded)`）

```python
vl = context.view_layer
ordered = sorted(targets, key=lambda o: o.name)      # 去重已由 set 完成；按对象名排序（需求）
for o in vl.objects:
    o.select_set(False)                               # 先全清（headless 实测 select_all 亦可用，二选一）
for obj in ordered:
    if obj.name not in vl.objects:                    # 不在当前 View Layer（典型：所在集合被 exclude）
        excluded.append(obj); continue                # select_set 对其抛 RuntimeError【实测】，预先拦下
    if obj.hide_get(vl) or obj.hide_viewport:         # 两种隐藏都会静默失败【实测】
        hidden.append(obj); continue
    obj.select_set(True)
    selected.append(obj)
if selected:
    vl.objects.active = selected[0]                   # 激活对象（按排序第一个）；对隐藏对象 active 也可行【实测】
```

- **去重**：扫描阶段返回 `set` 天然去重；linked duplicate 共享 data 的多个 Object 各自独立出现、
  各自 select_set，无联动问题【实测】。
- **active 选取**：排序后第一个**成功选中**的对象；`selected` 为空时不设置 active。
- 隐藏对象策略：**跳过并汇报，不主动取消隐藏**（改 `hide_set(False)` 有副作用、且 hidden 状态是
  View Layer 级用户数据；保守回退：若用户强烈要求"总是选中"，再加一个插件偏好
  `unhide_on_select: bool`，默认 False）。

### 4.2 大纲 Objects 行高亮

视口选中状态会自动同步到大纲 Objects 行高亮，**不做任何大纲行操作**（需求明确"绝不是大纲搜索那种
模糊匹配行"——本方案从不触碰 `outliner.*` 高亮/搜索 API，仅产生真实 Object 选中状态）。

### 4.3 反馈（report 汇总）

| 情形 | 级别 | 文案（示例） |
|---|---|---|
| 正常选中 N 个 | `INFO` | `已选中 3 个引用对象` |
| 无任何引用者 | `INFO` | `没有找到引用所选数据块的对象` |
| hidden 非空 | `WARNING` | `M 个对象因被隐藏而跳过：A, B` |
| excluded 非空 | `WARNING` | `K 个对象位于被排除的集合中，无法选中：C` |
| World 引用图像 | `INFO` | `World 'X' 也引用了该图像（不属于对象）` |
| 单 ID 扫描异常 | `WARNING` | `扫描 <数据块名> 时出错，已跳过：<异常>` |
| 兜底异常 | `ERROR` | `Select References 执行失败：<异常>` |

INFO/WARNING 都会进 Info Editor 与状态栏；选中数 > 0 就返回 `{'FINISHED'}`，仅分类失败/兜底异常返回
`{'CANCELLED'}`。另：报告为【推断】的"从非 Outliner 入口触发时 selected_ids 可能不存在"——execute 用
`getattr` 防御后取不到即 `CANCELLED`，行为安全。

---

## 5. 边界与错误处理

| # | 场景 | 行为 |
|---|---|---|
| 5.1 | `selected_ids` 空 / 混杂 / 含 Object / 含不支持类型（如 Collection、Action、World、ShaderNodeTree） | poll 置灰（可见不可点）；execute 再校验一次，`{'CANCELLED'}` + WARNING。**判类只认六具体类，Object 显式排除**【实测依据】 |
| 5.2 | 库链接数据块被选中 | 扫描照常（只读）；引用者按 §3.5 处理；不做修改型操作 |
| 5.3 | 多用户数据（users > 1 / fake user） | 天然支持：逐 Object 扫描与 users 无关【实测 users 行为正常】；0 用户孤儿数据也扫（保守） |
| 5.4 | GN 循环引用（A↔B） | `visited` 按 node_group.name 防环【实测成环可能】；单测含显式成环用例 |
| 5.5 | 扫描途中属性缺失/异常（如某材质无 node_tree：`use_nodes=False` 时 node_tree 可能为 None） | 逐 ID try/except：记录、跳过该 ID、继续其余；execute 汇总 WARNING。所有节点树访问前判 `tree is not None` |
| 5.6 | 所选数据块无任何引用者 | INFO 提示，`{'FINISHED'}`，不改变当前选择 |
| 5.7 | execute 期间选择上下文异常（如 View Layer 被切换） | 整体 try/except 兜底 → ERROR + `{'CANCELLED'}`；不产生半选状态（先 deselect 后逐个 select，中断时最多"少选"，不误选） |
| 5.8 | 多 View Layer | 扫描覆盖全 `bpy.data.objects`；选中只作用于**当前** View Layer；其他 View Layer 的引用者既不报错也不选中（不列入 hidden/excluded，属正常范围外）——文档与提示文案注明此语义 |
| 5.9 | 注册/注销 | `unregister` 严格逆序 remove/unregister；重复注册由 Blender 抛错自然暴露，不吞异常 |

日志：开发期可用 `print`（控制台可见）；发布版仅依赖 `self.report`，不写文件、不污染用户目录。

---

## 6. 测试计划（给测试 agent 的可执行清单）

### 6.1 两种执行方式

- **方式 A（本机 GUI + MCP socket，端口 5001）**：Blender 5.2 GUI 会话中经 socket 执行脚本
  （参考 `blender-mcp-socket-test` 技能：TCP 直连执行 Python）。要求：
  - 夹具全部自建（`SR_TEST_` 前缀），**结束必须清理**（删除夹具对象/数据块、恢复改动过的现有对象状态）；
  - 开始前记录 `set(bpy.data.objects.keys)` 等基线，结束时按基线兜底清理；
  - GUI 会话额外做一次**人工冒烟**：大纲 LIBRARIES 模式右键确认菜单项出现/置灰/可点（自动化无法驱动
    真实右键菜单，报告未验证项 1）。
- **方式 B（headless）**：`blender --background --factory-startup --python tests/test_sel_ref.py`
  （`--factory-startup` 保证干净环境【实测】；`bpy.context.selected_ids` 裸读会 AttributeError【实测】，
  **所有选中注入一律走 `temp_override`**【实测 GUI/headless 均通过】）。
- 启用插件（headless）：`bpy.ops.preferences.addon_enable(module="select_references")` 或
  `addon_utils.enable("select_references")`（参数是模块名【实测】）。
- **测试不依赖 bpy.ops 调用 operator**：直接 `temp_override(selected_ids=[...])` 后调用
  `select_references.find_referencing_objects(...)` / `execute_selection(...)` 或 Operator 类的
  `execute`（bpy.ops 路径会触发 poll 的 space_data 检查，headless 无 Outliner 可 override，绕开）。
  GUI（方式 A）下若 socket 注入了完整窗口上下文，可再补 `bpy.ops` 路径用例。

### 6.2 测试夹具构造（自建，不依赖用户场景）

`SR_TEST_` 前缀，`bpy.data.*.new()` 构造：

- 2 个 Mesh（`SR_TEST_MESH_A/B`）+ 引用它们的 2 个 Object（linked duplicate：2 个对象共享 A）+ 1 个无关 Sphere；
- 1 个 Camera 数据 + 1 个 Camera Object（做背景图用）+ 1 个 image empty；
- 1 个 PointLight + 1 个 SpotLight（家族一致性用）+ 各自 Object；
- 2 个 Material：一个进 Mesh A 的 DATA 槽，一个用 `slot.link = 'OBJECT'` 设为 OBJECT 槽覆盖【实测路径】；
- 1 个 Image（`bpy.data.images.new`）；材质节点 `ShaderNodeTexImage.image = img`；
- GN 链：`SR_TEST_GN_ROOT`（含 Group 节点指向 `SR_TEST_GN_CHILD`）挂到某 Object 的 NODES 修改器；
  另建 A↔B 成环组验证防环（直接以 Python 设 `node.node_tree` 成环【实测 API 允许】）；
- 1 个被 exclude 的集合（`view_layer.layer_collection.children['...'].exclude = True`）内放 1 个引用 Mesh A 的对象。

### 6.3 断言清单（纯函数级 + 端到端）

| # | 用例 | 断言 |
|---|---|---|
| T1 | Mesh 单选 | `find_referencing_objects(mesh_a)` 含 mesh_a 的 Object（含 linked duplicate 双方），不含 Sphere |
| T2 | Camera | Camera Object 命中 |
| T3 | Light 家族 | PointLight 的 Object 命中；`classify_selection([point_light, spot_light])` 判**同家族通过**（isinstance 语义） |
| T4 | Material | DATA 槽对象与 OBJECT-linked 槽对象**都**命中（漏任一即 fail） |
| T5 | Image 并集 | 材质引用对象 ∪ image empty ∪ 相机背景图所在 Object 全命中；`_worlds_using_image` 对 World 单独命中 |
| T6 | GN 直引 | 挂 NODES 修改器且 node_group 为 ROOT 的 Object 命中 |
| T7 | GN 嵌套 | 仅引用 CHILD 的 Object 命中（经 ROOT→CHILD 递归） |
| T8 | GN 成环 | A↔B 互指，函数**在限时内返回**（防环生效），结果正确 |
| T9 | 多选并集 | `temp_override(selected_ids=[mesh_a, mesh_b])` → 并集正确、无重复 |
| T10 | 混合类型拒绝 | `[mesh_a, material_1]`、`[mesh_a, cube_object]`（含 Object）、`[collection]`（不支持）→ `classify_selection` 均 False |
| T11 | 空选 | `[]` → False |
| T12 | 对照组 | 执行后无关 Sphere `select_get()` 为 False |
| T13 | 执行算法 | `execute_selection` 后：目标全 `select_get()` True、active 为排序第一个、excluded 集合对象与隐藏对象进对应跳过列表且不抛未捕获异常 |
| T14 | 端到端（GUI, 方式 A） | `temp_override(selected_ids=[mesh_a])` 后调 Operator.execute；断言 `view_layer.objects.selected` 与 report；再人工右键冒烟（菜单可见/置灰/点击） |
| T15 | 清理验证 | 测试结束后 `SR_TEST_` 前缀在 `bpy.data.objects/materials/images/node_groups/meshes/...` 中为空 |

---

## 7. 风险与限制清单

1. **引用点覆盖不全（by design, Phase 1）**：VSE 序列条目图像【报告未验证项 3】、Light 节点树内图像、
   粒子系统、文本对象字体、修改器纹理（如 Displace 的 texture 槽）、场景级引用（World/合成器节点树）
   不映射为 Object 或暂不覆盖；GN 树内 `GeometryNodeSetMaterial` / 材质 socket 引用为 Phase 2。
2. **World 引用不可选**：World 引用图像只能提示、无法产生 Object 选中（§3.4）。
3. **库链接**：真实跨 .blend 链接库未实测【报告未验证项 4】；扫描只读应安全，选中阶段对链接对象行为
   按【推断】处理，若异常并入 excluded 汇总（回退方案 §3.5）。
4. **被排除集合对象无法选中**（Blender 硬限制，RuntimeError 已实测）：跳过 + WARNING，不绕行。
5. **隐藏对象静默失败**（实测）：跳过 + WARNING，不自动取消隐藏（保守策略，偏好项为回退扩展）。
6. **多 View Layer**：仅当前 View Layer 生效（§5.8），其他层引用者不选中不报错。
7. **菜单链路未自动化**：真实右键 → operator 触发无 UI 自动化手段【报告未验证项 1】，靠文档佐证 + 人工冒烟。
8. **LIBRARIES 模式外的置灰**：其他 Outliner 显示模式（含 SCENES/VIEW_LAYER）菜单项同样置灰——这是
   `display_mode == 'LIBRARIES'` 限制的直接结果，符合需求但需向用户说明（需求只要求 Blender File 模式可用）。
9. **`selected_ids` 上下文依赖**：非 Outliner 入口（keymap 等）取不到（【推断】），execute 防御后
   CANCELLED；插件 Phase 1 不注册任何 keymap，风险仅存在于未来扩展。
10. **0 用户孤儿数据**：不会出现在 LIBRARIES 常规树中但可能经 ORPHAN_DATA 等途径被选中，扫描照样处理（保守）。

---

## 8. 给编码 agent 的有序实现步骤

1. 建 `select_references.py` 骨架：`bl_info`（`"blender": (5, 2, 0)`）+ 空 `register/unregister` + `__main__` 入口。
2. 实现 `get_family` 与 `classify_selection`（isinstance 六具体类 + 显式排除 `bpy.types.Object`；
   单测 T3/T10/T11 先行）。
3. 实现 `_objects_using_data`（Mesh/Camera/Light）与 `SUPPORTED_FAMILIES` 分发器
   `find_referencing_objects`（单测 T1/T2）。
4. 实现 `_objects_using_material`（`material_slots` 路径，单测 T4）。
5. 实现 `_objects_using_gn_tree` + `_tree_references`（visited 防环，单测 T6/T7/T8）。
6. 实现 `_shader_trees_with_image` / `_objects_using_image` / `_worlds_using_image`
   （材质嵌套组递归 + image empty + `camera.background_images`，单测 T5）。
7. 实现 `execute_selection`（deselect → 排序逐个 select_set → excluded/hidden 过滤 → active，
   单测 T12/T13）。
8. 实现 `SELECT_REFERENCING_OT_select_references`：poll（space_data/`LIBRARIES`/classify 三段）+
   execute（薄包装 + §4.3 分级 report + 兜底 try/except）。
9. 实现 `_draw_menu` 与 `OUTLINER_MT_context_menu.append/remove` 注册。
10. 写 `tests/test_sel_ref.py`（方式 B headless 全量断言 + 夹具 + 清理），`--factory-startup` 跑通。
11. 方式 A（GUI socket 5001）：安装到 `%APPDATA%\...\5.2\scripts\addons` 并启用，socket 跑 T14，
    人工右键冒烟（出现/置灰/点击 → 视口 + 大纲高亮）。
12. 用现有 `sel_ref_test.blend`（Camera/Cube/Light）做真实场景复核：选中 Mesh/Camera/Light 各一次，
    验证选中与高亮。
13. 回归清理：确认 T15（无 `SR_TEST_` 残留）、`unregister` 幂等、Info 报告文案符合 §4.3。
14. （可选 Phase 2）GN 树内材质 socket / SetMaterial 覆盖 + Image 多选缓存优化（§3.6）。

**交付文件清单**：`select_references.py`（根目录）、`tests/test_sel_ref.py`、本架构文档
（`docs/architecture_plan.md`，已存在）；可选 `README.md`（安装与使用说明）。

---

## 9. 给编码 agent 的注意事项（≤10 条）

1. "Blender File" 模式判 `space_data.display_mode == 'LIBRARIES'`，**不是** `DATA_API`（实测更正）。
2. 类型判定只用 `isinstance` 六具体类，且**必须先显式排除 `bpy.types.Object`**；点光源 RNA 名是
   `'PointLight'`，禁止用类型名字符串比较。
3. Material 只认 `obj.material_slots` 的 `slot.material`；只扫 `obj.data.materials` 会漏 OBJECT-linked 槽（实测）。
4. GN 递归必带 `visited`（以 node_group `name` 为 key）——API 允许 A↔B 成环，无防护会死循环（实测）。
5. `select_set`：对 `hide_set`/`hide_viewport` 对象**静默失败**、对被排除集合对象**抛 RuntimeError**
   （均实测）——先查 `obj.name in view_layer.objects` 与隐藏状态再选中，跳过项进 report 汇总。
6. 扫描遍历 `bpy.data.objects`（不是 `view_layer.objects`），但选中只作用于当前 View Layer。
7. execute 里取 `selected_ids` 一律 `getattr(context, 'selected_ids', [])` 防御；execute 不依赖
   `space_data`（headless/temp_override 测试路径需要）。
8. 测试一律 `temp_override(selected_ids=[...])` 注入（GUI/headless 实测可行），直接调纯函数或
   Operator.execute，不走 bpy.ops；headless 加 `--factory-startup`。
9. 相机背景图在 `camera.background_images`（元素 `.image`）；image empty 的图像在 `obj.data`
   （`empty_display_type == 'IMAGE'`）——两处 API 名实测确认，勿凭旧版本记忆写。
10. 置灰只依赖 operator.poll（返回 False 自动灰），菜单 draw 不手写 `enabled`；`unregister` 必须严格逆序。

---

## 10. 修订 v2（2026-09-01，针对用户实测反馈）

> 依据：Blender 5.2.0 LTS 本机 socket 实测（MCP 端口 5001），全部标注【实测】；无法实测的 GUI 环节给出
> 排查步骤。本章节只修订 §2.4（菜单注册）、§3（类型矩阵）、§6（测试计划），**不推翻任何既有架构**。

### 10.0 架构判断总览

**不需要推翻架构。** 三个问题均不触及核心设计（模块级纯函数 + 薄 Operator + poll 单一判定源）：

| 问题 | 定性 | 修订范围 |
|---|---|---|
| 1. 菜单项重复 | 注册层缺陷（register 无幂等性），非架构缺陷 | 仅 `register`/`unregister` 两函数（约 +20 行） |
| 2. 材质行为"不对" | 业务逻辑实测无缺口；残留菜单**不跑旧逻辑**（见 10.2） | 无代码改动，GUI 排查步骤（10.3/10.6） |
| 3a. Image "没实现" | 扫描已实现且有测试（T5），疑为 GUI 层误判 | 无代码改动，排查步骤 |
| 3b. Curves 未支持 | 属实（原需求六类型不含） | `_SUPPORTED_FAMILY_ROOTS`/`SUPPORTED_FAMILIES` 各 +1 条目 |

### 10.1 问题一：右键出现多个 "Select References"

**根因确认【实测】**：`register()`（select_references.py:508-511）无条件
`OUTLINER_MT_context_menu.append(_draw_menu)`；`importlib.reload` 保留模块 `__dict__`（同一字典对象）
并重新执行源码 → 每轮 reload 产生**新的** `_draw_menu` 函数对象，旧对象仅存于菜单内部列表，
`unregister()` 的 `remove(新函数对象)` 移除不到它 → 每轮 reload+register 净增一个菜单项。

**两个必须修正的用户侧推断【实测】**：

1. **残留条目并不执行"旧版本逻辑"**：reload 保留模块字典 → 旧函数的 `__globals__ is` 当前模块
   `__dict__`（实测 id 相同）。旧函数体内 `SELECT_REFERENCING_OT_select_references.bl_idname` 按名
   查共享 globals，命中的是**新类**；operator 类层面 reload+register 也不会重复——同 bl_idname 的新
   类对象注册时 Blender 自动 unregister previous（实测 stdout：
   `Info: ... 'object.select_references' has been registered before, unregistering previous`）。
   因此残留条目点击后执行的是**最新逻辑**，"材质行为不对"不能用它解释（见 10.2）。
2. **残留的实际危害有限**：视觉重复、draw 时多余的 `layout.operator` 调用、以及 unregister 后残留项
   指向已注销 operator（draw 时报错）。不影响选中结果的正确性。

**用户提议清理方案的评估：不可行，否定【实测】**：

- `bpy.types.OUTLINER_MT_context_menu` 上**不存在 `_items` 属性**（`hasattr` 实测 False；`dir()` 全
  列表中亦无任何可枚举 draw 函数的公开属性）。Python 侧没有任何 API 能枚举菜单已 append 的函数，
  该判据无从落地；
- 即使可枚举，`f.__qualname__ == "_draw_menu"` 且 `f.__globals__ is not globals()` 的判据在 reload
  场景下**恒为 False**（新旧函数共享同一 globals 字典，见上）。

**替代方案（推荐，已实测可行）——"globals 守卫账本"**：

```python
if "_APPENDED_DRAW_FNS" not in globals():      # reload 保留 globals，账本跨 reload 存活【实测】
    _APPENDED_DRAW_FNS = []

def register():
    # ① 防御性注销：unregister 里 unregister_class 对未注册新类抛 RuntimeError、
    #    remove(未 append 的函数) 静默 no-op【实测】，整体 try/except 吞掉即可
    try:
        unregister()
    except Exception:
        pass
    # ② 按账本清除历史 append 的 draw 函数（含跨 reload 残留）
    for old in _APPENDED_DRAW_FNS:
        try:
            bpy.types.OUTLINER_MT_context_menu.remove(old)
        except Exception:
            pass
    _APPENDED_DRAW_FNS.clear()
    # ③ 注册 operator：同 py 类对象重复注册抛 ValueError【实测】→ 防御；
    #    同 bl_idname 新类对象静默替换【实测】→ 无需处理
    try:
        bpy.utils.register_class(SELECT_REFERENCING_OT_select_references)
    except ValueError:
        pass
    # ④ append 并记账
    bpy.types.OUTLINER_MT_context_menu.append(_draw_menu)
    _APPENDED_DRAW_FNS.append(_draw_menu)

def unregister():
    for old in _APPENDED_DRAW_FNS:
        try:
            bpy.types.OUTLINER_MT_context_menu.remove(old)
        except Exception:
            pass
    _APPENDED_DRAW_FNS.clear()
    try:
        bpy.utils.unregister_class(SELECT_REFERENCING_OT_select_references)
    except RuntimeError:        # 未注册类【实测 RuntimeError，非静默】
        pass
```

- **守卫写法是硬要求**：`_APPENDED_DRAW_FNS = []` 若为普通赋值，reload 重执行源码会把它重置为空
  （账本清空 → 残留失联）。必须用 `if ... not in globals()` 或 `globals().setdefault` 守卫。
  【实测：reload 后非源码键存活（哨兵实验），源码普通赋值会被重置】
- 兜底账本（若未来转扩展/包形态 reload 语义变化）：`bpy.app.driver_namespace`（reload 不影响的持久
  dict）存放同一列表；本修订在真实插件上已用 driver_namespace 模拟三轮 reload+register+清账验证流程
  无异常【实测】。当前形态首选 globals 守卫，零外部状态。
- `menu.remove(f)` 语义【实测】：对未 append 的函数不报错（静默 no-op），多次 remove 同一函数不报错
  ——账本清理无需精确去重判断。
- §5.9 表中"重复注册由 Blender 抛错自然暴露，不吞异常"一条**由本修订废止**：改为 ①③ 的定点防御。

### 10.2 问题二：材质行为"不是很对"

**业务逻辑无缺口【实测】**：`_objects_using_material`（select_references.py:153-166）逐对象扫
`material_slots`，DATA 槽与 OBJECT-linked 槽统一经 `slot.material` 判定（OBJECT 覆盖只反映在
slot 上）。自动化测试 T9/T10 两条材质用例均通过。扫描结果正确。

**"残留旧菜单跑旧代码"假设已被否定**（10.1 修正点 1）。剩余可能原因按概率排序：

1. **菜单重复造成的视觉混淆**：多个同名条目，用户不确定点了哪个、或把置灰/可点状态看混；
2. **GUI 选中上下文与测试注入不同**：poll 三段判定中任一段在真实 GUI 下失败都会置灰，用户可能把
   "点击置灰项无反应"理解为"行为不对"；混杂多选（如 Material 行 + Object 行同时选中）时返回
   unsupported/mixed；
3. **OBJECT-linked 槽的用户预期差**：槽位 link='OBJECT' 时大纲/属性面板显示的材质与
   `slot.material` 的覆盖关系不直观，用户删除/改派材质后期望与实际槽位状态不一致。

**GUI 排查步骤（在 Blender 会话内经 socket 依次执行，需人工先在 Outliner LIBRARIES 模式选中材质行）**：

```python
import bpy, sys
sr = sys.modules['select_references']
ids = bpy.context.selected_ids
# 步骤 1：读真实选中——确认 poll 的输入（类型与名字）
print([type(i).__name__ + ':' + i.name for i in ids])
# 步骤 2：定位 poll 失败段
print(sr.classify_selection(ids))        # 期望 (True, '', Material, [...])；否则原因码即答案
# 步骤 3：绕开 GUI 直接调纯函数，比对扫描结果
targets = sr.find_referencing_objects(bpy.data.materials['目标材质'])
print(sorted(o.name for o in targets))
# 步骤 4：核对期望对象的槽位实况
print([(o.name, s.link, s.material.name if s.material else None)
       for o in bpy.data.objects for s in o.material_slots])
```

- 步骤 2 失败 → poll/选中问题（问题一残留清理 + 用户操作方式）；步骤 3 与 GUI 表现不符 → 才是真正
  的扫描缺口，届时回报具体场景再修。**按当前证据，预计步骤 2/3 全过，无需改扫描代码。**

### 10.3 问题三：Image 与 Curves

**Image**：扫描已完整实现（材质直连∪嵌套组∪Image Empty∪相机背景图，select_references.py:249-274）
且有测试 T5/T11 覆盖，业务层"没实现"不成立。GUI 观感"压根没实现"的可能原因与排查同 10.2（菜单残留
混淆 / poll 置灰 / 结果为空时只有一行 INFO 容易被忽略——典型如测试图像仅被 World 引用，此时 report
"没有找到引用所选数据块的对象"而 World 提示易漏看）。排查时在 10.2 脚本基础上把目标换成 Image，
另查 `sr._worlds_using_image(img)` 输出。

**Curves 确认未支持【实测】**：现 `get_family` 对 Curves 数据块返回 None。修订规格：

- `bpy.types.Curve`（legacy，对象 type=='CURVE'）与 `bpy.types.Curves`（新版 hair/几何节点曲线，对象
  type=='CURVES'）**互不继承**【实测：双方 `__mro__` 互不包含，Curves 直接继承 ID】→
  `_SUPPORTED_FAMILY_ROOTS`（select_references.py:59）改为：

  ```python
  _SUPPORTED_FAMILY_ROOTS = (Camera, Image, Light, Material, Mesh, GeometryNodeTree,
                             Curve, Curves)
  ```

  `bpy.types.Curve` / `bpy.types.Curves` 加入顶部 `from bpy.types import (...)` 导入列表。
- 路由表 `SUPPORTED_FAMILIES`（select_references.py:321-328）增加两条：
  `Curve: _objects_using_data, Curves: _objects_using_data`。
- **`_objects_using_data` 直接复用，无需任何特判**【实测】：两种曲线类型的 `obj.data is target` 均
  成立（legacy Curve 与 Curves 实例分别验证 `obj.data is data` 为 True）；扫描遍历的是
  `bpy.data.objects`（不遍历数据块集合），与 Curves 数据块的存放位置无关。
- `classify_selection` 无需改动（按家族根类一致性判定自然生效）；注意 **Curve 与 Curves 混选应判
  mixed 拒绝**（二者是不同家族根类，符合"同类型才可选"语义，保持现状即可）。
- 【实测备注】Curves 数据块不在 `bpy.data.curves` 枚举中（存放于 `bpy.data.hair_curves`）；插件扫描
  不受影响，但测试夹具管理要注意（见 10.7 第 4 条）。

### 10.4 测试断言清单新增（并入 §6.3）

| # | 用例 | 断言 |
|---|---|---|
| T16 | legacy Curve 扫描 | Bezier 曲线数据块 → `find_referencing_objects` 命中其 Object（`obj.data is target`） |
| T17 | Curves 扫描 | 经 `bpy.ops.object.curves_empty_hair_add()`（需活跃 mesh 对象）创建 Curves 对象 → 命中；`get_family(data) is bpy.types.Curves` |
| T18 | 曲线家族判定 | `classify_selection([curve_data])`、`classify_selection([curves_data])` 各自通过；`[curve_data, curves_data]` → mixed 拒绝 |
| T19 | 菜单幂等（**须在 Blender 内执行**，方式 A socket） | 三轮 `importlib.reload` + `register()`：每轮前 `_APPENDED_DRAW_FNS` 逐个 remove 无异常；三轮后账本长度为 1 且其唯一元素 `is` 模块当前 `_draw_menu`；随后 `unregister()` 后账本为空；同模块不 reload 连续 `register()` 两次：第二次 operator 注册的 ValueError 被防御捕获，账本仍为 1 |
| T20 | GUI 人工冒烟（方式 A） | 清账 + 干净 register 后，Outliner LIBRARIES 模式右键菜单**仅出现一个** "Select References"；按 10.2 排查脚本复核 Material / Image 行为并记录 selected_ids 实况 |

夹具补充：曲线类夹具用 `SR_TEST_` 前缀；legacy Curve 用 `bpy.data.curves.new(name, 'CURVE')`；Curves
只能经 operator 创建（`bpy.data.curves.new` 的 type 枚举仅 CURVE/SURFACE/FONT【实测】）。

### 10.5 实现注意事项与风险点（给编码 agent）

1. **守卫写法是幂等方案的生命线**：`_APPENDED_DRAW_FNS` 必须用 `if ... not in globals()` 守卫；
   普通赋值会被 reload 重置、账本失联（实测原理见 10.1）。
2. **定点 try/except，不吞一切**：`register_class` 同 py 类对象重复注册抛 **ValueError**【实测】、
   `unregister_class` 未注册类抛 **RuntimeError**【实测】、同 bl_idname 新类对象注册**静默替换且打印
   Info**【实测】——分别按上面代码定点捕获；不要在 register 外层再包一个大 try/except。
3. **勿再尝试 `_items`**：菜单内部函数列表无 Python 可见枚举入口（实测 False），任何基于
   `_items`/`__globals__` 指纹的清理方案都不可靠；账本是唯一可维护状态。
4. **Curves 夹具的创建与清理 API 均特殊**【实测】：创建只能 `bpy.ops.object.curves_empty_hair_add()`
   （前置：有活跃 mesh 对象）；清理用 `bpy.data.batch_remove(ids=[data])`——
   `bpy.data.curves.remove()` 会抛 TypeError（期望 Curve 类型，拒绝 Curves）；对象删除后残留的
   users==0 数据块也可 `bpy.data.orphans_purge()` 兜底。测试中勿用 `bpy.data.curves` 查找 Curves
   夹具（其枚举不含 Curves，见 10.3）。
5. **`_SUPPORTED_FAMILY_ROOTS` 顺序无关但要全**：isinstance 逐个匹配，Curve 与 Curves 都列出，
   漏一个就回到"该类型 get_family 返回 None"的现状。
6. **保持 poll/execute 零改动**：新增类型走纯函数与路由表，poll 的 classify_selection 与 execute
   分发逻辑自动覆盖；不要为此改 Operator。
7. **GUI 层不可自动化**：右键菜单项计数、Material/Image 的真实 selected_ids 读取只能人工 + socket
   辅助（10.2 脚本）；T19 的账本断言是菜单幂等的主要自动防线，T20 人工冒烟兜底。
8. **版本与文档**：`bl_info["version"]` 升为 (1, 1, 0)，bl_description 与模块 docstring 的支持类型
   列表补 Curve/Curves；§2.4 与 §5.9 的旧注册描述以本章为准。
9. **回归确认**：修订后重跑全量 20 条旧测试（headless 方式 B）+ 新增 T16-T18，确认账本机制对既有
   流程零影响（测试脚本内部的 importlib.reload 正是复现路径，旧测试通过即验证幂等）。
