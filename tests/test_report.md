# Select References 插件测试报告

- 日期：2026-09-02（v3，对照 docs/architecture_plan.md §10 修订 v2）
- Blender 版本：5.2.0（EEVEE，测试文件 `sel_ref_test.blend`）
- 被测代码：`select_references.py` **v1.1.0**（注册幂等化 + 新增 Curve/Curves 支持）
- 执行方式：MCP socket（端口 5001）在 Blender 内执行 `tests/test_select_references.py`，本地发送器 `tests/run_socket_test.py`
- 结果：**38 / 38 通过，0 环境错误**

## 一、用例结果

### 原有 20 条（v1 基线，全部保持有效）

| # | 类别 | 用例 | 结果 |
|---|------|------|------|
| 1 | classify | 单 Mesh 通过 | PASS |
| 2 | classify | Mesh+Material 混合拒绝（mixed） | PASS |
| 3 | classify | 含 Object 拒绝（unsupported/mixed） | PASS |
| 4 | classify | 空列表拒绝（no selection） | PASS |
| 5 | classify | PointLight 判为 Light 家族 | PASS |
| 6 | 扫描 | 共用 Mesh → 两个 linked duplicate 对象 | PASS |
| 7 | 扫描 | Camera → 其对象 | PASS |
| 8 | 扫描 | Light（PointLight）→ 其对象 | PASS |
| 9 | 扫描 | Material（DATA 槽在共用 Mesh 上）→ 两个对象 | PASS |
| 10 | 扫描 | Material（OBJECT 槽 + DATA 槽并存）→ 两对象并集 | PASS |
| 11 | 扫描 | Image → 材质直连 ∪ 嵌套组 ∪ Image Empty ∪ 相机背景图（不含无关 Cube） | PASS |
| 12 | 扫描 | GN 父组 → 挂修改器对象 | PASS |
| 13 | 扫描 | GN 嵌套子组 → 同样命中父对象 | PASS |
| 14 | 扫描 | 无关 Mesh 只含对照对象（无误报） | PASS |
| 15 | 执行 | 选中集合按名排序、去重 | PASS |
| 16 | 执行 | active 对象为排序后首个 | PASS |
| 17 | 执行 | 隐藏对象被跳过 | PASS |
| 18 | 执行 | 被排除集合对象被跳过（RuntimeError 兜底） | PASS |
| 19 | 执行 | 对照对象未被误选 | PASS |
| 20 | 端到端 | poll 在无 Outliner 上下文时拒绝（RuntimeError，预期） | PASS |

### 修订 v2 新增（§10.4）

| # | 类别 | 用例 | 结果 |
|---|------|------|------|
| 21 | T16 | get_family: legacy Curve 判为 Curve 家族 | PASS |
| 22 | T16 | 扫描: legacy Curve（Bezier，`bpy.data.curves.new('CURVE')`）→ 其 Object | PASS |
| 23 | T17 | get_family: Curves 判为 Curves 家族 | PASS |
| 24 | T17 | 夹具: Curves 数据块在 `bpy.data.hair_curves`（不在 `bpy.data.curves`） | PASS |
| 25 | T17 | 扫描: Curves（`curves_empty_hair_add` 创建）→ 其 Object | PASS |
| 26 | T18 | classify: 单 legacy Curve 通过 | PASS |
| 27 | T18 | classify: 单 Curves 通过 | PASS |
| 28 | T18 | classify: Curve+Curves 混选拒绝（不同家族根类，互不继承） | PASS |
| 29 | T18 | classify: Curve+Mesh 混选拒绝 | PASS |
| 30 | T19 | 脏状态构造（账本 = 1 正常 + 2 陈旧绘制函数） | PASS |
| 31 | T19 | 三轮 reload+register 中逐个 remove 无异常（remove no-op 语义） | PASS |
| 32 | T19 | 三轮 reload+register 后账本长度为 1 | PASS |
| 33 | T19 | 账本唯一元素 `is` 当前模块 `_draw_menu` | PASS |
| 34 | T19 | unregister 后账本为空 | PASS |
| 35 | T19 | 连续两次 register 无外抛（重复注册 ValueError 被定点防御） | PASS |
| 36 | T19 | 连续两次 register 后账本仍为 1 | PASS |
| 37 | T19 | operator 类处于已注册状态（ValueError 探针判定） | PASS |
| 38 | 清理 | 全部 SR_TEST_ 夹具无残留（含 curves/hair_curves 两集合） | PASS |

## 二、本轮（v1.1.0）修复的两个用户实测问题

