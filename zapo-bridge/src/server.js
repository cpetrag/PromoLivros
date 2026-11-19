import { createHash, timingSafeEqual } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { ConfigError, loadConfig, loadEnv } from './config.js';
import { BridgeError, InvalidInputError, NotFoundError } from './errors.js';
import { isValidChatId, parseMessageId } from './jid.js';
import { createLog, toZapoLogger } from './log.js';
import { loadImage } from './media.js';
import { createPollStore } from './poll-store.js';
import { createWebhook } from './webhook.js';
import { createWhatsApp, createZapoClient } from './whatsapp.js';

const MAX_TEXT_LENGTH = 65_536;
const MAX_POLL_NAME_LENGTH = 255;
const MAX_POLL_OPTION_LENGTH = 100;
const MAX_POLL_OPTIONS = 12;
const MAX_PIN_SECONDS = 30 * 24 * 60 * 60;
const MESSAGE_ID_PATTERN = /^[A-Za-z0-9]{6,64}$/;

// Subconjunto da API do WAHA que o promo_livros/waha.py usa. Mantendo o contrato,
// o Python segue igual e só muda o processo que atende a porta.
export function createApp({ config, whatsapp, log, fetchImpl = fetch }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '12mb', strict: true }));

  app.get('/health', (req, res) => {
    res.json({ status: whatsapp.status(), uptime: Math.round(process.uptime()) });
  });

  app.use((req, res, next) => {
    if (!authorized(req.header('x-api-key'), config.apiKey)) {
      res.status(401).json({ error: 'NAO_AUTORIZADO', message: 'Chave de API ausente ou inválida.' });
      return;
    }
    next();
  });

  const sessionRoute = (handler) => wrap(async (req, res) => {
    assertSession(req.params.session, config.session);
    await handler(req, res);
  });

  app.get('/api/sessions/:session', sessionRoute(async (req, res) => {
    res.json({ name: config.session, status: whatsapp.status(), me: whatsapp.me(), engine: { engine: 'ZAPO' } });
  }));

  app.post('/api/sessions/:session/start', sessionRoute(async (req, res) => {
    whatsapp.start();
    res.json({ name: config.session, status: whatsapp.status() });
  }));

  app.post('/api/sessions/:session/restart', sessionRoute(async (req, res) => {
    await whatsapp.restart();
    res.json({ name: config.session, status: whatsapp.status() });
  }));

  app.post('/api/sessions/:session/stop', sessionRoute(async (req, res) => {
    await whatsapp.stop();
    res.json({ name: config.session, status: whatsapp.status() });
  }));

  app.put('/api/sessions/:session', sessionRoute(async (req, res) => {
    res.status(501).json({
      error: 'NOT_IMPLEMENTED',
      message: 'not implemented: o webhook da ponte vem de BRIDGE_WEBHOOK_URL.',
    });
  }));

  app.get('/api/:session/auth/qr', sessionRoute(async (req, res) => {
    const png = await whatsapp.qrPng();
    if (!png) {
      res.status(422).json({ error: 'SEM_QR', message: `Sem QR agora. Status: ${whatsapp.status()}.` });
      return;
    }
    res.set('cache-control', 'no-store').type('image/png').send(png);
  }));

  app.get('/api/:session/groups', sessionRoute(async (req, res) => {
    res.json(await whatsapp.groups());
  }));

  app.get('/api/:session/groups/:chatId/participants/v2', sessionRoute(async (req, res) => {
    res.json(await whatsapp.participants(groupId(req.params.chatId)));
  }));

  app.get('/api/:session/lids', sessionRoute(async (req, res) => {
    res.json(await whatsapp.lids());
  }));

  app.post('/api/sendText', wrap(async (req, res) => {
    const body = sendBody(req.body, config.session);
    const text = boundedText(body.text, 'text', MAX_TEXT_LENGTH);
    res.json(await whatsapp.sendText(body.chatId, text));
  }));

  app.post('/api/sendImage', wrap(async (req, res) => {
    const body = sendBody(req.body, config.session);
    const caption = body.caption === undefined || body.caption === null
      ? ''
      : boundedText(body.caption, 'caption', MAX_TEXT_LENGTH, { allowEmpty: true });
    const image = await loadImage(body.file, { maxBytes: config.maxImageBytes, fetchImpl });
    res.json(await whatsapp.sendImage(body.chatId, image, caption));
  }));

  app.post('/api/sendPoll', wrap(async (req, res) => {
    const body = sendBody(req.body, config.session);
    const poll = parsePoll(body.poll);
    res.json(await whatsapp.sendPoll(body.chatId, poll.name, poll.options, poll.multipleAnswers));
  }));

  app.post('/api/:session/chats/:chatId/messages/:messageId/pin', sessionRoute(async (req, res) => {
    const chatId = groupOrChatId(req.params.chatId);
    const messageId = ownMessageId(req.params.messageId);
    const duration = req.body?.duration ?? 86_400;
    if (!Number.isInteger(duration) || duration < 1 || duration > MAX_PIN_SECONDS) {
      throw new InvalidInputError('duration precisa ser inteiro entre 1 e 2592000.');
    }
    await whatsapp.pin(chatId, messageId, duration);
    res.json({ success: true });
  }));

  app.post('/api/:session/chats/:chatId/messages/:messageId/unpin', sessionRoute(async (req, res) => {
    await whatsapp.unpin(groupOrChatId(req.params.chatId), ownMessageId(req.params.messageId));
    res.json({ success: true });
  }));

  app.use((req, res) => {
    res.status(404).json({ error: 'NAO_ENCONTRADO', message: 'Rota não existe.' });
  });

  app.use((error, req, res, next) => {
    if (error instanceof BridgeError) {
      res.status(error.status).json({ error: error.code, message: error.message });
      return;
    }
    if (error?.type === 'entity.parse.failed') {
      res.status(400).json({ error: 'ENTRADA_INVALIDA', message: 'JSON inválido.' });
      return;
    }
    if (error?.type === 'entity.too.large') {
      res.status(413).json({ error: 'ENTRADA_INVALIDA', message: 'Corpo grande demais.' });
      return;
    }
    log.error('http_error', { route: req.path, message: error?.message });
    if (res.headersSent) {
      next(error);
      return;
    }
    res.status(500).json({ error: 'ERRO_INTERNO', message: 'Falha inesperada no WhatsApp.' });
  });

  return app;
}

