
## [2026-03-15] Refactor ChatScreen Controller (Issue #459)
- Split `useChatScreenController.ts` into multiple functional hooks:
  - `useAgentSelection`
  - `useChatNavigation`
  - `useMessageState`
  - `useChatSession`
  - `useChatScroll`
  - `useChatScreenFocusEffects`
  - `useChatInput`
  - `useChatActions`
  - `useChatStates`
  - `useA2AIntegration`
  - `useChatScreenEssentials`
  - `useChatModalStates`
  - `useChatShortcut`
- Updated `useChatScreenController` to orchestrate these hooks.
- Fixed duplicate `AllowlistError` in `frontend/lib/api/client.ts`.
- Improved null-safety and robust error handling in `frontend/screens/LoginScreen.tsx` and `frontend/lib/config.ts`.
- Verified changes with linting, type checking, and tests.

## 2026-03-15 05:43 (EDT)
- Split useChatScreenController into smaller, functional hooks (#459):
  - useMessageState: Handles message querying and block loading.
  - useChatActions: Handles user actions like send, retry, and model selection.
  - useChatScroll: Handles list scrolling and auto-bottom stickiness.
  - useA2AIntegration: Handles A2A-specific interrupts and integrations.
  - useChatSession: Handles session binding and lifecycle.
  - useAgentSelection: Handles active agent resolution.
  - useChatNavigation: Handles redirection if agent is missing.
  - useChatInput: Handles text input state and height management.
  - useChatModalStates: Manages visibility of various pickers and managers.
  - useChatShortcut: Handles shortcut interaction.
  - useChatStates: Extracts relevant state from session.
  - useChatScreenEssentials: Handles safe area and details toggle.
  - useChatScreenFocusEffects: Handles focus-based side effects.
