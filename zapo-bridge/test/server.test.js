import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import sharp from 'sharp';
import { SessionNotWorkingError } from '../src/errors.js';
import { silentLog } from '../src/log.js';
import { createApp } from '../src/server.js';

const API_KEY = 'chave-de-teste';
const SESSION = 'promo-livros';
const GROUP = '120363000000000000@g.us';
const calls = [];
let working = true;
let baseUrl;
let server;

const whatsapp = {
  status: () => (working ? 'WORKING' : 'STOPPED'),
  me: () => ({ id: '5511000000000@c.us' }),
  start: () => calls.push(['start']),
  stop: async () => calls.push(['stop']),
  restart: async () => calls.push(['restart']),
  qrPng: async () => null,
  groups: async () => [{ id: GROUP, name: 'Black Livros 01' }],
  participants: async () => [{ id: '111@lid', role: 'admin' }],
  lids: async () => [],
  sendText: async (chatId, text) => {
    if (!working) throw new SessionNotWorkingError();
    calls.push(['sendText', chatId, text]);
    return { id: 'true_x_3EB0AAAA' };
  },
  sendImage: async (chatId, image, caption) => {
    calls.push(['sendImage', chatId, image.width, image.height, caption]);
    return { id: 'true_x_3EB0BBBB' };
  },
  sendPoll: async (chatId, name, options, multiple) => {
    calls.push(['sendPoll', chatId, name, options, multiple]);
    return { id: 'true_x_3EB0CCCC' };
  },
  pin: async (chatId, messageId, duration) => calls.push(['pin', chatId, messageId, duration]),
  unpin: async (chatId, messageId) => calls.push(['unpin', chatId, messageId]),
};

before(async () => {
  const app = createApp({ config: { apiKey: API_KEY, session: SESSION, maxImageBytes: 1024 * 1024 }, whatsapp, log: silentLog });
  server = await new Promise((resolve) => {
    const listening = app.listen(0, '127.0.0.1', () => resolve(listening));
  });
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

after(() => new Promise((resolve) => server.close(resolve)));

function call(method, path, body, key = API_KEY) {
  return fetch(`${baseUrl}${path}`, {
    method,
    headers: { 'content-type': 'application/json', ...(key ? { 'x-api-key': key } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

test('recusa chamada sem chave', async () => {
  const response = await call('GET', `/api/sessions/${SESSION}`, undefined, '');
  assert.equal(response.status, 401);
});

test('status da sessão no formato do WAHA', async () => {
  const response = await call('GET', `/api/sessions/${SESSION}`);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, 'WORKING');
  assert.equal((await call('GET', '/api/sessions/outra')).status, 404);
});

test('sendText valida e devolve o id', async () => {
  const ok = await call('POST', '/api/sendText', { session: SESSION, chatId: GROUP, text: 'Oferta' });
  assert.equal(ok.status, 200);
  assert.equal((await ok.json()).id, 'true_x_3EB0AAAA');
  const bad = await call('POST', '/api/sendText', { session: SESSION, chatId: 'lixo', text: 'x' });
  assert.equal(bad.status, 400);
});

test('sessão caída responde 422 com o texto que o Python reconhece', async () => {
  working = false;
  try {
    const response = await call('POST', '/api/sendText', { session: SESSION, chatId: GROUP, text: 'x' });
    assert.equal(response.status, 422);
    assert.match(await response.text(), /not working/i);
  } finally {
    working = true;
  }
});

test('sendImage aceita base64 e mede a imagem', async () => {
  const jpeg = await sharp({ create: { width: 40, height: 60, channels: 3, background: '#ff0000' } }).jpeg().toBuffer();
  const response = await call('POST', '/api/sendImage', {
    session: SESSION,
    chatId: GROUP,
    caption: 'Capa',
    file: { mimetype: 'image/jpeg', filename: 'promo.jpg', data: jpeg.toString('base64') },
  });
  assert.equal(response.status, 200);
  assert.deepEqual(calls.at(-1), ['sendImage', GROUP, 40, 60, 'Capa']);
});

test('sendPoll valida opções', async () => {
  const ok = await call('POST', '/api/sendPoll', {
    session: SESSION,
    chatId: GROUP,
    poll: { name: 'Qual?', options: ['A', 'B'], multipleAnswers: true },
  });
  assert.equal(ok.status, 200);
  assert.deepEqual(calls.at(-1), ['sendPoll', GROUP, 'Qual?', ['A', 'B'], true]);
  const repeated = await call('POST', '/api/sendPoll', {
    session: SESSION,
    chatId: GROUP,
    poll: { name: 'Qual?', options: ['A', 'A'] },
  });
  assert.equal(repeated.status, 400);
});

test('pin aceita id no formato WAHA', async () => {
  const messageId = encodeURIComponent(`true_${GROUP}_3EB0ABCDEF123456`);
  const response = await call('POST', `/api/${SESSION}/chats/${encodeURIComponent(GROUP)}/messages/${messageId}/pin`, { duration: 86400 });
  assert.equal(response.status, 200);
  assert.deepEqual(calls.at(-1), ['pin', GROUP, '3EB0ABCDEF123456', 86400]);
});

test('PUT da sessão responde 501 para o script de deploy entender', async () => {
  const response = await call('PUT', `/api/sessions/${SESSION}`, { config: {} });
  assert.equal(response.status, 501);
  assert.match(await response.text(), /not implemented/i);
});

test('QR ausente não devolve imagem', async () => {
  const response = await call('GET', `/api/${SESSION}/auth/qr`);
  assert.equal(response.status, 422);
});
