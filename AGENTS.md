# Repository Guidelines

本指南专供参与当前项目的 coding agent 执行。在执行任务时，必须严格遵守本部分及下方的 **Agent Guidelines**。

## 1. 代码风格与命名

- **Python 代码风格**：遵循 Black（88 列）、isort、Ruff 的默认约定；模块/函数用 `snake_case`，类用 `PascalCase`。
- **FastAPI 路由**：路由函数使用清晰的动宾式命名；避免在日志中打印 token 等敏感信息。
- **验证**：提交前必须完成本仓库的回归要求（见下）。

## 2. 回归要求

每次实施代码改动后，必须完成以下回归并修复至无问题：

- `cd backend && uv sync --extra dev --locked`
- `cd backend && uv run pre-commit run --all-files --config ../.pre-commit-config.yaml`
- `cd backend && uv run pytest`

> 说明：
> - 当前项目为 Python/FastAPI/PostgreSQL 技术栈，不使用 `npm` 作为后端回归入口。
> - 如改动涉及数据库结构或迁移脚本，应在本地额外执行：`cd backend && uv run alembic upgrade head` 并验证关键接口可用。

## 3. Git 操作规范

- **受限分支**：禁止直接向 `main`/`master` 或任何 `release/*` 分支提交或 push。
- **开发分支同步**：开发分支上的新提交应及时 push 到同名远端分支，确保远端保持最新。

## 4. Commit 与 Issue 规范

- **Commit 格式**：`type(scope): summary (#issue_id)`（允许多 issue：`(#id1,#id2)`；或使用一个 tracking issue 覆盖该 PR 的全部变更）。
  - 允许的 type：`feat`, `fix`, `bug`, `refactor`, `perf`, `tests`, `chore`, `docs`。
  - 每个 commit 必须包含至少一个对应的 Issue ID（或 tracking issue ID）。
- **语言要求**：Issue 标题、描述及评论必须使用 **简体中文** 撰写（专业术语除外）。
- **Markdown 注意事项**：使用 `gh` CLI 时，若涉及多行文本，必须通过 `--body-file` 传入临时文件，禁止直接在 `--body` 中使用 `\n`。
- **豁免说明**：仅修改协作规范/流程文档（例如 `AGENTS.md`）且不涉及产品/功能/缺陷时，可直接修改，无需创建 Issue。

## 5. 本地安全与配置

- **敏感信息**：`.env`、密钥、数据库凭证严禁提交。推送前确保 `.ignore` 生效。
- **日志**：禁止在日志中打印访问令牌或敏感数据。
- **环境一致性**：PostgreSQL 连接与外部 API token 必须与 `backend/config/settings.py` 中的约定保持一致。

---

# Agent Guidelines

本部分定义 AI coding agent 的强制操作规程。**若与上方 Repository Guidelines 存在冲突，以本部分为准。**

## Development Workflow

### 1. Pre-Task Protocol

开始任何用户指派任务前，必须先做以下检查：

- **未提交改动**：检查是否存在未提交更新（`git status`）。如存在，提醒用户并询问是否需要 commit 并 push 到远端。
- **分支上下文**：检查当前分支是否为 `main`（或主分支如 `master`）。若不是：
  - 报告当前分支名与最新一条 commit 信息。
  - 询问用户确认：继续在当前分支推进，或从主分支 checkout 新分支后再开始。

### 2. Branching Strategy

- **受限分支**：严禁在 `main`（或 `master`）及任何 `release/*` 分支直接 commit 或 push。
- **任务分支**：每个任务必须在从最新主分支创建的专用分支上进行。
- **多 Issue 合并**：仅当多个 issue 强相关且属于同一主题/模块时，允许在一个分支/PR 内处理；PR 描述必须列出所有关联 issue 与覆盖的验收点。
- **命名规范**：分支名需清晰描述（如 `feat/`、`fix/`、`docs/`）。

### 3. Synchronization & Focus

- **初始同步**：仅在创建任务分支时与远端主分支同步，确保起点干净。
- **任务聚焦**：实现阶段只聚焦当前任务；不要在实现过程中合并主分支或其他分支，避免上下文污染。
- **持续远端镜像**：引入改动后应及时 commit，并立即 push 到同名远端分支（受保护分支除外：`main`/`master`/`release/*`），确保远端始终保持最新。

### 4. Safety & Collaboration

- **禁止改写历史**：严禁 `git push --force`、`git push --force-with-lease`、`git rebase`。
- **基于 merge 的冲突解决**：所有冲突解决必须使用标准 merge commit，保留协作历史。

### 5. Contribution and Review

- **Draft PR 要求**：所有由 agent 发起的变更必须以 **Draft Pull Request** 形式提交。
- **人类在环**：只有人类协作者可以：
  - 将 PR 从 Draft 改为 Ready for Review。
  - 执行将 PR 合并进受保护分支的最终 **Merge**。
- **Agent 的评审角色**：agent 可协助 code review 与给出反馈，但不得批准或合并 PR。
- **最终冲突处理**：PR 准备从 Draft 转为评审前，agent 必须确保该分支已与最新主分支完成 merge。

## Operational Standards

### 6. Automated Verification & Self-Correction

- **Push 前验证**：push 前必须执行项目的测试与构建/检查命令。
- **自我纠错闭环**：如测试或 lint 失败，agent 必须先自行分析并尝试修复，再向用户汇报。
- **Lint**：确保代码符合项目格式化/规范要求。

### 7. Documentation & Verification Evidence

- **自文档化**：每个重要变更都应同步更新相关文档（如 `README.md`）或必要的少量行内注释。
- **验证证据**：PR 描述必须包含可核验的证据（如关键测试结果或日志片段），便于非技术干系人理解变更质量。

### 8. Requirement Clarification & Issue Management

- **Issue 跟踪**：开始前先查找相关 open issue；若不存在，需创建 issue 进行跟踪。仅当变更仅涉及协作/流程文档（如 `AGENTS.md`）且不触达产品/功能/缺陷时，可不创建 issue。
- **主动澄清**：与用户确认需求边界；在编码前提供包含具体步骤与验收标准的实现计划，等待确认。

### 9. Atomic Scope & Hygiene

- **一任务一分支**：每个分支只聚焦单一 PR 范围（可评审、可回滚的变更集合）。允许链接多个强相关 issue，但禁止混入无关改动。
- **清理**：PR 合并后，应建议或执行任务分支删除。

### 10. Security & Consistency

- **安全优先**：严禁提交 secrets、API keys 或任何敏感凭证。
- **一致性**：遵循项目现有代码风格与架构模式。
