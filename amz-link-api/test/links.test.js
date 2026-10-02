import assert from 'node:assert/strict';
import test from 'node:test';
import { LinkError } from '../src/errors.js';
import { createLinks } from '../src/links.js';
import { silentLog } from '../src/log.js';
import { createQueue } from '../src/queue.js';
import { resolveAsin } from '../src/resolve.js';

const LONG = 'https://www.amazon.com.br/dp/B0CP9Z56SW?linkCode=sl2&tag=babypoupe-20&ref_=as_li_ss_tl';

test('gera o curto, cacheia e não volta na Amazon', async () => {
  let shortenCalls = 0;
  const db = memoryDb();
  const links = createLinks({
    db,
    amazon: fakeAmazon({
      shortenUrl: async (longUrl) => {
        shortenCalls += 1;
        assert.equal(longUrl, LONG);
        return 'https://link.amazon/B09v8WQBm';
      },
    }),
    queue: createQueue(0),
    log: silentLog,
  });

  const first = await links.makeLink(
    'https://www.amazon.com.br/Nome/dp/B0CP9Z56SW?tag=outra-20',
    'babypoupe-20',
  );
  const second = await links.makeLink('B0CP9Z56SW', 'babypoupe-20');

  assert.equal(first.cached, false);
  assert.equal(first.shortUrl, 'https://link.amazon/B09v8WQBm');
  assert.equal(first.url, first.shortUrl);
  assert.equal(first.longUrl, LONG);
  assert.equal(second.cached, true);
  assert.equal(second.url, first.shortUrl);
  assert.equal(shortenCalls, 1);
  assert.equal(db.findLink('B0CP9Z56SW', 'babypoupe-20').hits, 1);
});

test('tag desconhecida falha antes de resolver o ASIN', async () => {
  let resolved = false;
  const links = createLinks({
    db: memoryDb(),
    amazon: fakeAmazon(),
    queue: createQueue(0),
    resolve: async () => {
      resolved = true;
      return 'B0CP9Z56SW';
    },
    log: silentLog,
  });

  await assert.rejects(
    () => links.makeLink('https://amzn.to/abc', 'naoexiste123-20'),
    (error) => error instanceof LinkError && error.code === 'TAG_INVALIDA',
  );
  assert.equal(resolved, false);
});

test('sem sessão devolve o link longo com a tag pedida', async () => {
  const links = createLinks({
    db: memoryDb(),
    amazon: fakeAmazon({ sessionOk: false }),
    queue: {
      enqueue: async () => {
        throw new Error('não deveria chamar a Amazon');
      },
    },
    log: silentLog,
  });

  const body = await links.makeLink('B0CP9Z56SW', 'babypoupe-20');
  assert.equal(body.shortUrl, null);
  assert.equal(body.url, LONG);
  assert.equal(body.cached, false);
});

test('tag omitida usa a loja principal', async () => {
  const links = createLinks({
    db: memoryDb(),
    amazon: fakeAmazon({
      shortenUrl: async (longUrl) => {
        assert.match(longUrl, /tag=cpetrag0f7-20/);
        return 'https://link.amazon/loja';
      },
    }),
    queue: createQueue(0),
    log: silentLog,
  });

  const body = await links.makeLink('B0CP9Z56SW');
  assert.equal(body.tag, 'cpetrag0f7-20');
});

test('lote mistura inválidos e respeita o intervalo só nas chamadas à Amazon', async () => {
  let clock = 5000;
  const waits = [];
  let shortenCalls = 0;
  const links = createLinks({
    db: memoryDb(),
    amazon: fakeAmazon({
      shortenUrl: async () => {
        shortenCalls += 1;
        clock += 10;
        return `https://link.amazon/item${shortenCalls}`;
      },
    }),
    queue: createQueue(1500, {
      now: () => clock,
      sleep: async (ms) => {
        waits.push(ms);
        clock += ms;
      },
    }),
    resolve: resolveAsin,
    log: silentLog,
  });

  const items = [
    ['https://www.amazon.com.br/dp/B0CP9Z56SW', 'naoexiste123-20'],
    ['https://www.amazon.com.br/dp/B0CP9Z56SW', 'babypoupe-20'],
    ['lixo', 'babypoupe-20'],
    ['B0AAAAAAAA', 'babypoupe-20'],
  ];
  const results = [];
  for (const [input, tag] of items) {
    try {
      results.push(await links.makeLink(input, tag));
    } catch (error) {
      results.push({ error: error.code, message: error.message });
    }
  }

  assert.equal(results.length, 4);
  assert.equal(results[0].error, 'TAG_INVALIDA');
  assert.equal(results[1].asin, 'B0CP9Z56SW');
  assert.equal(results[1].cached, false);
  assert.equal(results[2].error, 'ASIN_NAO_ENCONTRADO');
  assert.equal(results[3].asin, 'B0AAAAAAAA');
  assert.equal(shortenCalls, 2);
  assert.deepEqual(waits, [1490]);
});

function fakeAmazon({ sessionOk = true, shortenUrl } = {}) {
  const tags = new Set(['cpetrag0f7-20', 'babypoupe-20']);
  return {
    storeId: 'cpetrag0f7-20',
    whenReady: async () => {},
    isTagValid: (tag) => tags.has(tag),
    isSessionOk: () => sessionOk,
    shortenUrl: shortenUrl || (async () => 'https://link.amazon/abc'),
  };
}

function memoryDb() {
  const rows = new Map();
  return {
    findLink(asin, tag) {
      return rows.get(`${asin}|${tag}`) || null;
    },
    saveLink(asin, tag, shortUrl) {
      rows.set(`${asin}|${tag}`, { shortUrl, hits: 0 });
    },
    hit(asin, tag) {
      rows.get(`${asin}|${tag}`).hits += 1;
    },
  };
}
