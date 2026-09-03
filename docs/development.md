# Select References 开发文档

面向后续维护者与 fork 贡献者：架构、关键实现机制、Blender 5.2 API 实测陷阱、测试基建、调试指南、发布流程。

> 阅读顺序建议：先看本文件的 §1 架构与 §2 语义，遇到 bug 再查 §4 陷阱清单与 §6 调试指南。语义规范的唯一来源是 [`design_v3.md`](design_v3.md)。

## 1. 架构总览

单文件插件 `select_references.py`（legacy bl_info 形态，无任何外部依赖）。三层分离：

| 层 | 内容 | 原则 |
|---|---|---|
| 纯函数层 | `find_direct_referencers` / `find_direct_referencers_many` / 各引用边分流函数 / `classify_selection` / `get_family` / `execute_selection` | 输入 bpy 数据、返回集合/元组；不碰 operator、不 report——全部可经 `temp_override` 绕过 UI 自动化测试 |
| Operator 层 | `SELECT_REFERENCING_OT_select_references`（bl_idname `object.select_references`） | 薄包装：poll 三段判定（有选中 → classify 通过 → 有可执行结果），execute 分发到纯函数 |
| 注册层 | `register` / `unregister` / `_draw_menu` | 幂等（globals 守卫账本 `_APPENDED_DRAW_FNS`），见 §4.2 |

文件索引：

```
select_references.py      插件本体（唯一分发物）
docs/
  design_v3.md            v3 语义规范（需求拆解、引用边表、选择机制探针方案）
  architecture_plan.md    v1 架构设计 + §10 修订 v2（注册幂等、Curves 实测）
  research_report.md      Blender 5.2 API 调研（含实测标注）
  development.md          本文件
tests/
  test_select_references.py   76 条自动化断言（Blender 内执行）
  run_socket_test.py          本地 socket 发送器
  test_report.md              测试报告（38 条 v1 基线 + v4 全量，含 bug 存档）
  probe_*.py                  诊断探针（见 §6.3）
  run_probe.py                探针发送器
```

## 2. 核心语义（v1.2.0）：直接引用者一跳

**每次触发，结果为选中数据块的直接引用者**——不再向终端 Object 传播（v1 语义已被用户否定）。连续触发可逐级上溯引用链。

`find_direct_referencers(target)` 返回 `{"objects": set[Object], "ids": set[ID]}`：

- `objects`：对象引用者 → 走 `execute_selection`（视口选中，含去重/排序/隐藏/被排除集合防护）；
- `ids`：非 Object 数据块引用者 → 走 `select_datablock_rows`（大纲行高亮，见 §3）。

引用边表（目标 ← 直接引用者）：

| 目标 | 引用者扫描路径 | 结果实体 |
|---|---|---|
| Image | 材质节点树直连 ∪ ShaderNodeGroup 嵌套（**按 owner 逐材质判定**，见 §4.3） | Material |
| Image | `camera.background_images` | Camera |
| Image | Image Empty（`obj.type=='EMPTY' and empty_display_type=='IMAGE' and obj.data is img`） | Object |
| Image | World 环境纹理 | World → 仅 INFO |
| Material | Mesh/Curve/Curves 的 DATA 槽（目标 ∈ `data.materials`） | 对应数据块 |
| Material | 对象 OBJECT 槽（`slot.link=='OBJECT' and slot.material is 目标`） | Object |
| Mesh/Camera/Light/Curve/Curves | `obj.data is 目标` | Object |
| GeometryNodeTree | `NodesModifier.node_group is 目标` | Object |
| GeometryNodeTree | 父组组节点嵌套（一跳，不递归） | 父 GeometryNodeTree |
| Camera | `scene.camera` | 仅 INFO |

**DATA/OBJECT 槽分流是硬要求**：`me.materials` 是数据级列表（OBJECT 覆盖不反映在 data 上），对象级引用只认 `slot.link=='OBJECT'`。二者判定互斥，混用会导致例 2/例 3 的验收失败。

## 3. 大纲数据块行高亮机制（本插件最"黑魔法"的部分）

Blender **没有**公开 API 设置大纲选中态（`selected_ids` 只读；`SpaceOutliner` 无选择接口；无按 ID 选中的 op——13 轮探针实测，见 `tests/probe_outliner_select*.py`）。可行方案是利用大纲自带的过滤器：

