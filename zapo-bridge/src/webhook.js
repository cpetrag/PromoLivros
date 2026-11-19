import { randomUUID } from 'node:crypto';

const RETRY_DELAYS_MS = [1000, 3000, 9000];
const REQUEST_TIMEOUT_MS = 10_000;

// Entrega em fila única: a ordem dos votos importa para o painel de enquetes.
export function createWebhook({ url, apiKey, session, log, fetchImpl = fetch, sleep = defaultSleep }) {
  let chain = Promise.resolve();

  async function deliver(body) {
    for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
      try {
        const response = await fetchImpl(url, {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-api-key': apiKey },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        });
        if (response.ok) return true;
        // 4xx do painel é rejeição definitiva (chave, sessão, payload); repetir não muda nada.
        if (response.status >= 400 && response.status < 500) {
          log.error('webhook_rejected', { event: body.event, status: response.status });
          return false;
        }
        log.warn('webhook_failed', { event: body.event, status: response.status, attempt });
      } catch (error) {
        log.warn('webhook_failed', { event: body.event, message: error.message, attempt });
      }
      if (attempt < RETRY_DELAYS_MS.length) await sleep(RETRY_DELAYS_MS[attempt]);
    }
    log.error('webhook_gave_up', { event: body.event, id: body.id });
    return false;
  }

  return {
    emit(event, payload, id = randomUUID()) {
      const body = { id, event, session, payload };
      const delivery = chain.then(() => deliver(body));
      chain = delivery.catch(() => false);
      return delivery;
    },
  };
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
