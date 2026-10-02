import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import Database from 'better-sqlite3';

const SCHEMA = `
CREATE TABLE IF NOT EXISTS links (
  asin TEXT NOT NULL,
  tag TEXT NOT NULL,
  short_url TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  hits INTEGER DEFAULT 0,
  PRIMARY KEY (asin, tag)
);
CREATE TABLE IF NOT EXISTS tags (
  tag TEXT PRIMARY KEY,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
`;

export function createDatabase(dbPath) {
  if (dbPath !== ':memory:') {
    mkdirSync(dirname(dbPath), { recursive: true });
  }

  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.pragma('busy_timeout = 5000');
  db.exec(SCHEMA);

  const findStatement = db.prepare(
    'SELECT short_url, hits FROM links WHERE asin = ? AND tag = ?',
  );
  const saveStatement = db.prepare(`
    INSERT INTO links (asin, tag, short_url)
    VALUES (?, ?, ?)
    ON CONFLICT(asin, tag) DO UPDATE SET short_url = excluded.short_url
  `);
  const hitStatement = db.prepare(
    'UPDATE links SET hits = hits + 1 WHERE asin = ? AND tag = ?',
  );
  const listTagsStatement = db.prepare('SELECT tag FROM tags ORDER BY tag');
  const deleteTagsStatement = db.prepare('DELETE FROM tags');
  const insertTagStatement = db.prepare('INSERT INTO tags (tag) VALUES (?)');

  const replaceAll = db.transaction((tags) => {
    deleteTagsStatement.run();
    for (const tag of tags) insertTagStatement.run(tag);
  });

  return {
    findLink(asin, tag) {
      const row = findStatement.get(asin, tag);
      if (!row) return null;
      return { shortUrl: row.short_url, hits: row.hits };
    },
    saveLink(asin, tag, shortUrl) {
      saveStatement.run(asin, tag, shortUrl);
    },
    hit(asin, tag) {
      hitStatement.run(asin, tag);
    },
    listTags() {
      return listTagsStatement.all().map((row) => row.tag);
    },
    replaceTags(tags) {
      replaceAll(tags);
    },
    close() {
      db.close();
    },
  };
}
