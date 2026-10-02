import assert from 'node:assert/strict';
import test from 'node:test';
import { resolve } from 'node:path';
import { loadConfig, rootDir } from '../src/config.js';
import { ConfigError } from '../src/errors.js';

test('aplica os padrões da API local', () => {
  const config = loadConfig({});
  assert.equal(config.port, 3070);
  assert.equal(config.host, '127.0.0.1');
  assert.equal(config.storeId, 'cpetrag0f7-20');
  assert.equal(config.marketplaceId, '526970');
  assert.equal(config.headless, true);
  assert.equal(config.minIntervalMs, 1500);
  assert.equal(config.tagsRefreshMin, 30);
  assert.equal(config.profileDir, resolve(rootDir, 'amz-profile'));
  assert.equal(config.token, '');
});

test('HEADLESS=false abre o navegador visível', () => {
  assert.equal(loadConfig({ HEADLESS: 'false' }).headless, false);
});

test('recusa marketplace que não é numérico', () => {
  assert.throws(
    () => loadConfig({ AMZ_MARKETPLACE_ID: 'brasil', AMZ_STORE_ID: 'loja-20' }),
    ConfigError,
  );
});
