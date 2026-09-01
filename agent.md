# agent.md — 本项目 Agent 工作纪律

## 凭证保密纪律（最高优先级，无例外）

**本仓库（及其 GitHub 远端）绝对不允许出现任何形式的凭证**，包括但不限于：

- GitHub Token：`ghp_` / `github_pat_` / `gho_` / `ghu_` / `ghs_` / `ghr_` 开头的任何字符串
- 其他平台 API Key：`sk-` 开头（OpenAI 风格）、`AKIA` 开头（AWS）等
- 私钥块：`-----BEGIN ... PRIVATE KEY-----`
- 密码、cookie、session、数据库/服务连接串（含内嵌账号密码的 URL）
- 任何形如 `api_key = ...`、`token = ...`、`Authorization: Bearer ...` 的明文配置

### 规则

1. **对话中出现的凭证只可用于当次操作**（如调用 API、git push 的一次性 URL），绝不写入任何被 git 跟踪的文件，也不写入提交信息。
2. **提交前必须扫描**：对将要提交/推送的内容（含二进制文件，如 .blend）按上述模式做正则扫描，确认 0 命中后才可 push。一次性命令示例：

   ```bash
   git grep -I -i -E "ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|BEGIN .*PRIVATE KEY" $(git rev-list --all)
   ```

3. **凭证的正规传递方式**：环境变量（如 `BLENDER_MCP_PORT` 这类非敏感配置可进配置文件；密钥类一律 env 或 gitignore 的本地文件）。
4. **一旦发现凭证已入库**：立即到服务方吊销/轮换该凭证，再清理 git 历史（`git filter-repo` 或删库重建），历史清理完成前不得继续使用该仓库分享代码。
5. **git 凭证不落盘**：push 使用一次性带 token 的 URL 或交互式凭证管理器；`.git/config` 的 remote URL 必须保持干净（无内嵌 token）。

### 当前状态记录

- 2026-09-01：已对全部推送内容（2 个提交：`4843075`、`adc20f6`；文件 `.gitignore`、`sel_ref_test.blend` 含二进制内容）做过全量凭证扫描，**0 命中，确认干净**。
- `.workbuddy/`（本地工作数据）已在 `.gitignore` 中，永不入库。

## 其他纪律

- `.blend` 备份文件（`*.blend1`、`*.blend2`）不入库（已在 `.gitignore`）。
- 提交信息使用简洁英文祈使句。
