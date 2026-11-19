import assert from 'node:assert/strict';
import { test } from 'node:test';
import { silentLog } from '../src/log.js';
import { createWebhook } from '../src/webhook.js';

test('envia no formato do WAHA com a chave no cabeçalho', async () => {
  const calls = [];
  const webhook = createWebhook({
    url: 'http://127.0.0.1:8787/whatsapp/webhook',
    apiKey: 'segredo-de-teste',
    session: 'promo-livros',
    log: silentLog,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return { ok: true, status: 200 };
    },
  });

  assert.equal(await webhook.emit('poll.vote', { poll: { id: 'X' } }, 'vote_1'), true);
  const body = JSON.parse(calls[0].init.body);
  assert.deepEqual(body, { id: 'vote_1', event: 'poll.vote', session: 'promo-livros', payload: { poll: { id: 'X' } } });
  assert.equal(calls[0].init.headers['x-api-key'], 'segredo-de-teste');
});

test('repete em erro 5xx e desiste em 4xx', async () => {
  const statuses = [503, 200, 401];
  let calls = 0;
  const webhook = createWebhook({
    url: 'http://127.0.0.1:1/hook',
    apiKey: 'k',
    session: 's',
    log: silentLog,
    sleep: async () => {},
    fetchImpl: async () => {
      const status = statuses[calls++];
      return { ok: status < 300, status };
    },
  });

  assert.equal(await webhook.emit('message', {}), true);
  assert.equal(calls, 2);
  assert.equal(await webhook.emit('message', {}), false);
  assert.equal(calls, 3);
});