```
对每个待高亮数据块：
  1. space_data.use_filter_id_type = True；filter_id_type = 数据块类型（注意 Image→'IMAGE'）
  2. space_data.filter_text = 精确名（大小写敏感，子串匹配）
  3. 泵一次重绘（让过滤生效）
  4. bpy.ops.outliner.select_all(action='SELECT')  # 选中当前可见行，逐名累加
还原过滤器（filter_text、use_filter_id_type），再 outliner.show_one_level(open=True)
展开类型分节让被过滤隐藏的选中行可见
```

关键实测结论：**被过滤隐藏（或处于折叠分节中）的已选行，选中状态持久**——`selected_ids` 只上报可见行，曾据此误判"多目标必丢选"，实际多目标（跨类型、任意数量）高亮完整成立。

代价与限制：分节被展开一层；子串匹配会附带命中同名前缀数据块（INFO 以 extras 列出）；若用户原过滤器状态非默认，还原逻辑按快照恢复。

## 4. Blender 5.2 API 实测陷阱清单（排障先查这里）

以下全部为本项目实测结论，未经标注"未验证"的均为 5.2.0 LTS 实测：

1. **`hasattr(bpy.types, 类名)` 恒为 False**——`register_class` 不把类挂到 `bpy.types` 属性上。判定注册状态用 **ValueError 探针**：对同一 py 类重复 `register_class`，已注册则抛 `ValueError`。
2. **注册异常语义**：同 py 类对象重复注册抛 `ValueError`；`unregister_class` 未注册类抛 `RuntimeError`；**同 bl_idname 新类对象注册由 Blender 静默替换**（stdout 打 Info）。菜单 `append`/`remove`：`remove` 未 append 的函数是静默 no-op。
3. **菜单绘制函数无法枚举**：菜单类上无 `_items` 属性，`__globals__` 指纹判据在 reload 下恒失效（reload 保留模块 globals 字典）。因此**注册幂等只能靠模块级账本**：`if "_APPENDED_DRAW_FNS" not in globals()` 守卫初始化（普通赋值会被 reload 重置导致账本失联），register 前清账 remove、append 后记账。
4. **材质/World 内嵌节点树全部重名 `"Shader Nodetree"`** 且 `id_data` 是树自身——任何基于树名的跨 owner 身份判断必误报。图像引用判定必须**按 owner（逐材质/逐 World）**进行；嵌套组树用 `("ng", name)` 防环（组树在 `bpy.data.node_groups` 内 name 唯一）。
5. **`obj.hide_get()` 的 `view_layer` 必须关键字传参**：`obj.hide_get(view_layer=vl)`。
6. **`bpy.ops` 在 poll 拒绝时抛 `RuntimeError`**，不返回 `'CANCELLED'`。
7. **Outliner "Blender File" 模式 = `space_data.display_mode == 'LIBRARIES'`**（不是 'DATA_API'）。`context.selected_ids` 非 context 全局成员，需 Outliner area/region 上下文或 `temp_override(selected_ids=[...])` 注入（后者会穿透到被调函数内部，端到端测试时注意）。
8. **Curves（新毛发曲线）**：与 legacy `Curve` 互不继承（mro 无交集）；数据块在 `bpy.data.hair_curves`（不在 `bpy.data.curves`）；创建只能 `bpy.ops.object.curves_empty_hair_add()`，删除用 `bpy.data.batch_remove(ids=[...])`（`bpy.data.curves.remove` 抛 TypeError）。
9. **`curves_empty_hair_add` 重大副作用**：自动拉入约 57 个内置毛发/XPBD 仿真节点组，并可能在毛发附着网格上挂 NODES 修改器（曾污染用户场景的 Cube）。测试必须**事前快照节点组与非夹具对象的修改器、事后按快照还原**（v4 测试已内置该逻辑）。
10. **bpy 类型禁止实例化**：测试中需要"假 self"时构造轻量对象直调方法，不要 `SomeOperatorClass()`。

## 5. 测试基建

### 5.1 运行方式

前提：Blender 开启，MCP socket 插件监听 `127.0.0.1:5001`。

```bash
python tests/run_socket_test.py     # 发送 test_select_references.py 全文到 Blender 执行，打印 PASS/FAIL 明细
```

协议（详见 WorkBuddy 技能 `blender-mcp-socket-test`）：TCP JSON + `\0` 结尾；请求 `{"type":"execute","code":...,"strict_json":true}`；被测代码必须把汇总 dict 赋给 `result` 变量。

### 5.2 夹具纪律（踩过的坑）

- 全部夹具用 `SR_TEST_` 前缀；测试开头**预清理**历史遗留（避免 `.002` 后缀污染断言），期望值动态取夹具实际名；
- 导入陷阱：`sys.modules` 里可能已有 addons 目录加载的 `select_references` 模块——测试前必须 `sys.modules.pop` 后再从工作区 `sys.path` 导入，或先同步 addons 副本，**否则测到的是旧代码**；
- 测试结束保留插件注册状态供 GUI 人工冒烟，但所有夹具与副作用必须清零（含 §4.9 的毛发 op 副作用，有专门断言）。

