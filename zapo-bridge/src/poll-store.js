import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import Database from 'better-sqlite3';

const RETENTION_MS = 60 * 24 * 60 * 60 * 1000;

// Cópia própria das opções de cada enquete enviada. O voto chega só com o
// sha256 do nome da opção; se o archive do zapo não resolver o nome, este
// registro resolve e o voto não se perde.
export function createPollStore(path) {
  if (path !== ':memory:') mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const db = new Database(path);
  db.pragma('journal_mode = WAL');
  db.exec(`
    CREATE TABLE IF NOT EXISTS sent_polls (
      message_id TEXT PRIMARY KEY,
      chat_jid TEXT NOT NULL,
      options_json TEXT NOT NULL,
      created_at INTEGER NOT NULL
    )
  `);

  const insert = db.prepare(`
    INSERT INTO sent_polls (message_id, chat_jid, options_json, created_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(message_id) DO UPDATE SET options_json = excluded.options_json
  `);
  const select = db.prepare('SELECT options_json FROM sent_polls WHERE message_id = ?');
  const prune = db.prepare('DELETE FROM sent_polls WHERE created_at < ?');

  return {
    remember(messageId, chatJid, options, now = Date.now()) {
      insert.run(messageId, chatJid, JSON.stringify(options), now);
      prune.run(now - RETENTION_MS);
    },

    has(messageId) {
      return Boolean(select.get(messageId));
    },

    resolveOptionNames(messageId, selectedHashes) {
      const row = select.get(messageId);
      if (!row) return null;
      const byHash = new Map(JSON.parse(row.options_json).map((name) => [hashOption(name), name]));
      const names = [];
      for (const hash of selectedHashes ?? []) {
        const name = byHash.get(Buffer.from(hash).toString('hex'));
        if (name === undefined) return null;
        names.push(name);
      }
      return names;
    },

    close() {
      db.close();
    },
  };
}

export function hashOption(name) {
  return createHash('sha256').update(name, 'utf8').digest('hex');
}
