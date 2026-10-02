import assert from 'node:assert/strict';
import { once } from 'node:events';
import test from 'node:test';
import { LinkError } from '../src/errors.js';
import { silentLog } from '../src/log.js';
import { createApp } from '../src/server.js';

const token = 'chave-de-teste';

test('health é público e o restante exige a chave', async () => {
  const { base, close } = await listen(createApp(deps()));
  try {
    const health = await fetch(`${base}/health`);
    assert.equal(health.status, 200);
    const body = await health.json();
    assert.equal(body.sessionOk, false);
    assert.equal(body.lastTagsRefresh, null);
    assert.equal(typeof body.uptime, 'number');

    const denied = await fetch(`${base}/tags`);
    assert.equal(denied.status, 401);

    const tags = await fetch(`${base}/tags`, { headers: { 'x-api-key': token } });
    assert.equal(tags.status, 200);
    assert.deepEqual(await tags.json(), { tags: ['babypoupe-20'] });
  } finally {
    await close();
  }
});

test('GET /link devolve o corpo do gerador', async () => {
  const seen = [];
  const { base, close } = await listen(createApp(deps({
    makeLink: async (input, tag) => {
      seen.push([input, tag]);
      return {
        asin: 'B0CP9Z56SW',
        tag,
        longUrl: 'https://www.amazon.com.br/dp/B0CP9Z56SW?tag=babypoupe-20',
        shortUrl: 'https://link.amazon/abc',
        url: 'https://link.amazon/abc',
        cached: false,
      };
    },
  })));
  try {
    const response = await fetch(
      `${base}/link?url=${encodeURIComponent('https://www.amazon.com.br/dp/B0CP9Z56SW')}&tag=babypoupe-20`,
      { headers: { 'x-api-key': token } },
    );
    assert.equal(response.status, 200);
    assert.equal((await response.json()).shortUrl, 'https://link.amazon/abc');
    assert.deepEqual(seen, [['https://www.amazon.com.br/dp/B0CP9Z56SW', 'babypoupe-20']]);
  } finally {
    await close();
  }
});

test('tag inválida responde 400', async () => {
  const { base, close } = await listen(createApp(deps({
    makeLink: async () => {
      throw new LinkError('TAG_INVALIDA', 'A tag não pertence a esta conta de associado.');
    },
  })));
  try {
    const response = await fetch(`${base}/link?asin=B0CP9Z56SW&tag=naoexiste123-20`, {
      headers: { 'x-api-key': token },
    });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error, 'TAG_INVALIDA');
  } finally {
    await close();
  }
});

test('lote devolve um resultado por item, na mesma ordem', async () => {
  const { base, close } = await listen(createApp(deps({
    makeLink: async (input) => {
      if (input.includes('ruim')) {
        throw new LinkError('ASIN_NAO_ENCONTRADO', 'Não foi possível identificar o ASIN.');
      }
      return { asin: input, tag: 'babypoupe-20', url: `https://link.amazon/${input}`, cached: false };
    },
  })));
  try {
    const items = Array.from({ length: 10 }, (_, index) => ({
      url: index % 2 === 0 ? `B0CP9Z56S${index}` : `ruim-${index}`,
      tag: 'babypoupe-20',
    }));
    const response = await fetch(`${base}/links`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': token },
      body: JSON.stringify({ items }),
    });
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.length, 10);
    assert.equal(body[0].asin, 'B0CP9Z56S0');
    assert.equal(body[1].error, 'ASIN_NAO_ENCONTRADO');
    assert.equal(body[9].error, 'ASIN_NAO_ENCONTRADO');
  } finally {
    await close();
  }
});

test('lote acima de 50 é recusado', async () => {
  const { base, close } = await listen(createApp(deps()));
  try {
    const response = await fetch(`${base}/links`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': token },
      body: JSON.stringify({ items: Array.from({ length: 51 }, () => ({ url: 'B0CP9Z56SW' })) }),
    });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error, 'ENTRADA_INVALIDA');
  } finally {
    await close();
  }
});

test('GET /tags?atualizar=1 puxa a lista na Amazon', async () => {
  const amazon = baseAmazon();
  let pulls = 0;
  amazon.refreshTags = async () => {
    pulls += 1;
    return {
      sessionOk: true,
      lastTagsRefresh: '2026-09-28T20:00:00.000Z',
      tags: ['souleitor-20', 'cpetrag0f7-20'],
    };
  };
  const { base, close } = await listen(createApp({
    config: { token },
    amazon,
    links: { makeLink: async () => ({}) },
    log: silentLog,
  }));
  try {
    const cached = await fetch(`${base}/tags`, { headers: { 'x-api-key': token } });
    assert.deepEqual(await cached.json(), { tags: ['babypoupe-20'] });
    assert.equal(pulls, 0);

    const live = await fetch(`${base}/tags?atualizar=1`, { headers: { 'x-api-key': token } });
    assert.equal(live.status, 200);
    assert.deepEqual(await live.json(), {
      tags: ['souleitor-20', 'cpetrag0f7-20'],
      sessionOk: true,
      lastTagsRefresh: '2026-09-28T20:00:00.000Z',
      atualizado: true,
    });
    assert.equal(pulls, 1);

    const invalid = await fetch(`${base}/tags?atualizar=sim`, { headers: { 'x-api-key': token } });
    assert.equal(invalid.status, 400);
    assert.equal((await invalid.json()).error, 'ENTRADA_INVALIDA');
  } finally {
    await close();
  }
});

test('refresh-tags devolve o estado novo', async () => {
  const amazon = baseAmazon();
  amazon.refreshTags = async () => ({
    sessionOk: true,
    lastTagsRefresh: '2026-09-28T18:00:00.000Z',
    tags: ['babypoupe-20', 'cpetrag0f7-20'],
  });
  const { base, close } = await listen(createApp({
    config: { token },
    amazon,
    links: { makeLink: async () => ({}) },
    log: silentLog,
  }));
  try {
    const response = await fetch(`${base}/refresh-tags`, {
      method: 'POST',
      headers: { 'x-api-key': token },
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).sessionOk, true);
  } finally {
    await close();
  }
});

function deps(links = {}) {
  return {
    config: { token },
    amazon: baseAmazon(),
    links: {
      makeLink: links.makeLink || (async () => {
        throw new Error('não deveria gerar link neste teste');
      }),
    },
    log: silentLog,
  };
}

function baseAmazon() {
  return {
    getState: () => ({ sessionOk: false, lastTagsRefresh: null, tags: ['babypoupe-20'] }),
    refreshTags: async () => ({ sessionOk: false, lastTagsRefresh: null, tags: ['babypoupe-20'] }),
  };
}

async function listen(app) {
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address();
  return {
    base: `http://127.0.0.1:${port}`,
    close: () => new Promise((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
    }),
  };
}
