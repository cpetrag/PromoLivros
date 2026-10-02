import assert from 'node:assert/strict';
import test from 'node:test';
import { createAlert } from '../src/alert.js';
import { silentLog } from '../src/log.js';

test('avisa a queda e a volta uma vez por mudança de estado', async () => {
  const calls = [];
  const alert = createAlert({
    token: '123:ABC',
    chatId: '99',
    log: silentLog,
    fetchImpl: async (url, options) => {
      calls.push(JSON.parse(options.body).text);
      assert.equal(url.includes('123:ABC'), true);
      return { ok: true };
    },
  });

  await alert.sessionDown();
  await alert.sessionDown();
  await alert.sessionUp();
  await alert.sessionUp();

  assert.deepEqual(calls, [
    'Sessão Amazon caiu — rodar `npm run login` no Mac Mini',
    'Sessão Amazon restabelecida.',
  ]);
});

test('sem token não chama o Telegram', async () => {
  let called = false;
  const alert = createAlert({
    token: '',
    chatId: '',
    log: silentLog,
    fetchImpl: async () => {
      called = true;
      return { ok: true };
    },
  });
  await alert.sessionDown();
  assert.equal(called, false);
});
