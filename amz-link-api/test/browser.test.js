import assert from 'node:assert/strict';
import test from 'node:test';
import { createBrowser, fetchInPage } from '../src/browser.js';
import { silentLog } from '../src/log.js';

test('resposta que não é JSON indica sessão inválida', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ text: async () => '<html>login</html>' });
  try {
    assert.equal(await fetchInPage('/associates/sitestripe/getStoreTagMap'), null);
  } finally {
    globalThis.fetch = original;
  }
});

test('relança o navegador quando a página morre e tenta de novo', async () => {
  let launches = 0;
  const launch = async () => {
    launches += 1;
    const fail = launches === 1;
    const page = {
      isClosed: () => false,
      async goto() {},
      async evaluate() {
        if (fail) throw new Error('Target page, context or browser has been closed');
        return { ok: true, shortUrl: 'https://link.amazon/abc' };
      },
      on() {},
      setDefaultTimeout() {},
      setDefaultNavigationTimeout() {},
    };
    return {
      pages: () => [page],
      on() {},
      async close() {},
    };
  };

  const browser = createBrowser({
    config: {
      profileDir: '/tmp/amz-profile',
      headless: true,
      origin: 'https://www.amazon.com.br',
      pageReloadMs: 0,
    },
    launch,
    log: silentLog,
  });

  const result = await browser.call('/associates/sitestripe/getShortUrl');
  assert.equal(result.shortUrl, 'https://link.amazon/abc');
  assert.equal(launches, 2);
  await browser.close();
});
