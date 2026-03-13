# Issue 18 评估与实施文档

## 背景

`#18` 的核心诉求仍然成立：A2A Extensions 在 `sessions` 与 `messages` 查询场景下，
当前返回结构默认携带 `raw`，导致响应体偏重，且上层调用方需要面对不必要的顶层字段。

但主干代码结构已经发生演进，原 issue 中提到的部分文件路径已经失效，不能按原描述直接实施。

## 当前主干现状

当前相关实现主要位于：

- `backend/app/integrations/a2a_extensions/service.py`
- `backend/app/integrations/a2a_extensions/session_query.py`
- `backend/app/api/routers/_extension_capability_router.py`
- `backend/app/schemas/a2a_extension.py`

其中：

- `service.py` 在成功响应时会默认归一化为 envelope，并默认注入 `raw`
- `session_query.py` 仍会解析 `result_envelope`，但当前并未用它驱动严格的响应结构
- `_extension_capability_router.py` 已是统一的 session query 路由入口
- `A2AExtensionResponse` 仍使用宽泛的 `result: Dict[str, Any]`

## 问题判断

### 仍然有效的部分

- 默认响应不应再携带体积较大的 `raw`
- 需要保留按需调试/诊断时取回原始 payload 的能力
- 需要补齐针对 `raw` 开关和分页行为的回归测试

### 已经过时的部分

- 原 issue 中提到的 `opencode_session_query.py` 已不存在
- 原 issue 中提到的 `_opencode_extension_router.py` 已不存在
- 当前用户主路径中，OpenCode session directory 已有独立裁剪逻辑，说明性能痛点部分已被上层缓解

## 本次实施目标

本次只解决功能正确性，不处理 `A2AExtensionsService` 单体文件过大的结构问题。

目标如下：

1. `sessions` / `messages` query 默认仅返回：
   - `items`
   - `pagination`
2. 仅在显式请求 `include_raw=true` 时，才返回顶层 `raw`
3. GET 与 POST 两种 query 入口都支持 `include_raw`
4. 保持现有错误码、错误响应、分页参数传递行为不回归

## 实施方案

### 1. 后端请求契约扩展

在 `backend/app/schemas/a2a_extension.py` 中为 `A2AExtensionQueryRequest` 增加：

- `include_raw: bool = False`

并在 `_extension_capability_router.py` 的 GET 查询参数中同步加入：

- `include_raw: bool = Query(False, ...)`

### 2. 服务层 envelope 收敛

在 `backend/app/integrations/a2a_extensions/service.py` 中调整成功响应归一化逻辑：

- 默认仅构造 `items` 与 `pagination`
- 当 `include_raw=True` 时，才附加 `raw`
- 不再默认透传上游 envelope 的其它顶层字段

这一步的目标是把 query 响应收敛成稳定、可预期的最小契约。

### 3. 空结果短路分支保持一致

当前 limit-without-offset 的深分页短路分支会返回：

- `raw`
- `items`
- `pagination`

本次需要将其改为与主路径一致：

- 默认只返回 `items` 与 `pagination`
- 在 `include_raw=True` 时返回 `raw`

### 4. 回归测试

补齐或更新以下测试：

- 默认不返回 `raw`
- `include_raw=True` 时返回 `raw`
- GET/POST 两种 query 入口都能透传 `include_raw`
- limit-without-offset 深分页短路分支在默认场景不返回 `raw`

## 不在本次范围内

- 不处理 `result_envelope` 的彻底重构
- 不拆分 `A2AExtensionsService`
- 不为 query 结果引入更细粒度的专用 Pydantic result model
- 不改动前端调用逻辑

## 验收标准

满足以下条件即可认为本次实现完成：

1. 默认 query 响应中不存在顶层 `raw`
2. 显式请求 `include_raw=true` 时，返回中存在顶层 `raw`
3. 现有前端与上层服务不因该变更发生行为回归
4. 后端相关 scoped tests 全部通过
