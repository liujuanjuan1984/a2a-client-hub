## 变更摘要
- 

## 关联 Issue
- Closes #

## 变更类型
- [ ] 功能（feat）
- [ ] 缺陷修复（fix/bug）
- [ ] 重构/性能优化（refactor/perf）
- [ ] 测试（tests）
- [ ] 文档/流程（docs/chore）

## 验证证据
请粘贴本次执行的校验命令与关键输出：

```bash
# backend
cd backend && uv sync --extra dev --locked
cd backend && uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
cd backend && uv run pytest

# frontend
cd frontend && npm install
cd frontend && npm run lint
cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types
cd frontend && npm test
```

## 风险与回滚
- 风险点：
- 回滚方式：

## Checklist
- [ ] 已遵循 `AGENTS.md` 与仓库规范
- [ ] 未提交敏感信息（`.env`、密钥、token）
- [ ] 文档已同步（如适用）
