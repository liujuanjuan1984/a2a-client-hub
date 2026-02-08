const backendName = process.env.COMPASS_BACKEND_PM2_NAME ?? "compass-backend";
const frontendName = process.env.COMPASS_FRONTEND_PM2_NAME ?? "compass-frontend";

export default {
  apps: [
    {
      name: backendName,
      cwd: "./backend",
      script: "../.venv/bin/python",
      args: "app/main.py",
      watch: false,
      autorestart: true,
      env: {
        LOG_FORMAT: "json",
      },
    },
    {
      name: frontendName,
      cwd: "./frontend",
      script: "npm",
      args:
        "run dev -- --host ${COMPASS_FRONTEND_HOST:-127.0.0.1} --port ${COMPASS_FRONTEND_PORT:-5173}",
      watch: false,
      autorestart: true,
      env: {
        NODE_ENV: "development",
      },
    },
  ],
};
