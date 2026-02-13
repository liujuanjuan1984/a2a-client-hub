# Repository Guidelines

This guide is for coding agents working on this repository. Follow these rules strictly. If any conflict exists between **Repository Guidelines** and **Agent Guidelines**, **Agent Guidelines** take precedence.

## 1. Code Style and Naming

- **Python**: follow Black (88 columns), isort, and Ruff defaults. Use `snake_case` for modules/functions and `PascalCase` for classes.
- **FastAPI routes**: use clear verb-object names; never log tokens or sensitive values.
- **Validation**: run the required regressions before pushing (see below).

## 2. Required Regressions

执行回归必须按变更范围区分前后端，并修复全部失败项。

### 2.1 Scope-Based Rules (Mandatory)

- **仅 backend 变更**：只执行 backend 回归。
- **仅 frontend 变更**：只执行 frontend 回归。
- **backend + frontend 同时变更**：两套回归都执行，且**串行**执行（先 backend，后 frontend），避免并发压垮本机 I/O。

### 2.2 Development Loop (Low-Load, Recommended)

开发过程中优先使用轻量回归，降低负载：

- **Backend（按改动文件/模块）**
  - `cd backend && uv run pre-commit run --files <changed_backend_files...> --config ../.pre-commit-config.yaml`
  - `cd backend && uv run pytest <changed_tests_or_module>`
- **Frontend（按改动文件/模块）**
  - `cd frontend && npm run lint`
  - `cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types`
  - `cd frontend && npm test -- --findRelatedTests <changed_frontend_files...> --maxWorkers=25%`

### 2.3 Pre-Push Gate (Mandatory)

推送前必须完成对应范围的**全量**回归：

- **Backend changes (`backend/`)**
  - `cd backend && uv sync --extra dev --locked`
  - `cd backend && uv run pre-commit run --all-files --config ../.pre-commit-config.yaml`
  - `cd backend && uv run pytest`

- **Frontend changes (`frontend/`)**
  - `cd frontend && npm install`
  - `cd frontend && npm run lint`
  - `cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types`
  - `cd frontend && npm test -- --maxWorkers=25%`

Notes:

- 避免重复重负载检查：同一轮代码未变化时，不要重复执行等价全量检查。
- If a change touches database schema or migrations, additionally run:
  - `cd backend && uv run alembic upgrade head`
  - And verify the critical endpoints manually.

## 3. Git Rules

- **Protected branches**: never commit or push directly to `main`/`master` or any `release/*` branch.
- **Remote mirroring**: on a development branch, commit early/often and push to the remote branch of the same name so the remote stays current.

## 4. Commits and Issues

- **Commit format**: `type(scope): summary (#issue_id)`
  - Allowed types: `feat`, `fix`, `bug`, `refactor`, `perf`, `tests`, `chore`, `docs`
  - Every commit must include at least one Issue ID (or a tracking Issue ID).
- **Issue language**: Issue titles, descriptions, and comments must be written in **Simplified Chinese** (technical terms are allowed).
- **gh CLI markdown**: when creating/editing issues/PRs with multi-line text, use `--body-file`. Do not embed `\n` in `--body`.
- **Exemption**: documentation-only changes to collaboration/process docs (e.g. `AGENTS.md`) may skip creating an Issue.

## 5. Local Security and Config

- **No secrets**: never commit `.env`, keys, tokens, or DB credentials. Ensure `.gitignore` is effective before pushing.
- **Logs**: never print access tokens or other sensitive data in logs.
- **Consistency**: PostgreSQL connection and external API tokens must follow the conventions defined in `backend/config/settings.py`.

---

# Agent Guidelines

This section defines mandatory operational protocols for AI agents. If any conflicts exist between this section and the section above, this section prevails.

## Development Workflow

### 1. Pre-Task Protocol

Before starting any user-assigned task, the agent must:

- **Uncommitted changes**: run `git status`. If there are changes, notify the user and ask whether they should be committed and pushed.
- **Branch context**: if the current branch is not `main` (or primary branch like `master`):
  - report the current branch name and latest commit message
  - ask for confirmation: proceed on the current branch or create a new branch from the primary branch

### 2. Branching Strategy

- **Restricted branches**: direct commits/pushes to `main`/`master` or any `release/*` are prohibited.
- **Task-specific branches**: each task must be done on a dedicated branch created from the latest primary branch.
- **Multi-issue PRs**: allowed only when issues are strongly related and in the same theme/module; PR description must list all linked issues and acceptance criteria.
- **Naming**: use descriptive branch names (`feat/`, `fix/`, `docs/`, etc.).

### 3. Synchronization and Focus

- **Initial sync**: sync with the remote primary branch only when creating the task branch.
- **Task focus**: do not merge from primary or other branches during implementation.
- **Continuous remote mirroring**: commit changes as they are introduced and push to the remote branch of the same name (excluding protected branches).

### 4. Safety and Collaboration

- **No history rewriting**: never use `git push --force`, `git push --force-with-lease`, or `git rebase`.
- **Merge-based conflict resolution**: resolve conflicts using merge commits only.

### 5. Contribution and Review

- **Draft PR requirement**: all agent-initiated changes must be submitted as **Draft Pull Requests**.
- **Human in the loop**: only humans may mark Draft PRs as Ready for Review and merge into protected branches.
- **Agent review role**: agents may assist with reviews but cannot approve/merge.
- **Final sync before review**: before moving a PR out of Draft, ensure the branch has been merged with the latest primary branch.

## Operational Standards

### 6. Automated Verification and Self-Correction

- **Verify before push**: run the required regressions before pushing, following the scope-based rules in Section 2.
- **Self-correction loop**: if lint/tests fail, fix them autonomously before reporting.

### 7. Documentation and Verification Evidence

- **Documentation**: update relevant documentation (README or minimal inline comments) for significant changes.
- **Evidence**: PR descriptions must include concrete verification evidence (test results/log snippets).

### 8. Requirement Clarification and Issue Management

- **Issue tracking**: search for a relevant open issue before starting; create one if missing (except process-doc-only changes).
- **Clarification**: confirm boundaries and propose steps/acceptance criteria before coding when requirements are ambiguous.

### 9. Atomic Scope and Hygiene

- **One task, one branch**: keep each branch focused and reviewable; avoid mixing unrelated changes.
- **Cleanup**: after merge, suggest deleting the task branch.

### 10. Security and Consistency

- **Security first**: never commit secrets.
- **Consistency**: follow established patterns and styles in this repository.