### 5.3 断言结构

76 条：classify 家族判定（含混选/置灰规则）→ 引用边全表（objects/ids 分类）→ execute 防护（隐藏/被排除/排序/active）→ 大纲行高亮（单/多目标/过滤器还原）→ 注册幂等（账本三轮 reload 清账、ValueError 探针）→ 端到端三验收例 + 链式上溯 → 清理无残留。完整清单与历史 bug 存档见 `tests/test_report.md`。

## 6. 调试指南

### 6.1 常见问题 → 排查路径

| 症状 | 先查 |
|---|---|
| 右键菜单出现多个 "Select References" | §4.2/4.3 账本机制是否被改动；是否手工多次 register |
| 菜单项总置灰 | poll 三段判定：`bpy.context.selected_ids` 实际内容（Outliner LIBRARIES 模式下选中行）→ `classify_selection(ids)` 返回的原因码 |
| 选材质没反应/选错对象 | DATA/OBJECT 槽分流（§2 末）；GUI 四步排查脚本（下） |
| 大纲行没高亮 | §3 机制：`filter_id_type` 映射表（Image→'IMAGE'）、重绘泵、`show_one_level` |
| 图像/材质扫描误报无关对象 | §4.4 内嵌树同名问题——检查是否有人改回"跨 owner 收集树"的写法 |
| 会话里冒出一堆几何节点组 | §4.9 `curves_empty_hair_add` 副作用，查测试是否跳过了快照还原 |

### 6.2 GUI 排查四步脚本（在 Blender 会话内经 socket 执行）

```python
import bpy, sys
sr = sys.modules['select_references']
ids = bpy.context.selected_ids
print([type(i).__name__ + ':' + i.name for i in ids])   # 1. poll 的真实输入
print(sr.classify_selection(ids))                        # 2. poll 哪一段失败
print([o.name for o in sr.find_direct_referencers_many(ids)["objects"]])  # 3. 绕开 GUI 直接调纯函数
print([(o.name, s.link, s.material.name if s.material else None)
       for o in bpy.data.objects for s in o.material_slots])              # 4. 槽位实况
```

### 6.3 探针文件索引（tests/probe_*.py）

一次性诊断脚本，保留作机制考证与回归排查的依据：

- `probe_cube.py`：v1 期 Image 误报 bug 的定位探针（内嵌树同名问题）；
- `probe_t19.py`：`hasattr(bpy.types,…)` 失效与注册异常语义的考证；
- `probe_outliner_select[1-13].py`：大纲行高亮机制的 13 轮探针（结论沉淀在 §3，可行方案定稿于 probe5/probe12/13）；
- `probe_publish_verify.py` / `run_probe.py`：发布验证与探针发送器。

## 7. 发布流程

1. 修改工作区 `select_references.py`，`py_compile` 通过；
2. **同步覆盖 addons 副本**（用户实际加载的是它）：
   `copy select_references.py "%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\"`；
3. 会话内刷新（经 socket 或手动）：`bpy.ops.preferences.addon_disable(module="select_references")` + `addon_enable`；
4. 验证：ValueError 探针确认 operator 已注册、`bl_info["version"]` 正确、`__file__` 指向 addons 副本；
5. 跑全量测试（§5.1）；
6. git 提交（见 §8）。

注意：`addon_enable` + `bpy.ops.wm.save_userpref()` 后启用状态跨重启持久化。

## 8. 贡献与提交纪律

- **凭证纪律（最高优先级）**：见根目录 [`agent.md`](../agent.md)——任何 token/密钥绝不入库；提交前按其正则模式扫描（含 .blend 二进制）；push 凭证不落盘。
- 提交信息：简洁英文祈使句。
- `.workbuddy/`、`__pycache__/`、`*.blend1/2` 不入库（`.gitignore`）。

## 9. 版本历史

- **1.2.0**（2026-09-02）：语义重构——"终端 Object"改"直接引用者一跳"（`docs/design_v3.md`）；新增大纲数据块行高亮（13 轮探针定稿 filter 方案）。
- **1.1.0**（2026-09-01）：注册幂等化（globals 守卫账本，修复右键菜单重复）；新增 Curve/Curves 双家族支持。
- **1.0.0**（2026-09-01）：首版六类型；修复 Image 扫描误报（内嵌树同名）与 `hide_get` 传参。
