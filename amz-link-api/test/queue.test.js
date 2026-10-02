import assert from 'node:assert/strict';
import test from 'node:test';
import { createQueue } from '../src/queue.js';

test('espaça o início das tarefas pelo intervalo mínimo', async () => {
  let clock = 5000;
  const waits = [];
  const queue = createQueue(1500, {
    now: () => clock,
    sleep: async (ms) => {
      waits.push(ms);
      clock += ms;
    },
  });

  const first = queue.enqueue(async () => {
    clock += 10;
    return 'a';
  });
  const second = queue.enqueue(async () => 'b');
  assert.deepEqual(await Promise.all([first, second]), ['a', 'b']);
  assert.deepEqual(waits, [1490]);
});

test('uma falha não trava a fila', async () => {
  const queue = createQueue(0);
  await assert.rejects(queue.enqueue(async () => {
    throw new Error('falhou');
  }));
  assert.equal(await queue.enqueue(async () => 'ok'), 'ok');
});
