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

- `service.py` 已负责 query 结果归一化与基础契约校验
- `session_query.py` 负责解析 card 中声明的 `result_envelope`
- `_extension_capability_router.py` 已是统一的 session query 路由入口
- `a2a_extension.py` 中的 query result schema 需要与路由响应保持一致

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

本次优先解决功能正确性，不处理 `A2AExtensionsService` 单体文件过大的结构问题。

目标如下：

1. `sessions` / `messages` query 默认仅返回：
   - `items`
   - `pagination`
2. 仅在显式请求 `include_raw=true` 时，才返回顶层 `raw`
3. GET 与 POST 两种 query 入口都支持 `include_raw`
4. `result_envelope` 不再只是被解析，而是实际驱动 query 结果字段抽取
5. query 结果使用更强的 schema 校验，避免多余顶层字段继续泄露
6. 保持现有错误码、错误响应、分页参数传递行为不回归

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

### 3. 用 `result_envelope` 驱动字段抽取

在 `backend/app/integrations/a2a_extensions/session_query.py` 中：

- 将 `result_envelope` 解析为显式的字段映射
- 允许使用默认字段名或别名路径
- 对非法键名和非法字段声明直接报 contract error

在 `backend/app/integrations/a2a_extensions/service.py` 中：

- 按 `result_envelope` 指定的位置提取 `items`
- 按 `result_envelope` 指定的位置提取 `pagination`
- 按 `result_envelope` 指定的位置提取 `raw`
- 当声明字段存在但类型不合法时，返回 contract error，而不是静默吞掉

### 4. 强化 query result schema

在 `backend/app/schemas/a2a_extension.py` 中新增专用 query result schema：

- `A2AExtensionQueryPagination`
- `A2AExtensionQueryResult`
- `A2AExtensionQueryResponse`

并让 query 路由使用更具体的 `response_model`，同时排除 `None` 字段。

### 5. 空结果短路分支保持一致

当前 limit-without-offset 的深分页短路分支会返回：

- `raw`
- `items`
- `pagination`

本次需要将其改为与主路径一致：

- 默认只返回 `items` 与 `pagination`
- 在 `include_raw=True` 时返回 `raw`

### 6. 回归测试

补齐或更新以下测试：

- 默认不返回 `raw`
- `include_raw=True` 时返回 `raw`
- GET/POST 两种 query 入口都能透传 `include_raw`
- limit-without-offset 深分页短路分支在默认场景不返回 `raw`
- `result_envelope` 别名映射能驱动字段抽取
- 非法 `result_envelope` 声明会被识别为 contract error
- 非法 query result（如 `items` 不是对象列表）会被 schema 拦下

## 不在本次范围内

- 不拆分 `A2AExtensionsService`
- 不改动前端调用逻辑

## 验收标准

满足以下条件即可认为本次实现完成：

1. 默认 query 响应中不存在顶层 `raw`
2. 显式请求 `include_raw=true` 时，返回中存在顶层 `raw`
3. `result_envelope` 声明可以真实影响 query 结果抽取
4. query 路由响应不会再混入未声明的额外字段
5. 现有前端与上层服务不因该变更发生行为回归
6. 后端相关 scoped tests 全部通过
