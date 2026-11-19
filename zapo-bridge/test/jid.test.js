import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isValidChatId, parseMessageId, serializeMessageId, toWahaJid, toZapoJid } from '../src/jid.js';

test('converte telefone entre o formato do WAHA e do zapo', () => {
  assert.equal(toZapoJid('5511999999999@c.us'), '5511999999999@s.whatsapp.net');
  assert.equal(toWahaJid('5511999999999@s.whatsapp.net'), '5511999999999@c.us');
  assert.equal(toWahaJid('5511999999999:12@s.whatsapp.net'), '5511999999999@c.us');
});

test('mantém grupo e lid intactos', () => {
  assert.equal(toZapoJid('120363000000000000@g.us'), '120363000000000000@g.us');
  assert.equal(toWahaJid('123456789012345@lid'), '123456789012345@lid');
});

test('serializa id no formato WAHA e lê os dois formatos', () => {
  const serialized = serializeMessageId('120363000000000000@g.us', '3EB0ABCDEF1234567890', true);
  assert.equal(serialized, 'true_120363000000000000@g.us_3EB0ABCDEF1234567890');
  assert.equal(parseMessageId(serialized).id, '3EB0ABCDEF1234567890');
  assert.equal(parseMessageId('true_120363@g.us_3EB0ABC_5511@c.us').id, '3EB0ABC');
  assert.equal(parseMessageId('3EB0ABCDEF').id, '3EB0ABCDEF');
  assert.equal(parseMessageId(''), null);
});

test('recusa chatId fora do padrão', () => {
  assert.equal(isValidChatId('120363000000000000@g.us'), true);
  assert.equal(isValidChatId('../etc/passwd'), false);
  assert.equal(isValidChatId('abc@example.com'), false);
});
