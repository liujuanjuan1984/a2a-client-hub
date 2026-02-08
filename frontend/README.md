# A2A Universal Client

多 A2A 服务聚合客户端的前端工程，面向 Web 与移动端统一使用场景。

## 项目定位

- 前端工程位于本仓库 `frontend/`，提供注册/登录、Agent Card 管理与对话体验的 UI 与状态管理
- 目标支持维护多条 Agent Card URL 与认证凭据，并选择其一进行对话与调试
- 凭据托管与 CORS 处理必须由后端承担；后端位于本仓库 `backend/`

## 技术栈

- Expo
- React Native
- React Native Web
- Expo Router
- NativeWind
- Zustand
- TanStack Query
- TypeScript

## 相关说明

- 单仓迁入与回归：Issue #4

## 导航约定

本项目使用 Expo Router（基于 React Navigation），并在主功能区域采用 `Tabs` 作为全局主导航（Agents/Sessions/Jobs），避免新增页面时反复手工补 “Home/返回” 按钮。

- 常规页面跳转：优先使用 `router.push()` 保留历史栈（App 返回手势/返回键与 Web 浏览器后退更符合直觉）
- 仅在“重定向/不应返回到上一页”的场景使用 `router.replace()`
- 自定义 Header 场景下，返回建议采用 “能返回则返回，否则回主页” 的策略：`router.canGoBack() ? router.back() : router.replace("/")`

## 认证约定（Backend）

本项目按 a2a-client-hub 后端认证机制接入：

- Access Token 仅驻留内存（不写入 `localStorage/sessionStorage`，也不落盘到持久化 store）。
- Refresh Token 由服务端通过 `HttpOnly` Cookie 下发与轮换；前端通过 `POST /api/v1/auth/refresh` 在冷启动/刷新后恢复会话。
- Web 端请求默认携带 cookie（`credentials: 'include'`），用于 refresh cookie 续签与恢复登录态。

注意：

- 生产环境必须 HTTPS；若 refresh cookie 带 `Secure`，在 HTTP 环境下浏览器会拒绝设置/发送 cookie（仅本地调试可通过后端配置临时关闭）。
- `EXPO_PUBLIC_API_BASE_URL` 不会被业务代码改写；推荐配置为完整绝对 URL：`https://<your-api-host>/api/v1`（跨域时需配套 CORS + Cookie 策略）。
- 仅当 Web 以同源反代方式部署时，才可以使用相对路径 `/api/v1`；Native 端必须使用绝对 URL。
