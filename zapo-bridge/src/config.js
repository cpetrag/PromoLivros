import dotenv from 'dotenv';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const projectDir = resolve(rootDir, '..');

export class ConfigError extends Error {}

const DEVICE_BROWSERS = new Set(['chrome', 'firefox', 'safari', 'edge', 'opera']);
const LOG_LEVELS = new Set(['trace', 'debug', 'info', 'warn', 'error']);

// O .env da ponte vem primeiro; o do projeto completa WAHA_API_KEY/WAHA_SESSION,
// assim a chave continua num lugar só e o Python não precisa mudar.
export function loadEnv() {
  dotenv.config({ path: resolve(rootDir, '.env'), quiet: true });
  dotenv.config({ path: resolve(projectDir, '.env'), quiet: true });
}

export function loadConfig(env = process.env) {
  const session = text(env.WAHA_SESSION, 'promo-livros');
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(session)) {
    throw new ConfigError('WAHA_SESSION inválido.');
  }

  const deviceBrowser = text(env.BRIDGE_DEVICE_BROWSER, 'chrome').toLowerCase();
  if (!DEVICE_BROWSERS.has(deviceBrowser)) {
    throw new ConfigError('BRIDGE_DEVICE_BROWSER inválido.');
  }

  const logLevel = text(env.BRIDGE_LOG_LEVEL, 'info').toLowerCase();
  if (!LOG_LEVELS.has(logLevel)) {
    throw new ConfigError('BRIDGE_LOG_LEVEL inválido.');
  }

  return {
    host: text(env.BRIDGE_HOST, '127.0.0.1'),
    port: portNumber(env.BRIDGE_PORT, 4450),
    apiKey: text(env.WAHA_API_KEY, ''),
    session,
    webhookUrl: httpUrl(env.BRIDGE_WEBHOOK_URL, 'http://127.0.0.1:8787/whatsapp/webhook'),
    dbPath: resolve(rootDir, text(env.BRIDGE_DB_PATH, 'data/zapo.sqlite')),
    deviceBrowser,
    logLevel,
    maxImageBytes: 8 * 1024 * 1024,
    rootDir,
  };
}

function text(value, fallback) {
  if (typeof value !== 'string') return fallback;
  const trimmed = value.trim();
  return trimmed || fallback;
}

function portNumber(value, fallback) {
  if (value === undefined || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new ConfigError('BRIDGE_PORT inválido.');
  }
  return parsed;
}

function httpUrl(value, fallback) {
  const raw = text(value, fallback);
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ConfigError('BRIDGE_WEBHOOK_URL inválido.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ConfigError('BRIDGE_WEBHOOK_URL precisa ser http ou https.');
  }
  return parsed.toString();
}
