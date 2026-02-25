🔍 **发现的问题 / 原始需求描述**
当前 `SessionsScreen` (会话列表页) 中的 `Async Continue` 按钮存在位置不当的问题。
- **入口错位**：在列表页触发异步指令，用户无法即时看到 AI 的生成过程或反馈，容易产生“没点中”或“程序没反应”的错觉。
- **语义冲突**：该按钮与旁边的 `Continue` (进入聊天) 在视觉和文案上过于接近，且硬编码了特定的总结指令。

🛠️ **详细实施方案建议**
1. **入口迁移评估**：
   - **核心建议**：将 `Async Continue` 从列表页卡片中移除。
   - **替代方案**：将其作为 `ChatScreen` 内部的一个快捷动作 (Quick Action) 或在 `ChatComposer` 附件菜单中展示。这样用户在触发异步继续/总结后，可以立即看到会话状态的更新。
2. **逻辑解耦**：
   - 检查 `frontend/screens/SessionsScreen.tsx` 中的 `canPromptAsync` 逻辑，移除对 `opencode` 字符串的硬编码依赖。
   - 考虑根据会话的元数据或 Extension 声明动态决定功能显隐。
3. **用户心智对齐**：若保留在列表页，应重命名为 `Async Summarize` 等更具确定性的名称，并增加 Loading 后的明确成功反馈。

🧪 **回归测试建议**
1. **链路验证**：在模拟器中点击操作，确保 `prompt_async` 请求带上了正确的 `conversation_id` 且后端返回了 202 确认。
2. **UI 冗余清理**：如果决定移除列表页入口，验证 `SessionsScreen` 的布局在不同屏幕宽度下依然平衡。

Labels: `status:todo`
