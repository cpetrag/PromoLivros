import assert from 'node:assert/strict';
import test from 'node:test';
import { createAmazon } from '../src/amazon.js';
import { silentLog } from '../src/log.js';

const config = {
  marketplaceId: '526970',
  storeId: 'cpetrag0f7-20',
  tagsRefreshMin: 30,
};

test('sessão boa na subida não dispara alerta de retorno', async () => {
  const alerts = [];
  const amazon = harness({
    alerts,
    payload: tagMap(['cpetrag0f7-20', 'babypoupe-20']),
  });
  const stop = amazon.boot();
  try {
    await amazon.whenReady();
    assert.equal(amazon.isSessionOk(), true);
    assert.deepEqual(alerts, []);
    assert.equal(amazon.isTagValid('babypoupe-20'), true);
    assert.equal(amazon.isTagValid('naoexiste123-20'), false);
  } finally {
    stop();
  }
});

test('sessão caída avisa uma vez e preserva as tags já conhecidas', async () => {
  const alerts = [];
  const replaced = [];
  const db = memoryTags(['babypoupe-20'], replaced);
  const amazon = createAmazon({
    browser: { call: async () => null },
    db,
    config,
    alert: fakeAlert(alerts),
    log: silentLog,
  });

  await amazon.refreshTags();
  await amazon.refreshTags();

  assert.deepEqual(alerts, ['down']);
  assert.equal(amazon.isSessionOk(), false);
  assert.equal(amazon.isTagValid('babypoupe-20'), true);
  assert.equal(replaced.length, 0);
});

test('quando a sessão volta, atualiza as tags e avisa', async () => {
  const alerts = [];
  let payload = null;
  const replaced = [];
  const amazon = createAmazon({
    browser: { call: async () => payload },
    db: memoryTags(['antiga-20'], replaced),
    config,
    alert: fakeAlert(alerts),
    log: silentLog,
  });

  await amazon.refreshTags();
  payload = tagMap(['cpetrag0f7-20', 'babypoupe-20']);
  const state = await amazon.refreshTags();

  assert.deepEqual(alerts, ['down', 'up']);
  assert.equal(state.sessionOk, true);
  assert.deepEqual(state.tags, ['babypoupe-20', 'cpetrag0f7-20']);
  assert.deepEqual(replaced.at(-1), ['cpetrag0f7-20', 'babypoupe-20']);
  assert.equal(amazon.isTagValid('antiga-20'), false);
});

test('encurta com a loja fixa e derruba a sessão se a resposta não for JSON', async () => {
  const alerts = [];
  const calls = [];
  let mode = 'tags';
  const amazon = createAmazon({
    browser: {
      call: async (path) => {
        calls.push(path);
        if (mode === 'tags') return tagMap(['cpetrag0f7-20', 'babypoupe-20']);
        return null;
      },
    },
    db: memoryTags([], []),
    config,
    alert: fakeAlert(alerts),
    log: silentLog,
  });

  await amazon.refreshTags();
  mode = 'short';
  const shortUrl = await amazon.shortenUrl(
    'https://www.amazon.com.br/dp/B0CP9Z56SW?linkCode=sl2&tag=babypoupe-20&ref_=as_li_ss_tl',
  );

  assert.equal(shortUrl, null);
  assert.equal(amazon.isSessionOk(), false);
  assert.deepEqual(alerts, ['down']);
  assert.match(calls.at(-1), /storeId=cpetrag0f7-20/);
  assert.match(calls.at(-1), /tag%3Dbabypoupe-20/);
});

test('devolve o link curto quando o SiteStripe responde ok', async () => {
  let phase = 'tags';
  const amazon = createAmazon({
    browser: {
      call: async () => {
        if (phase === 'tags') return tagMap(['cpetrag0f7-20', 'babypoupe-20']);
        if (phase === 'bad') return { ok: false, isOk: false };
        return { ok: true, isOk: true, shortUrl: 'https://link.amazon/B09v8WQBm' };
      },
    },
    db: memoryTags([], []),
    config,
    alert: fakeAlert([]),
    log: silentLog,
  });

  await amazon.refreshTags();
  phase = 'bad';
  assert.equal(await amazon.shortenUrl('https://www.amazon.com.br/dp/B0CP9Z56SW?tag=babypoupe-20'), null);
  assert.equal(amazon.isSessionOk(), true);

  phase = 'short';
  assert.equal(
    await amazon.shortenUrl('https://www.amazon.com.br/dp/B0CP9Z56SW?tag=babypoupe-20'),
    'https://link.amazon/B09v8WQBm',
  );
  assert.equal(amazon.isSessionOk(), true);
});

function tagMap(tags) {
  return { status: 1, storeTagMap: { 'cpetrag0f7-20': tags } };
}

function memoryTags(initial, replaced) {
  let tags = [...initial];
  return {
    listTags: () => tags,
    replaceTags(next) {
      tags = [...next];
      replaced.push(next);
    },
  };
}

function fakeAlert(alerts) {
  return {
    sessionDown: async () => {
      alerts.push('down');
    },
    sessionUp: async () => {
      alerts.push('up');
    },
  };
}

function harness({ alerts, payload }) {
  return createAmazon({
    browser: { call: async () => payload },
    db: memoryTags([], []),
    config,
    alert: fakeAlert(alerts),
    log: silentLog,
  });
}
