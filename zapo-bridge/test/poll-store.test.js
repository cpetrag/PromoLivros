import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { createPollStore } from '../src/poll-store.js';

const sha = (text) => createHash('sha256').update(text).digest();

test('resolve o nome das opções pelo sha256 do voto', () => {
  const store = createPollStore(':memory:');
  store.remember('MSG1', '120363@g.us', ['Sim', 'Não', 'Talvez']);
  assert.deepEqual(store.resolveOptionNames('MSG1', [sha('Não'), sha('Talvez')]), ['Não', 'Talvez']);
  assert.deepEqual(store.resolveOptionNames('MSG1', []), []);
  store.close();
});

test('devolve null para enquete desconhecida ou hash que não bate', () => {
  const store = createPollStore(':memory:');
  store.remember('MSG1', '120363@g.us', ['Sim', 'Não']);
  assert.equal(store.resolveOptionNames('OUTRA', [sha('Sim')]), null);
  assert.equal(store.resolveOptionNames('MSG1', [sha('Outro')]), null);
  store.close();
});