### 问题 1：右键出现多个 "Select References" 菜单项
- **根因【实测】**：`register()` 无条件 `OUTLINER_MT_context_menu.append(_draw_menu)`；`importlib.reload` 保留模块 globals 但重执行源码生成**新的**绘制函数对象，旧对象残留在菜单内部列表且无任何 Python API 可枚举（`_items` 属性不存在，`__globals__` 指纹判据在 reload 下恒 False）。
- **修复**："globals 守卫账本"——模块级 `_APPENDED_DRAW_FNS`（`if ... not in globals()` 守卫初始化，跨 reload 存活）；register 前先按账本清账 + 防御性 unregister，再 append 记账；unregister 同步清账。`register_class` 同 py 类对象重复注册抛 **ValueError**（定点防御）、`unregister_class` 未注册类抛 **RuntimeError**（定点捕获）、同 bl_idname 新类对象注册由 Blender 静默替换（实测）。
- **验证**：T19 八条断言全过（含手动构造跨 reload 脏状态后清账）。

### 问题 2：材质行为"不是很对" + Image/Curves "没实现"
- **材质与 Image**：业务逻辑实测无缺口（DATA 槽/OBJECT 槽材质用例、Image 四路径用例均通过；架构师另附 GUI 排查脚本，见 architecture_plan.md §10.2）。用户观感问题大概率源于菜单重复造成的混淆（问题 1 已修）与 poll 置灰被误读。
- **Curves 确实未支持，已新增**：`bpy.types.Curve`（legacy，对象 type=='CURVE'）与 `bpy.types.Curves`（hair/几何节点曲线，type=='CURVES'）**互不继承**（实测 mro），各为一个独立家族根类；引用语义 `obj.data is target` 对两者均成立，`_objects_using_data` 零改动复用；混选 Curve+Curves 判 mixed 拒绝（符合"同类型才可选"语义）。

## 三、本轮修正的一个测试自身 bug

- **`hasattr(bpy.types, "类名")` 在 Blender 5.2 恒为 False**（探针 `tests/probe_t19.py` 实测：`register_class` 成功返回后该属性仍不存在；同 py 类重复注册抛 ValueError 反证类确已注册）。原断言"T19: operator 类处于已注册状态"据此误报 FAIL。
- **修正**：改用 **ValueError 探针**判定注册状态（重复 register 抛 ValueError ⇒ 已注册）；文件顶部清理与结尾重注册不再依赖 hasattr；reload 后补一次幂等 `register()` 保证端到端测试有 operator 可调。

## 四、需用户在 GUI 人工冒烟的点（自动化无法覆盖）

1. **菜单唯一性**：Outliner 切 "Blender File" 模式，任意数据块右键 → 应**只有一个** "Select References"（本次测试结束后插件已在会话内干净注册；若之前见过多个，本次起应消失）；
2. **材质**：mesh 指定材质 → 该材质右键 Select References 应选中对应 Object；object（OBJECT-linked 槽）指定材质 → 应选中该 object。若仍异常，按 `docs/architecture_plan.md` §10.2 的四步排查脚本经 socket 执行并回报输出；
3. **Image**：图像行右键 → 菜单项可用；引用仅为 World 时注意底部 INFO 提示（选中集为空属正确行为）；
4. **Curve / Curves**：两类曲线行右键 → 菜单项可用，点击后选中对应 Object；两者混选 → 菜单项置灰；
5. 多选同类型 → 可点；混杂类型（含 Object 行）→ 置灰。

## 五、复现/运行方式

```bash
# 1. Blender 开启且 MCP 插件 socket（端口 5001）在监听
# 2. 运行发送器：
C:\Users\EarthBugs\.workbuddy\binaries\python\versions\3.13.12\python.exe tests/run_socket_test.py
```

测试自清理所有 `SR_TEST_*` 夹具（含 `bpy.data.curves` 与 `bpy.data.hair_curves` 两集合），结束时保留插件注册供 GUI 人工冒烟。

---
## 六、v4（v1.2.0，v3 一跳语义重构，2026-09-03）

语义来源 `docs/design_v3.md`：选中**直接引用者（一跳）**，引用者是什么就选什么——
Object 引用者走视口选中（v1 逻辑不变）；非 Object 数据块引用者走大纲 Blender File
模式行高亮；World/Scene 引用者永远仅 INFO。连续触发逐级上溯，不自动多跳。

### 6.1 新语义用例表（全部 PASS）

| 输入 | objects（视口选中） | ids（大纲行高亮） | 仅 INFO |
|---|---|---|---|
| Mesh（两 linked duplicate 共用） | ObjA、ObjB | — | — |
| Material（DATA 槽） | — | 宿主 Mesh 数据块 | — |
| Material（OBJECT+DATA 槽） | OBJECT 槽对象 | DATA 槽 Mesh | — |
| Image | Image Empty | 材质（直连∪嵌套组）∪相机数据块 | World |
| Camera | 其 Object | — | Scene |
| Light / Curve / Curves | 其 Object | — | — |
| GN 父组 | 挂修改器对象 | — | — |
| GN 子组 | — | 父 GN 组数据块（一跳） | — |

