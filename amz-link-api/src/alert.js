import { log as defaultLog } from './log.js';

const DOWN_TEXT = 'Sessão Amazon caiu — rodar `npm run login` no Mac Mini';
const UP_TEXT = 'Sessão Amazon restabelecida.';

export function createAlert({
  token = '',
  chatId = '',
  fetchImpl = globalThis.fetch,
  log = defaultLog,
}) {
  let lastState = null;

  async function send(state, text) {
    if (lastState === state) return;
    lastState = state;
    log.info('alert', { state });
    if (!token || !chatId) return;

    try {
      const response = await fetchImpl(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          chat_id: chatId,
          text,
          disable_web_page_preview: true,
        }),
        signal: AbortSignal.timeout(10_000),
      });
      if (!response.ok) {
        log.error('telegram_error', { status: response.status });
      }
    } catch (error) {
      const message = token && error.message.includes(token)
        ? 'falha ao falar com o Telegram'
        : error.message;
      log.error('telegram_error', { message });
    }
  }

  return {
    sessionDown() {
      return send('down', DOWN_TEXT);
    },
    sessionUp() {
      return send('up', UP_TEXT);
    },
  };
}