function sendBody(body, session) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new InvalidInputError('Corpo JSON obrigatório.');
  }
  assertSession(body.session, session);
  return { ...body, chatId: groupOrChatId(body.chatId) };
}

function parsePoll(poll) {
  if (!poll || typeof poll !== 'object' || Array.isArray(poll)) {
    throw new InvalidInputError('poll é obrigatório.');
  }
  const name = boundedText(poll.name, 'poll.name', MAX_POLL_NAME_LENGTH);
  if (!Array.isArray(poll.options) || poll.options.length < 2 || poll.options.length > MAX_POLL_OPTIONS) {
    throw new InvalidInputError(`poll.options precisa ter de 2 a ${MAX_POLL_OPTIONS} opções.`);
  }
  const options = poll.options.map((option) => boundedText(option, 'poll.options', MAX_POLL_OPTION_LENGTH));
  if (new Set(options).size !== options.length) {
    throw new InvalidInputError('poll.options não pode repetir opção.');
  }
  return { name, options, multipleAnswers: poll.multipleAnswers === true };
}

function boundedText(value, field, maxLength, { allowEmpty = false } = {}) {
  if (typeof value !== 'string') throw new InvalidInputError(`${field} precisa ser texto.`);
  if (!allowEmpty && !value.trim()) throw new InvalidInputError(`${field} está vazio.`);
  if (value.length > maxLength) throw new InvalidInputError(`${field} passou de ${maxLength} caracteres.`);
  return value;
}

function groupOrChatId(value) {
  if (!isValidChatId(value)) throw new InvalidInputError('chatId inválido.');
  return value;
}

function groupId(value) {
  const chatId = groupOrChatId(value);
  if (!chatId.endsWith('@g.us')) throw new InvalidInputError('Grupo inválido.');
  return chatId;
}

function ownMessageId(value) {
  const parsed = parseMessageId(value);
  if (!parsed || !MESSAGE_ID_PATTERN.test(parsed.id)) throw new InvalidInputError('messageId inválido.');
  return parsed.id;
}

function assertSession(value, session) {
  if (value !== session) throw new NotFoundError('Sessão não existe.');
}

function wrap(handler) {
  return (req, res, next) => {
    Promise.resolve(handler(req, res, next)).catch(next);
  };
}

function authorized(header, token) {
  if (!token || typeof header !== 'string' || !header.trim()) return false;
  const left = createHash('sha256').update(header.trim()).digest();
  const right = createHash('sha256').update(token).digest();
  return timingSafeEqual(left, right);
}

export async function start() {
  loadEnv();
  const config = loadConfig();
  const log = createLog({ level: config.logLevel });
  if (!config.apiKey) {
    throw new ConfigError('WAHA_API_KEY vazio: a ponte não sobe sem chave.');
  }

  mkdirSync(path.resolve(config.rootDir, 'logs'), { recursive: true });
  const pollStore = createPollStore(path.resolve(path.dirname(config.dbPath), 'bridge.sqlite'));
  const webhook = createWebhook({ url: config.webhookUrl, apiKey: config.apiKey, session: config.session, log });
  const client = await createZapoClient(config, toZapoLogger(log, { session: config.session }));
  const whatsapp = createWhatsApp({ client, log, pollStore, webhook });
  const app = createApp({ config, whatsapp, log });

  const server = await new Promise((resolve, reject) => {
    const listening = app.listen(config.port, config.host, () => resolve(listening));
    listening.on('error', reject);
  });
  log.info('listen', { host: config.host, port: config.port, session: config.session });
  whatsapp.start();

  let shuttingDown = false;
  async function shutdown(signal) {
    if (shuttingDown) return;
    shuttingDown = true;
    log.info('shutdown', { signal });
    const closed = new Promise((resolve) => server.close(resolve));
    server.closeIdleConnections();
    await closed;
    // disconnect (não logout): mantém o pareamento para o próximo boot.
    await whatsapp.stop();
    pollStore.close();
    process.exit(0);
  }

  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => {
      shutdown(signal).catch((error) => {
        log.error('shutdown_failed', { message: error.message });
        process.exit(1);
      });
    });
  }

  return server;
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
    console.error(JSON.stringify({ ts: new Date().toISOString(), level: 'error', event: 'fatal', message: error.message }));
    process.exit(1);
  });
}