### 6.2 §4 选择机制探针结论（十三轮，tests/probe_outliner_select*.py）

- `selected_ids` 只读（裸读/赋值 AttributeError，仅 temp_override 注入可见）；
  `SpaceOutliner` RNA 无选择接口；`bpy.ops.outliner.*` 无按 ID/名字选中 op；
  `filter_text` 仅子串匹配、**不支持正则**（probe9）。
- **唯一可行机制**：`use_filter_id_type + filter_id_type` 限定类型分节（消除对象
  层级同名行与父级链过选）+ 大小写敏感 `filter_text` 精确名 + `tag_redraw` 后
  `bpy.ops.wm.redraw_timer` 泵一次重绘 + `outliner.select_all`，逐名过滤累加，
  结束后还原过滤器（probe5 定稿）。
- **多目标可行（probe13，推翻 probe8/E1 的"不可行"结论）**：早期观测到"逐名过滤
  切换过滤器后已选行丢失"，实为**误判**——被过滤隐藏或处于折叠类型分节中的已选
  行只是**不可见**，选中状态本身持久（probe12/F：`show_one_level` 展开后选中恢复
  显示）；`selected_ids` 只上报可见行。最终形态：还原过滤器后调
  `bpy.ops.outliner.show_one_level(open=True)` 展开类型分节并再泵一次，全部目标
  （跨类型、任意数量）选中恢复显示与上报。
- 已知限制：子串匹配下同类型且名字包含目标名的数据块会被附带高亮（无逐行反选
  API，extras 汇报）；`users==0` 孤儿数据块不入 LIBRARIES 树（调用方 INFO 列出）。
- **未走回退方案**：大纲数据块行高亮（含多目标）全部落地，无 INFO 降级。

### 6.3 测试基建要点（v4）

- 端到端输入用 `select_datablock_rows` **真实选中输入行**（等价用户在大纲点选），
  不用 temp_override 注入 `selected_ids`——注入值会穿透嵌套 override，污染
  execute 内部对 `bpy.context.selected_ids` 的选中结果判定（实测误判 rows_ok 为空）。
- report 文本断言：bpy 类型禁止 `_op_cls()` 实例化、metaclass 使类级 monkeypatch
  `report` 不生效——直调 operator 类 `execute` 函数并以携带捕获闭包的假 self
  （`types.SimpleNamespace`）调用。
- 模块导入陷阱沿用：先 pop `sys.modules["select_references"]` 并用旧模块自身
  unregister 清账，再从工作区导入。
- 结果：**75/75 全 PASS**（含 classify 五族、v3 引用边全表、execute_selection
  防护、行高亮单/多目标、T19 注册幂等、三个验收例端到端、清理无残留）。

### 6.4 发布验证（tests/probe_publish_verify.py）

- 工作区副本已覆盖 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\select_references.py`（diff 一致、py_compile 通过）；
- 经 socket `addon_disable` + `addon_enable` 刷新（enable 前临时从 sys.path 移除
  工作区路径，避免 import 截胡）：`__file__` 指向 addons 副本、version=(1,2,0)、
  operator ValueError 探针 registered、`find_direct_referencers` /
  `select_datablock_rows` / `_ID_TYPE_FOR_FILTER` 含 IMAGE 全部就位。**通过**。

### 6.5 v4 需用户在 GUI 人工冒烟的点

1. 大纲 Blender File 模式选材质（DATA 槽）→ 右键 Select References → 对应
   Mesh 数据块行高亮（视口不选对象）；
2. 选图像 → 引用它的所有材质、相机数据块行**同时**高亮（多目标），Empty 对象
   视口选中；底部 INFO 提示 World 引用；
3. 承接 1 的结果（Mesh 行仍选中）再触发一次 → 选中两个引用对象（链式上溯）；
4. 行高亮后大纲过滤器设置（过滤文本/类型限定）已还原为触发前状态；类型分节
   被展开一层属预期（让高亮行可见的机制代价）。

---
## 附：v1（2026-09-01）修复存档

### Bug A：`hide_get` 传参错误
`obj.hide_get(vl)` → `obj.hide_get(view_layer=vl)`（view_layer 必须关键字传参）。

### Bug B（核心）：Image 扫描误报无关对象
材质/World 内嵌节点树全部重名 "Shader Nodetree" 且 `id_data` 是树自身，任何基于树名的跨 owner 身份判断必误报 → 重构为按 owner 逐材质判定（`_tree_owner_uses_image` / `_group_tree_has_image` / `_objects_using_material_image`）；GN 组树在 `bpy.data.node_groups` 内 name 唯一，防环键用 `tree.name`。
