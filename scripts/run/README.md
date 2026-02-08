# Compass 一键启动脚本说明

本目录提供以 PM2 为核心的一键启动方案，实现前后端两个进程的守护与 JSON 日志输出的人类可读展示。

## 前置准备

- 已创建 `.venv` 并安装后端依赖（脚本会自动激活虚拟环境）。
- 已在 `frontend/` 安装 Node 依赖 (`npm install`)。
- 全局安装 `pm2` (`npm install -g pm2`)。

## 核心脚本

- `dev-bootstrap.sh`：环境检查、生成 CORS 配置并通过 PM2 启动 `compass-backend` 与 `compass-frontend`。
  - 若同名进程已存在且在运行，脚本先跳过端口冲突检查，再调用 `pm2 restart <name> --update-env` 完成重启。
  - 需要自定义 PM2 名称时，可设置 `COMPASS_BACKEND_PM2_NAME`、`COMPASS_FRONTEND_PM2_NAME` 环境变量；生态配置会读取这些值。
  - 如果其他程序占用了目标端口，脚本会终止并提示；可以先清理端口或使用 `--force` 强制跳过检查。
- `dev-logs.sh`：调用 `pm2 logs --json`，自动拉取最近 100 行（可自定义），再由 `pretty_logs.py` 把 JSON 转成易读文本。
- `pretty_logs.py`：Python 日志格式化器，可通过 `--columns` 自定义输出字段。
- `ecosystem.dev.config.mjs`：PM2 进程配置文件，保持前后端各一条记录，日志统一为 JSON。

> 脚本已添加到仓库，请确认具备可执行权限：`chmod +x scripts/run/*.sh scripts/run/pretty_logs.py`

## 一键启动

```bash
./scripts/run/dev-bootstrap.sh
```

可选参数：

- `--frontend-host/--frontend-port`：重写前端监听地址。
- `--backend-host/--backend-port`：重写后端监听地址。
- `--force`：忽略端口占用检查（默认遇到占用即退出）。

脚本执行后会输出最终的 CORS 白名单，并调用 `pm2 status` 查看进程概况。

## 查看日志

默认查看后端（默认名称取 `COMPASS_BACKEND_PM2_NAME`，未设置时为 `compass-backend`）：

```bash
./scripts/run/dev-logs.sh
```

查看前端：

```bash
./scripts/run/dev-logs.sh compass-frontend
```

`dev-logs.sh` 支持透传 `pm2 logs` 的其他参数，例如 `--lines 200`。
若未显式传入 `--lines`，脚本会默认添加 `--lines ${COMPASS_PM2_LOG_LINES:-100}`，方便快速查看历史日志。
默认展示字段为 `timestamp|level|app|message|request_id|user_id`，可通过 `--columns` 覆盖，例如：

```bash
./scripts/run/dev-logs.sh --columns timestamp,app,message
```

## 停止与清理

```bash
pm2 stop compass-backend compass-frontend
pm2 delete compass-backend compass-frontend
```

如需持久化 PM2 配置，请额外执行 `pm2 save`。
