记录一下目前的探讨与尝试（**暂时没有最终结论**）：

我们在后端初步探索了基于内存缓存（Memory Cache）的断点续传方案，主要改动点包括：

1. **协议层扩展**：
   - 在 `A2AAgentInvokeRequest` (`schemas/a2a_invoke.py`) 中增加了 `resume_from_sequence` (前端别名 `resumeFromSequence`) 字段，允许客户端在重连时指定需要从哪一个序号恢复流式接收。

2. **流式暂存与回放机制**：
   - 在 `a2a_invoke_service.py` 中引入了内存缓存模块 (`stream_cache/memory_cache.py`)。
   - 以 `user_message_id` 作为 `cache_key`，在下发 HTTP Streaming 和 WebSocket 消息时，将每次 yield 的事件及其累加的 `seq_counter` 写入缓存。
   - 当收到带有 `resume_from_sequence` 的恢复请求时，后端会首先从内存缓存中提取（replay）该序号之后的遗漏事件并下发。
   - 回放完毕后，继续接收上游 Gateway 的流式输出。如果在断线期间上游 Gateway 的流已经全部堆积发送，后端通过判断 `seq_counter <= resume_from_sequence` 来跳过重复的消息，从而实现无缝拼接。

**目前的未决事项与挑战**：
- **缓存可靠性**：目前仅为单机内存缓存（Memory Cache），若应用多实例部署或重启则缓存会失效，后续若要生产可用可能需要替换为 Redis 等分布式缓存。
- **前端对账配合**：前端的 `visibilitychange` (或 AppState) 唤醒监听、发送 `resumeFromSequence` 重连的逻辑尚未联调对接。
- **上游兼容性**：在极少数极端情况下（例如缓存被清理、或需要将断点续传直接透传给底层大模型），现有的代理层补数据策略是否完全足够，还有待商榷。

相关的探索代码暂时保存在本地分支 (`feat/issue-129-stream-resume`)，后续确认完整技术方案后再决定是否合入或调整。
