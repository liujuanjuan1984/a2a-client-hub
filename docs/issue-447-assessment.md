# Issue #447 评估记录

## 结论

`#447` 需求仍然合理且有效，需要继续推进。

原因：

1. 当前主聊天链路虽然可以透传任意 `metadata`，但前端没有可用入口写入 `metadata.shared.model`。
2. 当前 Hub 原本只识别旧版 shared extension URI，无法直接消费 `opencode-a2a-serve` 上游 `#154` 引入的新 URI 形状。
3. 当前仓库没有任何 provider/model discovery 的路由、resolver 或 UI 数据源。

## 对 `#443` 设计原则的审查

上游 `opencode-a2a-serve` 在 `#154` 中的改动总体遵循了 `#443` 的 shared/private contract 原则：

1. 主聊天模型切换被提升为 shared contract：
   - `metadata.shared.model`
   - URI: `urn:a2a:model-selection/v1`
2. OpenCode provider/model discovery 仍保持为 provider-private extension：
   - URI: `urn:opencode-a2a:provider-discovery/v1`
   - 方法：`opencode.providers.list` / `opencode.models.list`
3. discovery 返回的是 summary，而不是 raw upstream schema，这符合“adapter 负责归一化、Hub 负责消费 canonical/summary contract”的方向。

## 本仓库发现的额外兼容性缺口

本次评估确认，`#447` 不是孤立需求，还包含一层 capability 对齐工作：

1. Hub 现有 resolver 使用旧 URI：
   - `urn:shared-a2a:session-query:v1`
   - `urn:shared-a2a:interrupt-callback:v1`
2. 上游新实现声明的是：
   - `urn:opencode-a2a:session-query/v1`
   - `urn:a2a:interactive-interrupt/v1`
3. 上游新 Agent Card 对 session-query / interrupt / provider-discovery 扩展不再强制暴露 `params.provider`，Hub 需要以 URI 作为更稳定的能力边界。

## 本轮实现

1. 后端增加了对新旧 extension URI 的兼容识别，避免最新上游接入后 shared/private capability 直接失效。
2. 后端新增 OpenCode provider/model discovery resolver 与路由：
   - `POST /me/a2a/agents/{agent_id}/extensions/opencode/providers:list`
   - `POST /me/a2a/agents/{agent_id}/extensions/opencode/models:list`
   - `POST /a2a/agents/{agent_id}/extensions/opencode/providers:list`
   - `POST /a2a/agents/{agent_id}/extensions/opencode/models:list`
3. 前端新增轻量模型选择入口，选择结果会写入当前会话的 `metadata.shared.model`，并在发送消息时自动透传。

## 仍未覆盖的范围

1. 当前模型选择只覆盖聊天主链路，不包含 session-control UI。
2. 当前模型选择状态只保留在运行中会话；应用重启后的持久化策略仍可继续优化。
3. `metadata.opencode.directory` 的产品化暴露仍属于 `#289` 范围，本轮未一并处理。
