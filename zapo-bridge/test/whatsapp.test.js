import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { test } from 'node:test';
import { silentLog } from '../src/log.js';
import { createPollStore } from '../src/poll-store.js';
import { createWhatsApp, SessionStatus } from '../src/whatsapp.js';

const GROUP = '120363000000000000@g.us';

function fakeClient() {
  const client = new EventEmitter();
  client.sent = [];
  client.registered = true;
  client.connect = async () => {};
  client.disconnect = async () => client.emit('connection', { status: 'close', reason: 'client_disconnected' });
  client.getState = () => ({ registered: client.registered });
  client.getCredentials = () => ({ meJid: '5511000000000:3@s.whatsapp.net' });
  client.message = {
    send: async (jid, content) => {
      client.sent.push({ jid, content });
      return { id: `3EB0${String(client.sent.length).padStart(16, 'A')}` };
    },
  };
  client.group = {
    queryAllGroups: async () => [{
      jid: GROUP,
      subject: 'Black Livros 01',
      participants: [{ jid: '111@lid', lid: '111@lid', phoneNumber: '5511999999999@s.whatsapp.net', isAdmin: true, isSuperAdmin: false }],
    }],
    queryGroupMetadata: async () => ({
      participants: [
        { jid: '111@lid', isAdmin: true, isSuperAdmin: false },
        { jid: '222@lid', isAdmin: false, isSuperAdmin: true },
        { jid: '333@lid', isAdmin: false, isSuperAdmin: false },
      ],
    }),
  };
  return client;
}

function setup() {
  const client = fakeClient();
  const emitted = [];
  const webhook = { emit: async (event, payload, id) => { emitted.push({ event, payload, id }); return true; } };
  const pollStore = createPollStore(':memory:');
  const whatsapp = createWhatsApp({ client, log: silentLog, pollStore, webhook });
  return { client, emitted, pollStore, whatsapp };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test('mapeia o ciclo de conexão para os status do WAHA', async () => {
  const { client, whatsapp } = setup();
  assert.equal(whatsapp.status(), SessionStatus.STOPPED);
  client.emit('auth_qr', { qr: 'qr-teste', ttlMs: 20000 });
  assert.equal(whatsapp.status(), SessionStatus.SCAN_QR_CODE);
  assert.ok((await whatsapp.qrPng()).subarray(1, 4).toString() === 'PNG');
  client.emit('connection', { status: 'open' });
  assert.equal(whatsapp.status(), SessionStatus.WORKING);
  assert.equal(await whatsapp.qrPng(), null);
  assert.deepEqual(whatsapp.me(), { id: '5511000000000@c.us' });
});

test('motivo fatal deixa a sessão parada em FAILED', () => {
  const { client, whatsapp } = setup();
  client.emit('connection', { status: 'open' });
  client.emit('connection', { status: 'close', reason: 'failure_banned', isLogout: false });
  assert.equal(whatsapp.status(), SessionStatus.FAILED);
});

test('queda comum agenda reconexão', () => {
  const { client, whatsapp } = setup();
  client.emit('connection', { status: 'open' });
  client.emit('connection', { status: 'close', reason: 'stream_error_force_login', isLogout: false });
  assert.equal(whatsapp.status(), SessionStatus.STARTING);
});

test('envio fora de WORKING responde como sessão caída', async () => {
  const { whatsapp } = setup();
  await assert.rejects(() => whatsapp.sendText(GROUP, 'oi'), { status: 422 });
});

test('enquete devolve id no formato WAHA e guarda as opções', async () => {
  const { client, pollStore, whatsapp } = setup();
  client.emit('connection', { status: 'open' });
  const sent = await whatsapp.sendPoll(GROUP, 'Qual?', ['A', 'B'], true);
  assert.match(sent.id, /^true_120363000000000000@g\.us_3EB0/);
  assert.equal(client.sent[0].content.selectableCount, 0);
  assert.equal(pollStore.has(sent.key.id), true);
});

test('voto vira poll.vote com nomes, mesmo quando o zapo não resolve', async () => {
  const { client, emitted, whatsapp } = setup();
  client.emit('connection', { status: 'open' });
  const sent = await whatsapp.sendPoll(GROUP, 'Qual?', ['A', 'B'], false);
  client.emit('message_addon', {
    kind: 'poll_vote',
    key: { id: 'VOTE1', remoteJid: GROUP, participant: '111@lid', fromMe: false },
    targetMessageId: sent.key.id,
    decrypted: {
      kind: 'poll_vote',
      selectedOptionNames: null,
      pollVote: { selectedOptions: [createHash('sha256').update('B').digest()], senderTimestampMs: 1_760_000_000_000 },
    },
  });
  await flush();
  assert.equal(emitted[0].event, 'poll.vote');
  assert.equal(emitted[0].id, 'vote_VOTE1');
  assert.deepEqual(emitted[0].payload.vote.selectedOptions, ['B']);
  assert.equal(emitted[0].payload.vote.from, '111@lid');
  assert.equal(emitted[0].payload.poll.id, sent.id);
  assert.equal(emitted[0].payload.vote.timestamp, 1_760_000_000_000);
});

test('mensagem de grupo vira evento message com texto', async () => {
  const { client, emitted } = setup();
  client.emit('message', {
    key: { id: 'M1', remoteJid: GROUP, participant: '111@lid', fromMe: false, isGroup: true },
    message: { conversation: '!enquete Teste | a | b' },
    timestampSeconds: 1_760_000_000,
  });
  await flush();
  assert.equal(emitted[0].event, 'message');
  assert.deepEqual(
    { from: emitted[0].payload.from, participant: emitted[0].payload.participant, body: emitted[0].payload.body },
    { from: GROUP, participant: '111@lid', body: '!enquete Teste | a | b' },
  );
});

test('grupos, participantes e lids no formato do WAHA', async () => {
  const { client, whatsapp } = setup();
  client.emit('connection', { status: 'open' });
  assert.deepEqual(await whatsapp.groups(), [{ id: GROUP, name: 'Black Livros 01' }]);
  assert.deepEqual(await whatsapp.participants(GROUP), [
    { id: '111@lid', role: 'admin' },
    { id: '222@lid', role: 'superadmin' },
    { id: '333@lid', role: 'participant' },
  ]);
  assert.deepEqual(await whatsapp.lids(), [{ lid: '111@lid', pn: '5511999999999@c.us' }]);
});

test('fixar usa o id puro mesmo vindo no formato WAHA', async () => {
  const { client, whatsapp } = setup();
  client.emit('connection', { status: 'open' });
  await whatsapp.pin(GROUP, '3EB0ABCDEF123456', 604_800);
  assert.deepEqual(client.sent[0].content, {
    type: 'pin',
    target: { remoteJid: GROUP, id: '3EB0ABCDEF123456', fromMe: true },
    durationSecs: 604_800,
  });
});
