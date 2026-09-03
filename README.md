# Select References（选中引用）

Blender 5.2 插件：在大纲（Outliner）**Blender File 显示模式**下，选中数据块后右键一键 **"Select References"**，精确选中**直接引用**该数据块的数据块或对象，并在大纲中高亮对应行。

[![Blender](https://img.shields.io/badge/Blender-5.2-orange)](https://www.blender.org/) [![Version](https://img.shields.io/badge/version-1.3.0-blue)](#版本历史)

## 功能

- **界面语言跟随 Blender**：菜单、提示与报告文案自动跟随 `Preferences > Interface > Language`，支持简体中文/英文两种（zh* 开头一律中文，其余英文回退）。菜单与报告实时切换；悬停提示（tooltip）在插件启用时按当前语言定型。
- **一跳语义**：每次触发，结果为选中数据块的**直接引用者**——引用者是对象就选对象（视口高亮），是数据块就高亮对应大纲行。**连续触发即可沿引用链逐级上溯**。
- 与大纲搜索的模糊匹配不同：选中的是精确的引用关系结果，不会带出"名字包含关键词"的无关行。

## 一个典型场景

假设场景里有这样一条引用链（名字纯属虚构，可替换成你自己的任何数据）：

```
图像 wood_diffuse.png ← 材质 Wood ← 网格 Cube ← 对象 Cube

材质 Metal ← 对象 Bolt   （OBJECT 槽：Bolt 这个"对象"单独指定了 Metal，它的网格上并没有）
```

在 Outliner 的 Blender File 模式下依次体验：

1. 选中图像 **wood_diffuse.png** → 右键 "Select References" → **材质 Wood** 的行被高亮（注意：不会选中任何对象）；
2. 接着选中材质 **Wood** 再触发 → **网格 Cube** 的行被高亮；
3. 再选中网格 **Cube** 触发 → **对象 Cube** 在视口和大纲中被选中——整条链走完；
4. 另一条链：选中材质 **Metal** 触发 → **对象 Bolt** 被选中（引用发生在对象级材质槽上，而非网格数据上，所以选中的是对象而不是 Bolt 的网格）。

每次只走一跳，想上溯几层就触发几次。

### 支持的输入类型与结果

| 你选中的 | 触发后选中的 | 原因 |
|---|---|---|
| 贴图（Image） | 引用它的**材质 / 摄像机**（大纲行高亮）；图像 Empty 则为**对象** | 节点树 / 背景图 / Empty 引用 |
| 材质（数据级 DATA 槽引用） | 引用它的**网格 / 曲线**（大纲行高亮） | 数据级材质槽 |
| 材质（对象级 OBJECT 槽引用） | 引用它的**对象** | 对象级材质槽 |
| 网格 / 摄像机 / 灯光 / 曲线（Curve 或 Curves） | 引用它们的**对象** | `obj.data` |
| 几何节点子组 | **父几何节点组**（大纲行高亮） | 组节点嵌套引用（一跳） |
| 几何节点父组 | 挂该修改器的**对象** | NodesModifier 直接引用 |

多选规则：**同类型**多选可触发；混杂类型（或含 Object 行、Curve 与 Curves 混选）时菜单项**置灰**。

## 安装

要求：Blender 5.2（更低版本未测试，4.x 未验证）。

方式一（推荐）：`Edit > Preferences > Add-ons > 右上角下拉 > Install from Disk...`，选择 `select_references.py`（或本仓库 Releases 页下载的 zip）。

方式二：把 `select_references.py` 复制到：

```
%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\
```

然后重启 Blender，并在偏好设置 Add-ons 中启用 "Select References"。

## 使用步骤

1. 在大纲（Outliner）右上角切换到 **Blender File** 显示模式；
2. 选中一个或多个**同类型**数据块行（如多个材质）；
3. 右键 → **Select References**（对不支持的选择该项为灰色不可点）；
4. 看结果：对象引用者在视口高亮；数据块引用者在大纲对应分节行高亮；底部状态栏 INFO 会汇总（包括无法选中的 World / Scene 引用者提示）。

## 已知限制

- 大纲数据块行高亮基于 Blender 的过滤器机制实现（本插件无官方 API 可直接设置大纲选中态），副作用：触发后大纲类型分节会被展开一层；**子串匹配**可能附带高亮同名前缀的其他数据块（INFO 中以 "extras" 列出）；
- World / Scene 这类无可视选中态的引用者只在底部 INFO 提示，不进选中结果；
- `users==0` 的孤儿数据块引用者仅 INFO 列出；
- 结果为空时只有一行 INFO，注意看状态栏。

## 开发与测试

```bash
# 在 Blender 内运行 79 条自动化测试（需 Blender 开启且 MCP socket 插件监听 127.0.0.1:5001）
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
