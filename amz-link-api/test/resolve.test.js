import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveAsin } from '../src/resolve.js';

test('normaliza ASIN puro', async () => {
  assert.equal(await resolveAsin('b0cp9z56sw'), 'B0CP9Z56SW');
});

test('extrai ASIN de URLs da Amazon Brasil e descarta a query', async () => {
  const samples = [
    'https://www.amazon.com.br/dp/B0CP9Z56SW',
    'https://www.amazon.com.br/Nome-do-Livro/dp/B0CP9Z56SW/ref=sr_1_1?tag=outra-20',
    'https://www.amazon.com.br/gp/product/B0CP9Z56SW?tag=outra-20',
    'https://amazon.com.br/gp/aw/d/B0CP9Z56SW',
    'www.amazon.com.br/dp/B0CP9Z56SW?tag=outra-20',
  ];
  for (const sample of samples) {
    assert.equal(await resolveAsin(sample, mustNotFetch), 'B0CP9Z56SW');
  }
});

test('segue só encurtadores conhecidos e lê o ASIN da URL final', async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, redirect: options.redirect, timeout: options.signal !== undefined });
    return {
      url: 'https://www.amazon.com.br/dp/B0CP9Z56SW?tag=outra-20',
      body: { cancel: async () => {} },
    };
  };

  for (const sample of [
    'https://amzn.to/abc',
    'https://www.amzn.to/abc',
    'https://link.amazon/B09v8WQBm',
    'https://a.co/d/xyz',
  ]) {
    assert.equal(await resolveAsin(sample, fetchImpl), 'B0CP9Z56SW');
  }
  assert.equal(calls.length, 4);
  assert.equal(calls[0].redirect, 'follow');
  assert.equal(calls[0].timeout, true);
});

test('não busca hosts arbitrários', async () => {
  const blocked = [
    'https://example.com/dp/B0CP9Z56SW',
    'https://amzn.to.evil.com/abc',
    'https://evilamazon.com.br/dp/B0CP9Z56SW',
    'nao-e-um-asin',
    '',
  ];
  for (const sample of blocked) {
    assert.equal(await resolveAsin(sample, mustNotFetch), null);
  }
});

test('encurtador sem ASIN na URL final devolve nulo', async () => {
  const fetchImpl = async () => ({ url: 'https://www.amazon.com.br/gp/css/homepage.html' });
  assert.equal(await resolveAsin('https://amzn.to/sumiu', fetchImpl), null);
});

function mustNotFetch() {
  throw new Error('não deveria buscar esta URL');
}
