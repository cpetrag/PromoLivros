import { chmodSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import QRCode from 'qrcode';
import { SessionNotWorkingError } from './errors.js';
import { isGroupJid, serializeMessageId, toWahaJid, toZapoJid } from './jid.js';

export const SessionStatus = Object.freeze({
  STARTING: 'STARTING',
  SCAN_QR_CODE: 'SCAN_QR_CODE',
  WORKING: 'WORKING',
  FAILED: 'FAILED',
  STOPPED: 'STOPPED',
});

// Motivos em que reconectar sozinho piora as coisas: conta banida, aparelho
// removido, outra instância assumiu a sessão. Fica parado até alguém agir.
const FATAL_REASONS = new Set([
  'stream_error_replaced',
  'stream_error_device_removed',
  'stream_error_force_logout',
  'failure_not_authorized',
  'failure_banned',
  'failure_locked',
  'failure_client_too_old',
  'failure_bad_user_agent',
  'primary_identity_key_change',
]);

const RECONNECT_BASE_MS = 2_000;
const RECONNECT_MAX_MS = 5 * 60_000;
const GROUPS_CACHE_MS = 60_000;
const DEVICE_BROWSER_NAMES = {
  chrome: 'Chrome',
  firefox: 'Firefox',
  safari: 'Safari',
  edge: 'Edge',
  opera: 'Opera',
};

export async function createZapoClient(config, logger) {
  const [{ WaClient, createStore }, { createSqliteStore }, { wamPlugin }, { createMediaProcessor }] =
    await Promise.all([
      import('zapo-js'),
      import('@zapo-js/store-sqlite'),
      import('@zapo-js/wam'),
      import('@zapo-js/media-utils'),
    ]);

  // As chaves do aparelho pareado ficam aqui: só o dono do processo lê.
  mkdirSync(dirname(config.dbPath), { recursive: true, mode: 0o700 });
  chmodSync(dirname(config.dbPath), 0o700);
  const sqlite = createSqliteStore({
    path: config.dbPath,
    // O segredo da enquete precisa sobreviver a restarts para os votos continuarem legíveis.
    cacheTtlMs: { messageSecretMs: 45 * 24 * 60 * 60 * 1000 },
  });
  const store = createStore({
    backends: { sqlite },
    providers: {
      auth: 'sqlite',
      signal: 'sqlite',
      preKey: 'sqlite',
      session: 'sqlite',
      identity: 'sqlite',
      senderKey: 'sqlite',
      appState: 'sqlite',
      privacyToken: 'sqlite',
      messages: 'sqlite',
      threads: 'sqlite',
      contacts: 'sqlite',
    },
    cacheProviders: { messageSecret: 'sqlite', deviceList: 'sqlite', groupMetadata: 'sqlite' },
  });

  return new WaClient(
    {
      store,
      sessionId: config.session,
      deviceBrowser: DEVICE_BROWSER_NAMES[config.deviceBrowser],
      recoverFromClientTooOld: true,
      markOnlineOnConnect: false,
      plugins: [wamPlugin()],
      media: { processor: createMediaProcessor(), generateThumbnail: true, generateProbe: false },
    },
    logger,
  );
}

export function createWhatsApp({ client, log, pollStore, webhook }) {
  let status = SessionStatus.STOPPED;
  let qrCode = null;
  let attempt = 0;
  let reconnectTimer = null;
  let expectingClose = false;
  let groupsCache = { at: 0, groups: null };

  function setStatus(next, fields = {}) {
    if (status !== next) log.info('session_status', { from: status, to: next, ...fields });
    status = next;
  }

  client.on('auth_qr', (event) => {
    qrCode = event.qr;
    setStatus(SessionStatus.SCAN_QR_CODE);
  });

  client.on('auth_paired', () => {
    qrCode = null;
    setStatus(SessionStatus.STARTING, { paired: true });
  });

  client.on('connection', (event) => {
    if (event.status === 'open') {
      attempt = 0;
      qrCode = null;
      setStatus(SessionStatus.WORKING, { newLogin: Boolean(event.isNewLogin) });
      return;
    }
    qrCode = null;
    groupsCache = { at: 0, groups: null };
    if (expectingClose || event.reason === 'client_disconnected') {
      setStatus(SessionStatus.STOPPED, { reason: event.reason });
      return;
    }
    if (event.isLogout || FATAL_REASONS.has(event.reason)) {
      log.error('session_fatal', { reason: event.reason, code: event.code, logout: Boolean(event.isLogout) });
      setStatus(SessionStatus.FAILED, { reason: event.reason });
      return;
    }
    if (!client.getState().registered) {
      // QR expirou sem leitura: espera o painel pedir um novo em vez de gerar QR para sempre.
      setStatus(SessionStatus.STOPPED, { reason: event.reason });
      return;
    }
    setStatus(SessionStatus.STARTING, { reason: event.reason });
    scheduleReconnect();
  });

  client.on('message', (event) => {
    forwardMessage(event).catch((error) => log.error('forward_message_failed', { message: error.message }));
  });

  client.on('message_addon', (event) => {
    if (event.kind !== 'poll_vote') return;
    forwardVote(event).catch((error) => log.error('forward_vote_failed', { message: error.message }));
  });

  client.on('mex_notification', (event) => {
    if (event.kind === 'message_capping') {
      log.warn('message_capping', { status: event.cappingStatus, used: event.usedQuota, total: event.totalQuota });
    }
  });

  function scheduleReconnect() {
    if (reconnectTimer) return;
    const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attempt);
    attempt += 1;
    log.info('reconnect_scheduled', { delayMs: delay, attempt });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect().catch(() => {});
    }, delay);
    reconnectTimer.unref?.();
  }

  async function connect() {
    expectingClose = false;
    setStatus(SessionStatus.STARTING);
    try {
      await client.connect();
    } catch (error) {
      log.error('connect_failed', { message: error.message, attempt });
      scheduleReconnect();
      throw error;
    }
  }

  async function stop() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    expectingClose = true;
    try {
      await client.disconnect();
    } catch (error) {
      log.warn('disconnect_failed', { message: error.message });
    }
    setStatus(SessionStatus.STOPPED);
  }

  async function forwardMessage(event) {
    const { key } = event;
    if (!key?.isGroup || !event.message) return;
    const text = event.message.conversation
      ?? event.message.extendedTextMessage?.text
      ?? event.message.imageMessage?.caption
      ?? '';
    if (!text) return;
    await webhook.emit(
      'message',
      {
        id: serializeMessageId(key.remoteJid, key.id, Boolean(key.fromMe)),
        timestamp: event.timestampSeconds ?? Math.floor(Date.now() / 1000),
        from: toWahaJid(key.remoteJid),
        participant: toWahaJid(key.participant ?? ''),
        fromMe: Boolean(key.fromMe),
        body: text,
      },
      `msg_${key.id}`,
    );
  }

  async function forwardVote(event) {
    const { key, decrypted } = event;
    const pollId = serializeMessageId(key.remoteJid, event.targetMessageId, true);
    const names = decrypted?.selectedOptionNames
      ?? pollStore.resolveOptionNames(event.targetMessageId, decrypted?.pollVote?.selectedOptions);
    const voter = toWahaJid(key.participant ?? key.remoteJid);
    if (!names) {
      log.warn('poll_vote_unreadable', { poll: event.targetMessageId });
      await webhook.emit('poll.vote.failed', { vote: { id: key.id, from: voter }, poll: { id: pollId } }, `vote_${key.id}`);
      return;
    }
    const sentAt = Number(decrypted?.pollVote?.senderTimestampMs);
    await webhook.emit(
      'poll.vote',
      {
        vote: {
          id: key.id,
          from: voter,
          fromMe: Boolean(key.fromMe),
          selectedOptions: [...names],
          timestamp: Number.isFinite(sentAt) && sentAt > 0 ? sentAt : Date.now(),
        },
        poll: { id: pollId, to: toWahaJid(key.remoteJid) },
      },
      `vote_${key.id}`,
    );
  }

  function requireWorking() {
    if (status !== SessionStatus.WORKING) throw new SessionNotWorkingError();
  }

  async function sendContent(chatId, content) {
    requireWorking();
    const jid = toZapoJid(chatId);
    const result = await client.message.send(jid, content);
    return { id: serializeMessageId(jid, result.id, true), key: { id: result.id, remoteJid: chatId, fromMe: true } };
  }

  async function allGroups() {
    requireWorking();
    if (groupsCache.groups && Date.now() - groupsCache.at < GROUPS_CACHE_MS) return groupsCache.groups;
    const groups = await client.group.queryAllGroups();
    groupsCache = { at: Date.now(), groups };
    return groups;
  }

  // Não espera o connect: durante o pareamento ele só termina quando o QR é lido,
  // e o painel precisa da resposta HTTP antes disso para buscar o QR.
  function startInBackground() {
    connect().catch(() => {});
  }

  return {
    start() {
      if (status === SessionStatus.WORKING || status === SessionStatus.STARTING || status === SessionStatus.SCAN_QR_CODE) return;
      startInBackground();
    },

    stop,

    async restart() {
      await stop();
      attempt = 0;
      startInBackground();
    },

    status() {
      return status;
    },

    me() {
      const meJid = client.getCredentials?.()?.meJid;
      return meJid ? { id: toWahaJid(meJid) } : null;
    },

    async qrPng() {
      if (status !== SessionStatus.SCAN_QR_CODE || !qrCode) return null;
      return QRCode.toBuffer(qrCode, { type: 'png', width: 512, margin: 2 });
    },

    async groups() {
      const groups = await allGroups();
      return groups.map((group) => ({ id: group.jid, name: group.subject }));
    },

    async participants(chatId) {
      requireWorking();
      if (!isGroupJid(chatId)) return [];
      const metadata = await client.group.queryGroupMetadata(chatId);
      return (metadata.participants ?? []).map((participant) => ({
        id: toWahaJid(participant.jid),
        role: participant.isSuperAdmin ? 'superadmin' : participant.isAdmin ? 'admin' : 'participant',
      }));
    },

    async lids() {
      const groups = await allGroups();
      const pairs = new Map();
      for (const group of groups) {
        for (const participant of group.participants ?? []) {
          const lid = participant.lid ?? (participant.jid?.endsWith('@lid') ? participant.jid : undefined);
          const phone = participant.phoneNumber
            ?? (participant.jid?.endsWith('@s.whatsapp.net') ? participant.jid : undefined);
          if (lid && phone) pairs.set(toWahaJid(lid), toWahaJid(phone));
        }
      }
      return [...pairs].map(([lid, pn]) => ({ lid, pn }));
    },

    sendText(chatId, text) {
      return sendContent(chatId, { type: 'text', text });
    },

    sendImage(chatId, image, caption) {
      return sendContent(chatId, {
        type: 'image',
        media: image.bytes,
        mimetype: 'image/jpeg',
        width: image.width,
        height: image.height,
        ...(caption ? { caption } : {}),
      });
    },

    async sendPoll(chatId, name, options, multipleAnswers) {
      const sent = await sendContent(chatId, {
        type: 'poll',
        name,
        options,
        // 0 = "várias respostas" no WhatsApp; 1 = resposta única.
        selectableCount: multipleAnswers ? 0 : 1,
      });
      pollStore.remember(sent.key.id, toZapoJid(chatId), options);
      return sent;
    },

    async pin(chatId, messageId, durationSecs) {
      requireWorking();
      const jid = toZapoJid(chatId);
      await client.message.send(jid, { type: 'pin', target: { remoteJid: jid, id: messageId, fromMe: true }, durationSecs });
    },

    async unpin(chatId, messageId) {
      requireWorking();
      const jid = toZapoJid(chatId);
      await client.message.send(jid, { type: 'unpin', target: { remoteJid: jid, id: messageId, fromMe: true } });
    },
  };
}
