module.exports = {
  apps: [
    {
      name: 'alpaca-options-bot',
      script: 'npx',
      args: 'ts-node --transpile-only -P tsconfig.json bot.ts',
      watch: false,
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      env: {
        NODE_ENV: 'production',
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: 'logs/err.log',
      out_file: 'logs/out.log',
      merge_logs: true,
    },
  ],
};
