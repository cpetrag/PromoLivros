import { createHash, timingSafeEqual } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { createAlert } from './alert.js';
import { createAmazon } from './amazon.js';
import { createBrowser } from './browser.js';
import { loadConfig, loadEnv } from './config.js';
import { createDatabase } from './db.js';
import { LinkError } from './errors.js';
import { createLinks } from './links.js';
import { log as defaultLog } from './log.js';
import { createQueue } from './queue.js';

export function createApp({ config, amazon, links, log = defaultLog }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '64kb', strict: true }));

  app.get('/health', (req, res) => {
    const state = amazon.getState();
    res.json({
      sessionOk: state.sessionOk,
      lastTagsRefresh: state.lastTagsRefresh,
      uptime: Math.round(process.uptime()),
    });
  });

  app.use((req, res, next) => {
    if (!authorized(req.header('x-api-key'), config.token)) {
      res.status(401).json({
        error: 'NAO_AUTORIZADO',
        message: 'Chave de API ausente ou inválida.',
      });
      return;
    }
    next();
  });

  app.get('/tags', wrap(async (req, res) => {
    const atualizar = singleQuery(req.query.atualizar);
    const refresh = singleQuery(req.query.refresh);
    if (atualizar === null || refresh === null) {
      res.status(400).json({
        error: 'ENTRADA_INVALIDA',
        message: 'Parâmetro repetido ou inválido.',
      });
      return;
    }
    const asked = atualizar ?? refresh;
    if (asked !== undefined && asked !== '1' && asked !== 'true') {
      res.status(400).json({
        error: 'ENTRADA_INVALIDA',
        message: 'Use atualizar=1 para puxar as tags na Amazon.',
      });
      return;
    }
    if (asked === undefined) {
      res.json({ tags: amazon.getState().tags });
      return;
    }
    const state = await amazon.refreshTags();
    res.json({
      tags: state.tags,
      sessionOk: state.sessionOk,
      lastTagsRefresh: state.lastTagsRefresh,
      atualizado: Boolean(state.sessionOk),
    });
  }));

  app.get('/link', wrap(async (req, res) => {
    const url = singleQuery(req.query.url);
    const asin = singleQuery(req.query.asin);
    const tag = singleQuery(req.query.tag);
    if (url === null || asin === null || tag === null) {
      res.status(400).json({
        error: 'ENTRADA_INVALIDA',
        message: 'Parâmetro repetido ou inválido.',
      });
      return;
    }
    const body = await links.makeLink(url || asin || '', tag);
    res.json(body);
  }));

  app.post('/links', wrap(async (req, res) => {
    const items = parseItems(req.body);
    if (!items) {
      res.status(400).json({
        error: 'ENTRADA_INVALIDA',
        message: 'Envie items com no máximo 50 elementos.',
      });
      return;
    }

    const results = [];
    for (const item of items) {
      results.push(await linkOne(item, links, log));
    }
    res.json(results);
  }));

  app.post('/refresh-tags', wrap(async (req, res) => {
    res.json(await amazon.refreshTags());
  }));

  app.use((req, res) => {
    res.status(404).json({ error: 'NAO_ENCONTRADO', message: 'Rota não existe.' });
  });

  app.use((error, req, res, next) => {
    if (error instanceof LinkError) {
      res.status(error.status).json({ error: error.code, message: error.message });
      return;
    }
    if (error instanceof SyntaxError && error.status === 400 && 'body' in error) {
      res.status(400).json({ error: 'ENTRADA_INVALIDA', message: 'JSON inválido.' });
      return;
    }
    log.error('http_error', { message: error.message });
    if (res.headersSent) {
      next(error);
      return;
    }
    res.status(500).json({ error: 'ERRO_INTERNO', message: 'Falha inesperada.' });
  });

  return app;
}

export async function start() {
  loadEnv();
  const config = loadConfig();
  if (!config.token) {
    defaultLog.error('config', {
      message: 'AMZ_TOKEN vazio; as rotas autenticadas vão recusar todas as chamadas.',
    });
  }

  mkdirSync(path.resolve(config.rootDir, 'logs'), { recursive: true });
  const db = createDatabase(config.dbPath);
  const browser = createBrowser({ config });
  const alert = createAlert({
    token: config.telegramBotToken,
    chatId: config.telegramChatId,
  });
  const amazon = createAmazon({ browser, db, config, alert });
  const queue = createQueue(config.minIntervalMs);
  const links = createLinks({ db, amazon, queue });
  const app = createApp({ config, amazon, links });

  const server = await new Promise((resolve, reject) => {
    const listening = app.listen(config.port, config.host, () => resolve(listening));
    listening.on('error', reject);
  });

  const stopRefresh = amazon.boot();
  const stopMaintenance = browser.startMaintenance();
  defaultLog.info('listen', { host: config.host, port: config.port });

  let shuttingDown = false;
  async function shutdown(signal) {
    if (shuttingDown) return;
    shuttingDown = true;
    defaultLog.info('shutdown', { signal });
    stopRefresh();
    stopMaintenance();
    await new Promise((resolve) => server.close(resolve));
    await browser.close();
    db.close();
    process.exit(0);
  }

  process.on('SIGINT', () => {
    shutdown('SIGINT').catch((error) => {
      defaultLog.error('shutdown_failed', { message: error.message });
      process.exit(1);
    });
  });
  process.on('SIGTERM', () => {
    shutdown('SIGTERM').catch((error) => {
      defaultLog.error('shutdown_failed', { message: error.message });
      process.exit(1);
    });
  });

  return server;
}

function wrap(handler) {
  return (req, res, next) => {
    Promise.resolve(handler(req, res, next)).catch(next);
  };
}

async function linkOne(item, links, log) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) {
    return { error: 'ENTRADA_INVALIDA', message: 'Item inválido.' };
  }
  const url = optionalString(item.url);
  const asin = optionalString(item.asin);
  const tag = item.tag === undefined || item.tag === null ? undefined : optionalString(item.tag);
  if (url === null || asin === null || tag === null) {
    return { error: 'ENTRADA_INVALIDA', message: 'Item inválido.' };
  }

  try {
    return await links.makeLink(url || asin || '', tag);
  } catch (error) {
    if (error instanceof LinkError) {
      return { error: error.code, message: error.message };
    }
    log.error('link_failed', { message: error.message });
    return { error: 'ERRO_INTERNO', message: 'Falha ao gerar o link.' };
  }
}

function parseItems(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  if (!Array.isArray(body.items) || body.items.length > 50) return null;
  return body.items;
}

function singleQuery(value) {
  if (value === undefined) return undefined;
  if (typeof value !== 'string') return null;
  return value;
}

function optionalString(value) {
  if (value === undefined) return undefined;
  if (typeof value !== 'string') return null;
  return value;
}

function authorized(header, token) {
  if (!token || typeof header !== 'string' || !header.trim()) return false;
  const left = createHash('sha256').update(header.trim()).digest();
  const right = createHash('sha256').update(token).digest();
  return timingSafeEqual(left, right);
}

function isMainModule() {
  const entry = process.argv[1];
  if (!entry) return false;
  return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry);
}

// PM2 carrega este arquivo pelo ProcessContainerFork, então argv não é server.js.
const launchedByPm2 = process.env.pm_id !== undefined;

if (isMainModule() || launchedByPm2) {
  start().catch((error) => {
    console.error(JSON.stringify({
      ts: new Date().toISOString(),
      level: 'error',
      event: 'fatal',
      message: error.message,
    }));
    process.exit(1);
  });
}
