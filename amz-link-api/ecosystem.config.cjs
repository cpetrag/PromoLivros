module.exports = {
  apps: [
    {
      name: 'amz-link-api',
      script: 'src/server.js',
      cwd: __dirname,
      interpreter: 'node',
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      max_restarts: 30,
      restart_delay: 5000,
      kill_timeout: 8000,
      max_memory_restart: '1500M',
      out_file: './logs/out.log',
      error_file: './logs/error.log',
      merge_logs: true,
      time: true,
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};
