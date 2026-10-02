import { LinkError } from './errors.js';
import { log as defaultLog } from './log.js';
import { resolveAsin as defaultResolve } from './resolve.js';

const TAG_PATTERN = /^[A-Za-z0-9_-]{1,80}$/;
const ASIN_PATTERN = /^[A-Z0-9]{10}$/;

export function buildLongUrl(asin, tag) {
  return `https://www.amazon.com.br/dp/${asin}?linkCode=sl2&tag=${tag}&ref_=as_li_ss_tl`;
}

export function createLinks({
  db,
  amazon,
  queue,
  resolve = defaultResolve,
  log = defaultLog,
}) {
  async function makeLink(input, tag) {
    const started = Date.now();
    if (amazon.whenReady) await amazon.whenReady();

    const usedTag = pickTag(tag, amazon.storeId);
    if (!TAG_PATTERN.test(usedTag) || !amazon.isTagValid(usedTag)) {
      throw new LinkError(
        'TAG_INVALIDA',
        'A tag não pertence a esta conta de associado.',
      );
    }

    const asin = await resolve(input);
    if (!asin || !ASIN_PATTERN.test(asin)) {
      throw new LinkError('ASIN_NAO_ENCONTRADO', 'Não foi possível identificar o ASIN.');
    }

    const longUrl = buildLongUrl(asin, usedTag);
    const existing = db.findLink(asin, usedTag);
    if (existing) {
      db.hit(asin, usedTag);
      const body = payload({ asin, tag: usedTag, longUrl, shortUrl: existing.shortUrl, cached: true });
      log.info('link', summary(body, started));
      return body;
    }

    let shortUrl = null;
    let cached = false;
    if (amazon.isSessionOk()) {
      try {
        const generated = await queue.enqueue(async () => {
          const raced = db.findLink(asin, usedTag);
          if (raced) return { shortUrl: raced.shortUrl, fromCache: true };
          const value = await amazon.shortenUrl(longUrl);
          if (value) db.saveLink(asin, usedTag, value);
          return { shortUrl: value || null, fromCache: false };
        });
        shortUrl = generated.shortUrl;
        cached = generated.fromCache;
        if (cached) db.hit(asin, usedTag);
      } catch (error) {
        log.error('shorten_failed', { message: error.message, asin, tag: usedTag });
      }
    }

    const body = payload({ asin, tag: usedTag, longUrl, shortUrl, cached });
    log.info('link', summary(body, started));
    return body;
  }

  return { makeLink };
}

function pickTag(tag, storeId) {
  if (tag === undefined || tag === null) return storeId;
  if (typeof tag !== 'string') return '';
  const trimmed = tag.trim();
  return trimmed || storeId;
}

function payload({ asin, tag, longUrl, shortUrl, cached }) {
  return {
    asin,
    tag,
    longUrl,
    shortUrl: shortUrl || null,
    url: shortUrl || longUrl,
    cached: Boolean(cached),
  };
}

function summary(body, started) {
  return {
    asin: body.asin,
    tag: body.tag,
    cached: body.cached,
    result: body.shortUrl ? 'short' : 'fallback',
    ms: Date.now() - started,
  };
}
