# 依赖升级分层计划（Issue #271）

## 目标

- 以低风险、可回滚的方式持续收敛前后端依赖债务。
- 避免一次性升级导致主线开发阻塞。
- 每次升级都必须附带可复现的回归证据。

## 分层策略

### Phase A（低风险，默认优先）

范围：

- 安全修复（有明确 CVE 修复版本）。
- patch/minor 级别的开发工具链依赖。
- 不改动业务语义的兼容性修复。

执行步骤：

1. 仅升级目标依赖（最小改动面）。
2. 串行执行 scoped 回归（后端先、前端后）。
3. 记录变更、风险、回滚命令。

### Phase B（中风险）

范围：

- 框架周边库 minor 升级（可能影响构建或测试行为）。
- 需要额外兼容验证的 transitive 依赖调整。

执行步骤：

1. 升级前先冻结基线（锁文件、关键测试结果）。
2. 升级后执行扩展回归（增加相关模块测试）。
3. 如果出现不稳定，先回滚再拆分升级颗粒度。

### Phase C（高风险）

范围：

- major 升级（如 FastAPI/React Native/Expo 关键链路）。
- 可能影响运行时协议、构建链或部署流程的改动。

执行步骤：

1. 独立分支、独立 PR。
2. 必须附迁移说明与回滚预案。
3. 人工评审通过后再进入主线。

## 首批低风险升级（本轮已落地）

日期：2026-02-24

### 后端（安全修复）

- `cryptography`: `46.0.3 -> 46.0.5`
- `filelock`: `3.20.1 -> 3.24.3`
- `protobuf`: `6.33.2 -> 6.33.5`
- `pyasn1`: `0.6.1 -> 0.6.2`
- `urllib3`: `2.6.2 -> 2.6.3`
- `virtualenv`: `20.35.4 -> 20.39.0`

说明：上述升级由 `pip-audit` 漏洞修复驱动，已验证 `No known vulnerabilities found`。

### 前端（测试兼容性修复）

- `minimatch` override: `^10.2.2 -> ^5.1.6`

说明：修复 Jest 覆盖率场景下 `minimatch is not a function`，确保覆盖率门禁可执行。

## 本轮回归命令

后端：

- `cd backend && uv run pre-commit run --files <changed_files...> --config ../.pre-commit-config.yaml`
- `cd backend && uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=30`
- `cd backend && uv run pip-audit`

前端：

- `cd frontend && npm run lint`
- `cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types`
- `cd frontend && npm test -- --coverage --maxWorkers=25%`

## 回滚预案

- 后端：回滚 `backend/uv.lock` 与 `backend/pyproject.toml` 到上一个稳定提交。
- 前端：回滚 `frontend/package.json` 与 `frontend/package-lock.json` 到上一个稳定提交。
- 如需局部回滚，优先按依赖包逐个回退并重跑对应 scoped 回归。
