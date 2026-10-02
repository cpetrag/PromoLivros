import dotenv from 'dotenv';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ConfigError } from './errors.js';

export const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function loadEnv() {
  dotenv.config({ path: resolve(rootDir, '.env') });
}

export function loadConfig(env = process.env) {
  const storeId = text(env.AMZ_STORE_ID, 'cpetrag0f7-20');
  const marketplaceId = text(env.AMZ_MARKETPLACE_ID, '526970');

  if (!/^[A-Za-z0-9_-]+$/.test(storeId)) {
    throw new ConfigError('AMZ_STORE_ID inválido.');
  }
  if (!/^\d+$/.test(marketplaceId)) {
    throw new ConfigError('AMZ_MARKETPLACE_ID inválido.');
  }

  return {
    port: portNumber(env.PORT, 3070),
    host: text(env.HOST, '127.0.0.1'),
    token: text(env.AMZ_TOKEN, ''),
    storeId,
    marketplaceId,
    profileDir: resolve(rootDir, text(env.AMZ_PROFILE_DIR, 'amz-profile')),
    headless: text(env.HEADLESS, 'true') !== 'false',
    minIntervalMs: nonNegative(env.MIN_INTERVAL_MS, 1500),
    tagsRefreshMin: Math.max(1, nonNegative(env.TAGS_REFRESH_MIN, 30)),
    telegramBotToken: text(env.TELEGRAM_BOT_TOKEN, ''),
    telegramChatId: text(env.TELEGRAM_CHAT_ID, ''),
    dbPath: resolve(rootDir, text(env.AMZ_DB_PATH, 'data/links.sqlite')),
    origin: 'https://www.amazon.com.br',
    pageReloadMs: 6 * 60 * 60 * 1000,
    rootDir,
  };
}

function text(value, fallback) {
  if (typeof value !== 'string') return fallback;
  const trimmed = value.trim();
  return trimmed || fallback;
}

function nonNegative(value, fallback) {
  if (value === undefined || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return parsed;
}

function portNumber(value, fallback) {
  const parsed = nonNegative(value, fallback);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) return fallback;
  return parsed;
}
