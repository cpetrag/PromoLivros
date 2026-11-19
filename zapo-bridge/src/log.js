const LEVEL_ORDER = { trace: 10, debug: 20, info: 30, warn: 40, error: 50 };

export function createLog({ write = console.log, writeError = console.error, level = 'info' } = {}) {
  const minimum = LEVEL_ORDER[level] ?? LEVEL_ORDER.info;

  function emit(eventLevel, event, fields = {}) {
    if (LEVEL_ORDER[eventLevel] < minimum) return;
    const writer = LEVEL_ORDER[eventLevel] >= LEVEL_ORDER.warn ? writeError : write;
    writer(JSON.stringify({ ts: new Date().toISOString(), level: eventLevel, event, ...fields }, jsonSafe));
  }

  return {
    level,
    debug: (event, fields) => emit('debug', event, fields),
    info: (event, fields) => emit('info', event, fields),
    warn: (event, fields) => emit('warn', event, fields),
    error: (event, fields) => emit('error', event, fields),
  };
}

// Adapta o log JSON ao contrato Logger do zapo-js (trace..error + child com bindings).
export function toZapoLogger(log, bindings = {}) {
  const forward = (eventLevel) => (message, context) => {
    const target = eventLevel === 'trace' ? 'debug' : eventLevel;
    log[target](`zapo:${message}`, { ...bindings, ...safeContext(context) });
  };

  return {
    level: log.level,
    trace: forward('trace'),
    debug: forward('debug'),
    info: forward('info'),
    warn: forward('warn'),
    error: forward('error'),
    child: (extra) => toZapoLogger(log, { ...bindings, ...extra }),
  };
}

function jsonSafe(key, value) {
  return typeof value === 'bigint' ? value.toString() : value;
}

function safeContext(context) {
  if (!context || typeof context !== 'object') return {};
  const result = {};
  for (const [key, value] of Object.entries(context)) {
    if (value instanceof Error) result[key] = value.message;
    else if (value instanceof Uint8Array) result[key] = `<${value.byteLength} bytes>`;
    else result[key] = value;
  }
  return result;
}

export const silentLog = createLog({ write: () => {}, writeError: () => {} });
