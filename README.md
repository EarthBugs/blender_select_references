# Select References（选中引用）

Blender 5.2 插件：在大纲（Outliner）**Blender File 显示模式**下，选中数据块后右键一键 **"Select References"**，精确选中**直接引用**该数据块的数据块或对象，并在大纲中高亮对应行。

[![Blender](https://img.shields.io/badge/Blender-5.2-orange)](https://www.blender.org/) [![Version](https://img.shields.io/badge/version-1.3.0-blue)](#版本历史)

## 功能

- **界面语言跟随 Blender**：菜单、提示与报告文案自动跟随 `Preferences > Interface > Language`，支持简体中文/英文两种（zh* 开头一律中文，其余英文回退）。菜单与报告实时切换；悬停提示（tooltip）在插件启用时按当前语言定型。

### 核心语义：沿引用链向上游走一跳

每次触发，结果为选中数据块的**直接引用者**（一跳）——引用者是对象就选对象，是数据块就高亮对应数据块行。连续触发即可逐级上溯完整引用链：

```
test_image(图像) → Material(材质) → Cube(网格) → Cube(对象)
```

| 你选中的 | 触发后选中的 | 原因 |
|---|---|---|
| 图像 test_image | **材质 Material**（大纲 Materials 行高亮） | 材质节点树直接引用它 |
| 材质 Material（DATA 槽） | **网格 Cube**（大纲 Meshes 行高亮） | 网格数据块的数据槽引用它 |
| 材质 m2（OBJECT 槽） | **对象 Sphere**（视口 + Objects 高亮） | 对象级材质槽引用它 |
| 网格 / 摄像机 / 灯光 / 曲线 | 引用它们的**对象** | `obj.data is 目标` |
| 几何节点子组 | **父几何节点组** | 组节点嵌套引用（一跳） |
| 几何节点父组 | 挂该修改器的**对象** | NodesModifier 直接引用 |

### 支持的输入类型（多选须同类型）

摄像机 / 贴图（Image）/ 灯光 / 材质 / 网格 / 几何节点树 / Curve（legacy 贝塞尔）/ Curves（新版毛发曲线）。

- 多选**同类型** → 菜单项可点；混杂类型（或含 Object 行）→ 菜单项**置灰**；
- 混选 Curve + Curves 也会置灰（二者是不同数据块家族）。

## 安装

要求：Blender 5.2（更低版本未测试，4.x 未验证）。

方式一（推荐）：`Edit > Preferences > Add-ons > 右上角下拉 > Install from Disk...`，选择 `select_references.py`。

方式二：把 `select_references.py` 复制到：

```
%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\
```

然后重启 Blender，并在偏好设置 Add-ons 中启用 "Select References"。

## 使用

1. 大纲切换到 **Blender File** 显示模式；
2. 选中任意支持类型的数据块行（可多选同类型）；
3. 右键 → **Select References**；
4. 结果：对象引用者被选中（视口高亮），数据块引用者在大纲对应分节行高亮，底部 INFO 提示汇总。

## 已知限制

- 大纲数据块行高亮基于 Blender 的过滤器机制实现（本插件无官方 API 可直接设置大纲选中态），副作用：触发后大纲类型分节会被展开一层；**子串匹配**可能附带高亮同名前缀的其他数据块（INFO 中以 "extras" 列出）；
- World / Scene 这类无可视选中态的引用者只在底部 INFO 提示，不进选中结果；
- `users==0` 的孤儿数据块引用者仅 INFO 列出；
- 结果为空（如选中 World）时只有一行 INFO，注意看状态栏。

## 开发与测试

```bash
# 在 Blender 内运行 76 条自动化测试（需 Blender 开启且 MCP socket 插件监听 127.0.0.1:5001）
python tests/run_socket_test.py
```

- 测试报告：[`tests/test_report.md`](tests/test_report.md)
- 开发文档（架构 / API 陷阱 / 调试指南 / 发布流程）：[`docs/development.md`](docs/development.md)
- 设计文档：[`docs/design_v3.md`](docs/design_v3.md)（语义规范）、[`docs/architecture_plan.md`](docs/architecture_plan.md)（v1 架构 + 修订）、[`docs/research_report.md`](docs/research_report.md)（API 调研）

修改插件代码后需同步到 addons 目录并重新启用（详见开发文档"发布流程"）。

## 版本历史

| 版本 | 日期 | 内容 |
|---|---|---|
| 1.3.0 | 2026-09-03 | 界面文案跟随 Blender 语言（中/英双语，运行时实时切换） |
| 1.2.0 | 2026-09-02 | 语义重构：直接引用者一跳选择 + 大纲数据块行高亮（替代 v1 的"终端对象"语义） |
| 1.1.0 | 2026-09-01 | 注册幂等化（修复右键菜单重复）；新增 Curve / Curves 支持 |
| 1.0.0 | 2026-09-01 | 首版：六类型支持，修复 Image 扫描误报、hide_get 传参 |

## 许可证

未设置（仓库作者可按需添加，如 MIT）。
