const PHONE_SERVER = 's.whatsapp.net';
const WAHA_PHONE_SERVER = 'c.us';
const CHAT_ID_PATTERN = /^[0-9A-Za-z.:_-]{1,64}@(c\.us|s\.whatsapp\.net|g\.us|lid)$/;

export function isValidChatId(value) {
  return typeof value === 'string' && CHAT_ID_PATTERN.test(value);
}

// O Python foi escrito para o WAHA, que usa @c.us; o zapo fala @s.whatsapp.net.
export function toWahaJid(jid) {
  if (typeof jid !== 'string' || !jid.includes('@')) return '';
  const [user, server] = splitJid(jid);
  const bareUser = user.split(':')[0];
  return `${bareUser}@${server === PHONE_SERVER ? WAHA_PHONE_SERVER : server}`;
}

export function toZapoJid(jid) {
  if (typeof jid !== 'string' || !jid.includes('@')) return '';
  const [user, server] = splitJid(jid);
  return `${user}@${server === WAHA_PHONE_SERVER ? PHONE_SERVER : server}`;
}

export function isGroupJid(jid) {
  return typeof jid === 'string' && jid.endsWith('@g.us');
}

// Mesmo formato do WAHA ("true_<chat>_<id>"), para que ids antigos e novos convivam no banco.
export function serializeMessageId(chatJid, messageId, fromMe = true) {
  return `${fromMe ? 'true' : 'false'}_${toWahaJid(chatJid)}_${messageId}`;
}

export function parseMessageId(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const raw = value.trim();
  const parts = raw.split('_');
  if ((parts[0] === 'true' || parts[0] === 'false') && parts.length >= 3 && parts[1].includes('@')) {
    return { id: parts[2], fromMe: parts[0] === 'true', chatId: parts[1] };
  }
  return { id: raw, fromMe: true, chatId: null };
}

function splitJid(jid) {
  const at = jid.lastIndexOf('@');
  return [jid.slice(0, at), jid.slice(at + 1)];
}
