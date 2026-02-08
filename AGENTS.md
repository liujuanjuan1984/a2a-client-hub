# Repository Guidelines

本指南专供参与当前项目的 coding agent 执行。在执行任务时，必须严格遵守本部分及下方的 **Agent Guidelines**。

## 1. 代码风格与命名

- **组件与逻辑**：TypeScript/React 组件使用 `PascalCase`，hooks/utilities 使用 `camelCase`。
- **样式**：Tailwind 原子类统一集中在组件文件。
- **验证**：提交前必须运行 `npm run lint`。

## 2. 回归要求

每次实施代码改动后，必须完成以下回归并修复至无问题：

- `npm install`
- `npm run lint`
- `npm run check-types`
- `npm run test -- --runInBand`

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
- **环境一致性**：PostgreSQL 与 API token 必须与 `config/settings.py` 及 `frontend/.env` 保持一致。

## 表单页约定（Create/Edit）

- Create/Edit 必须是路由页面（支持 deep link / 浏览器后退 / 生命周期隔离），并以路由级 `modal` 方式呈现（编辑时 Tabs 被遮挡，减少误触切换导致的状态丢失）。
- 对于有未保存变更的表单页，应阻止手势/返回键直接退出，改为弹确认（避免静默丢失）。

---

# Agent Guidelines

This section defines the mandatory operational protocols for AI agents. **If any conflicts exist between these rules and the guidelines above, these rules shall prevail.**

## Development Workflow

### 1. Pre-Task Protocol

Before starting any user-assigned task, the agent MUST perform the following checks:

- **Uncommitted Changes:** Check for uncommitted updates (`git status`). If any exist, remind the user and ask if they should be committed and pushed to the remote.
- **Branch Context:** Check the current branch. If it is NOT `main` (or the primary branch like `master`):
  - Report the current branch name and the latest commit message.
  - Ask the user for confirmation: proceed on the current branch or checkout a new branch from the primary branch.

### 2. Branching Strategy

- **Restricted Branches:** Direct commits or pushes to `main` (or `master`) or any `release/*` branches are strictly prohibited.
- **Task-Specific Branches:** Every task must be performed on a dedicated branch created from the latest primary branch.
- **Multi-Issue PRs:** A single branch/PR may include multiple issues when they are strongly related and belong to the same theme/module. The PR description must list all linked issues and the acceptance criteria covered.
- **Naming Conventions:** Use clear, descriptive branch names (e.g., `feat/`, `fix/`, `docs/`).

### 3. Synchronization & Focus

- **Initial Sync:** Synchronize with the remote primary branch only when creating the task branch to ensure a clean starting point.
- **Task Focus:** During development, the Agent must focus strictly on the assigned task. Do NOT merge from primary or other branches during the implementation phase to avoid context contamination.
- **Continuous Remote Mirroring:** Always commit changes as they are introduced and immediately push them to the remote branch of the same name, excluding protected branches (`main`/`master`/`release/*`). This ensures the remote workspace is always synchronized.

### 4. Safety & Collaboration

- **No History Rewriting:** Strictly prohibit `git push --force`, `git push --force-with-lease`, and `git rebase`.
- **Merge-Based Resolution:** All conflict resolutions must be handled via standard merge commits to preserve the collaborative history.

### 5. Contribution and Review

- **Draft PR Requirement:** All Agent-initiated changes must be submitted as **Draft Pull Requests**.
- **Human-in-the-Loop:** Only human collaborators are authorized to:
  - Change a PR status from "Draft" to "Ready for Review".
  - Execute the final **Merge** of any PR into protected branches.
- **Agent Review Role:** Agents may assist in reviewing PR code and providing feedback, but they cannot approve or merge PRs.
- **Final Conflict Resolution:** Before a PR is moved out of Draft, the Agent must ensure the branch is merged with the latest primary branch.

## Operational Standards

### 6. Automated Verification & Self-Correction

- **Test Before Push:** Agents must execute the project's test suite and build commands before pushing.
- **Self-Correction Loop:** If tests or linting fail, the Agent must analyze the errors and attempt to fix them autonomously before reporting to the user.
- **Linting:** Ensure all code adheres to the project's formatting standards.

### 7. Documentation & Verification Evidence

- **Self-Documentation:** Update relevant documentation (`README.md` or inline comments) for every significant change.
- **Proof of Work:** PR descriptions must include tangible evidence of verification, such as key test results or log snippets, to help non-technical stakeholders understand the changes.

### 8. Requirement Clarification & Issue Management

- **Issue Tracking:** Search for relevant open issues before starting. If none exist, create one to track the requirement, except for documentation-only changes to collaboration/process guidelines (e.g., `AGENTS.md`) that do not touch product/features/bugs.
- **Proactive Discussion:** Discuss requirements with the user to ensure clarity. Provide a proposed implementation plan with specific steps and acceptance criteria for confirmation before coding.

### 9. Atomic Scope & Hygiene

- **One Task, One Branch:** Keep each branch focused on a single PR scope (a coherent, reviewable, revertible change set). A PR scope may link multiple strongly-related issues; avoid mixing unrelated changes.
- **Cleanup:** After a PR is merged, the Agent should suggest or perform the deletion of the task branch.

### 10. Security & Consistency

- **Security First:** Never commit secrets, API keys, or sensitive credentials.
- **Consistency:** Follow existing coding styles and architectural patterns found in the project.
