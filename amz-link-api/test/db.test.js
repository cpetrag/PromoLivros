import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createDatabase } from '../src/db.js';

test('guarda link, incrementa hits e substitui a lista de tags', () => {
  const dir = mkdtempSync(join(tmpdir(), 'amz-link-'));
  const db = createDatabase(join(dir, 'links.sqlite'));
  try {
    assert.deepEqual(db.listTags(), []);
    db.replaceTags(['b', 'a']);
    assert.deepEqual(db.listTags(), ['a', 'b']);
    db.replaceTags(['a']);
    assert.deepEqual(db.listTags(), ['a']);

    assert.equal(db.findLink('B0CP9Z56SW', 'a'), null);
    db.saveLink('B0CP9Z56SW', 'a', 'https://link.amazon/abc');
    db.hit('B0CP9Z56SW', 'a');
    db.hit('B0CP9Z56SW', 'a');
    assert.deepEqual(db.findLink('B0CP9Z56SW', 'a'), {
      shortUrl: 'https://link.amazon/abc',
      hits: 2,
    });

    db.saveLink('B0CP9Z56SW', 'a', 'https://link.amazon/novo');
    const updated = db.findLink('B0CP9Z56SW', 'a');
    assert.equal(updated.shortUrl, 'https://link.amazon/novo');
    assert.equal(updated.hits, 2);
  } finally {
    db.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
