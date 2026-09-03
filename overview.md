# Select References 插件 — 任务总览

## 做了什么

为 Blender 5.2 开发了一个单文件插件 `select_references.py`：在 Outliner 的 "Blender File" 显示模式下，选中摄像机/贴图/灯光/材质/网格/几何节点后，右键菜单提供 **"Select References"**，一键精确选中场景中引用该数据块的所有 Object（支持多选；混杂类型时菜单项置灰）。与大纲搜索的模糊匹配不同，本插件选中的是 Object 本身（如选中 Mesh "Cube" 只会选中 Objects 下的 "Cube" 对象）。

## 按原计划的执行方式

按用户要求走了多 agent 流水线：
1. **调研**（GLM-5.3-flash ≈ lite agent）→ `docs/research_report.md`
2. **架构规划**（GLM-5.3 完整版 ≈ reasoning agent）→ `docs/architecture_plan.md`
3. **编码**（flash agent）→ `select_references.py`
4. **测试**：子 agent 通道两次被杀（后台 agent 状态立即变 killed），此环节**由主会话直接完成**（已向用户说明偏离）：编写测试 + 经 Blender MCP socket（端口 5001）在 Blender 内实际执行。

## 关键技术决策

- Outliner "Blender File" 模式 = `display_mode == 'LIBRARIES'`（实测，非 'DATA_API'）
- 菜单项置灰用 operator `poll()` 返回 False 实现；菜单挂 `OUTLINER_MT_context_menu`
- 类型判定用 isinstance 六具体类 + 显式排除 `bpy.types.Object`（PointLight 的 RNA 名是 'PointLight'，不能按名字符串匹配）
- **核心 bug 修复**：材质内嵌节点树全部重名 "Shader Nodetree" 且 `id_data` 是树自身，任何基于树名的跨 owner 身份判断都会误报 → 改为按 owner（逐材质/逐 World）判定；GN 组树在 `bpy.data.node_groups` 内 name 唯一，仍用 name 防环
- `hide_get` 必须关键字传参 `view_layer=vl`；隐藏/被排除集合对象在执行时过滤 + 兜底

## 修订 v1.1.0（2026-09-02，针对用户 GUI 实测反馈）

用户反馈三问题，经"架构师评估 → 编码 agent 实现 → 测试验证"流水线处理：
1. **右键菜单重复** → 根因：register 无条件 append + reload 残留旧绘制函数且无法枚举。修复："globals 守卫账本"（`_APPENDED_DRAW_FNS`）实现注册幂等，T19 八条断言验证（含跨 reload 脏状态清账）。
2. **材质行为异常** → 架构师 socket 实测业务逻辑无缺口（DATA/OBJECT 槽用例均过），判断为菜单重复造成的混淆 + poll 置灰误读；排查脚本留在 architecture_plan.md §10.2。
3. **Image/Curves "没实现"** → Image 业务层已实现（同 2 的混淆）；Curves 确实未支持，新增 Curve（legacy）与 Curves（hair/GN 曲线）双家族（互不继承），`_objects_using_data` 复用。

顺带发现并修正测试断言 bug：**`hasattr(bpy.types, 类名)` 在 5.2 恒为 False**（register_class 不挂属性），改用 ValueError 探针判定注册状态。

测试：**38/38 通过**（tests/test_report.md，原 20 条 + T16-T19 新增 18 条）。执行说明：测试子 agent 因模型配额 429 连续失败，测试执行与报告由我直接完成（子 agent 已完成 v3 测试脚本编写）。

## 修订 v1.2.0（2026-09-02，语义重构：直接引用者一跳选择）

用户实测否定 v1"终端 Object"语义，给出三个验收例子（test_image→材质 Material、Material→Mesh Cube、m2→Sphere 对象）。核心语义变为：**每次触发沿引用链向上游走一跳，直接引用者是数据块就选数据块（大纲行高亮），是对象才选对象**。设计文档：`docs/design_v3.md`。

- 引用边重构：`find_direct_referencers` 返回 {"objects","ids"}；DATA/OBJECT 槽分流（DATA→选数据块，OBJECT→选对象）；GN 改一跳（子组→父组、父组→挂修改器对象）；Image→Material/Camera 数据块∪Empty 对象，World/Scene 仅 INFO。
- **技术突破**：大纲数据块行高亮此前被认为无 API，探针（13 轮）定稿可行方案——`filter_id_type` 限定分节 + 大小写敏感 `filter_text` 精确名 + 泵重绘 + `outliner.select_all` 逐名累加 + 还原过滤器 + `show_one_level` 展开分节；被过滤隐藏的已选行状态持久（selected_ids 只上报可见行曾致误判）。
- 测试：**75/75 通过**（含三验收例端到端 + 链式上溯）；已发布到 addons 目录并刷新会话（v1.2.0）。
- 已知限制：子串匹配可能附带高亮同名前缀数据块（extras 汇报）；孤儿数据块与 World/Scene 仅 INFO。

## 交付物

| 文件 | 说明 |
|------|------|
| `select_references.py` | 插件本体（约 540 行，legacy bl_info 单文件形态） |
| `docs/research_report.md` | API 调研报告（含实测标注） |
| `docs/architecture_plan.md` | 架构设计与实现路径 |
| `tests/test_select_references.py` | Blender 内执行的 20 条断言测试（自清理夹具） |
| `tests/run_socket_test.py` | socket 发送器 |
| `tests/probe_cube.py` | 误报 bug 诊断探针 |
| `tests/test_report.md` | 测试报告：**20/20 通过** |

## 安装 / 使用

- 方式一：把 `select_references.py` 放到 `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons`，在偏好设置 Add-ons 里启用；
- 方式二：Blender 文本编辑器打开该文件直接运行。
- 当前 Blender 会话中已注册最新修复版，可直接在 Outliner "Blender File" 模式右键冒烟（GUI 人工冒烟点见 `tests/test_report.md` 第三节）。

## 后续

- 无遗留代码问题；每小时进度汇报自动化（id 756a4ed0）已取消。
- 若后续要进 GitHub 仓库，注意 `.blend` 二进制按 agent.md 的凭证纪律扫描后再提交。
