# 后端 mypy 分阶段门禁方案（Issue #268）

## 现状

- 后端启用了严格 mypy 配置，但历史类型债务较多，无法一次性清零。
- 若直接对全量模块启用强门禁，会显著阻塞主线开发。

## Phase-1（本轮落地）

目标：先恢复“可执行、可持续”的增量门禁。

- 新增增量脚本：`backend/scripts/mypy_changed.sh`
- CI 接入：`backend` job 执行 `uv run bash scripts/mypy_changed.sh`
- pre-commit 接入：本地 hook `backend-mypy-changed`

当前范围：

- 仅纳入 `backend/app/utils/**/*.py`（通过 `MYPY_INCLUDE_REGEX` 控制）
- 对范围外改动先提示并跳过，不阻塞提交

## 扩展策略

1. 每次选取一个已基本类型稳定的目录纳入 `MYPY_INCLUDE_REGEX`。
2. 新增目录前先本地跑一次 `uv run mypy <target_dir>` 清理显著噪音。
3. 保持“先小范围稳定，再扩大范围”的节奏，避免大规模返工。

## 常用命令

- 本地增量执行：
  - `cd backend && uv run bash scripts/mypy_changed.sh`
- 指定文件执行：
  - `cd backend && uv run bash scripts/mypy_changed.sh backend/app/utils/outbound_url.py`
- 临时扩大范围（一次性命令）：
  - `cd backend && MYPY_INCLUDE_REGEX='^backend/app/(utils|schemas)/.*\.py$' uv run bash scripts/mypy_changed.sh`
