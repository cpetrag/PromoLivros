module.exports = {
  apps: [
    {
      name: 'zapo-bridge',
      script: 'src/server.js',
      cwd: __dirname,
      interpreter: 'node',
      exec_mode: 'fork',
      // Uma instância só: duas conexões na mesma sessão derrubam uma à outra (stream_error_replaced).
      instances: 1,
      autorestart: true,
      max_restarts: 20,
      restart_delay: 10000,
      exp_backoff_restart_delay: 5000,
      kill_timeout: 10000,
      max_memory_restart: '600M',
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
