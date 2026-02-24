# Issue #294 评估与开发建议（Shortcuts 持久化机制）

## 1. 评估范围与基线

- 评估时间：2026-02-24
- 基线分支：`master` 最新后创建的任务分支 `feat/issue-294-assessment`
- 评估对象：[#294](https://github.com/liujuanjuan1984/a2a-client-hub/issues/294)

## 2. 结论摘要

- 需求方向合理，且**仍然有效**，但问题描述中有部分已被主干代码覆盖。
- 当前实现已基本建立“后端写入优先”，但“缓存边界 + 重置策略 + 同步策略可观测性”仍有改进空间。
- 该议题与鉴权状态重置、Web 多标签页持久化隔离高度耦合，建议与相关 issue 联动拆分落地。

## 3. 现状审查（对照 #294）

### 3.1 后端是否是可信源（Source of Truth）

已部分成立：

- 前端增删改均先调后端 API，再更新本地状态：
  - `frontend/store/shortcuts.ts` 的 `addShortcut/updateShortcut/removeShortcut`
- 首次进入聊天控制器会触发 `syncShortcuts()` 从后端拉取：
  - `frontend/hooks/useChatScreenController.ts`
- 后端已经有 `user_shortcuts` 模型与服务，列表接口返回默认项 + 用户自定义项：
  - `backend/app/services/shortcut_service.py`

结论：  
“完全依赖前端本地持久化”这一点在当前主干上**不完全成立**，但前端仍保留较重本地持久化逻辑与默认兜底。

### 3.2 前端是否仅作为缓存层

部分成立，仍有偏差：

- `shortcuts` 使用了 `zustand persist`，并把默认项与自定义项混合存储在同一个数组里。
- `syncShortcuts()` 目前是“服务端全量覆盖本地”，缺少同步状态语义（如 `lastSyncAt`、`dirty`、`source`）。
- `resetClientState()` 在鉴权失效时会执行 `useShortcutStore.clearAll()`，将本地重置为默认项：
  - `frontend/lib/resetClientState.ts`
  - 触发点：`frontend/lib/api/client.ts`、`frontend/lib/api/sse.ts` 的 401 流程

结论：  
“前端缓存化”已在方向上实现，但缓存边界定义不够清晰，且鉴权重置路径会影响快捷指令本地态。

### 3.3 `syncShortcuts` 机制是否健壮

当前为最简策略：

- 同步成功：服务端结果直接替换本地。
- 同步失败：仅记录错误，不做合并或重试策略。
- 未登录/鉴权失败时，由全局重置逻辑直接清空到默认值。

结论：  
对于“在线、后端优先”的主路径可用；但对“未登录态保留本地缓存”“异常恢复可解释性”不足，#294 的诉求仍成立。

## 4. 对 #294 实施方案的最佳实践评估

## 4.1 合理部分

- 明确后端为唯一可信源：合理，且与已有后端模型一致。
- 前端作为缓存层：合理，应进一步收敛到“可控缓存”而不是“混合持久化状态”。
- 改进同步机制：合理，但要避免过度设计。

## 4.2 需要修正/收敛的部分

- 不建议立即引入“复杂双向智能合并”：
  - 当前前端写操作已是后端优先，不存在完整的离线写队列语义。
  - 若直接做复杂 merge，容易制造隐性冲突规则。
- 建议先做“边界清晰 + 可观测 + 可回退”的增量方案：
  - 先解决 401 重置边界与持久化隔离，再决定是否需要离线写合并。

## 4.3 推荐实施顺序（增量）

1. 拆分快捷指令本地状态语义（`defaults` 与 `customs` 逻辑分层，或至少在 store 内分区）。
2. 为同步增加基础元数据（如 `lastSyncAt`、`syncSource`、`syncError` 分级）。
3. 调整 `resetClientState` 的重置边界：鉴权失效后不直接破坏 shortcuts 缓存，或改为“标记失效待重拉”。
4. 增补测试：覆盖 401、refresh 失败、重登后恢复、多标签页覆盖风险。

## 5. 高相关 Open Issues

以下 issue 与 #294 高度相关，建议联动：

1. [#199](https://github.com/liujuanjuan1984/a2a-client-hub/issues/199)  
   `[Refactor] 前端会话与鉴权状态管理收敛`  
   直接涉及 `client.ts/sse.ts/resetClientState.ts`，与 #294 的“401 导致重置边界过大”高度重叠。

2. [#223](https://github.com/liujuanjuan1984/a2a-client-hub/issues/223)  
   `[Bug] Web 多标签页 localStorage 持久化冲突治理`  
   与 #294 的“本地持久化策略风险”同源。当前虽主要提 chat/messages，但 shortcuts 使用固定 persist key，风险模式一致。

中等相关（可选联动）：

1. [#99](https://github.com/liujuanjuan1984/a2a-client-hub/issues/99)  
   离线队列能力若落地，会影响是否需要 shortcuts 的离线写入合并策略。

## 6. 建议的 #294 验收标准（可直接转开发）

1. 后端仍为 shortcuts 唯一写入源，前端不引入绕过后端的本地写路径。
2. 鉴权失效后，shortcuts 缓存不被“无条件清空为默认值”（可改为标记失效并在登录后重拉）。
3. 同步失败有清晰状态表达，UI 可区分“未同步/同步失败/已同步”。
4. 覆盖最小回归：
   - 401 + refresh 失败后行为
   - 重新登录后 shortcuts 恢复
   - Web 双标签页下 shortcuts 不互相污染（或明确当前不支持并有保护说明）

## 7. 最终判断

- #294 不是“需求失效”，而是“描述需校准 + 方案需收敛”的有效 P0/P1 级修复议题。
- 推荐先与 #199、#223 对齐边界后再推进深度同步策略，避免重复改动与策略冲突。
