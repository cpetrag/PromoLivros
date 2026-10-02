const ASIN_PATTERN = /^[A-Z0-9]{10}$/i;
const PATH_ASIN = /\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})(?=\/|$)/i;
const SHORT_HOSTS = new Set(['amzn.to', 'link.amazon', 'a.co']);
const SHORT_FETCH_MS = 8000;

const SHORT_FETCH_HEADERS = {
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  'accept-language': 'pt-BR,pt;q=0.9',
};

export async function resolveAsin(input, fetchImpl = globalThis.fetch) {
  if (typeof input !== 'string') return null;
  const trimmed = input.trim();
  if (!trimmed || trimmed.length > 2000) return null;
  if (ASIN_PATTERN.test(trimmed)) return trimmed.toUpperCase();

  const url = parseUrl(trimmed);
  if (!url || (url.protocol !== 'http:' && url.protocol !== 'https:')) return null;

  if (isShortHost(url.hostname)) return followShortLink(url, fetchImpl);
  if (isAmazonBr(url.hostname)) return extractAsin(url);
  return null;
}

export function extractAsin(url) {
  const match = url.pathname.match(PATH_ASIN);
  return match ? match[1].toUpperCase() : null;
}

async function followShortLink(url, fetchImpl) {
  try {
    const response = await fetchImpl(url.href, {
      redirect: 'follow',
      signal: AbortSignal.timeout(SHORT_FETCH_MS),
      headers: SHORT_FETCH_HEADERS,
    });
    if (response.body && typeof response.body.cancel === 'function') {
      await response.body.cancel().catch(() => {});
    }
    if (!response.url) return null;
    const finalUrl = parseUrl(response.url);
    return finalUrl ? extractAsin(finalUrl) : null;
  } catch {
    return null;
  }
}

function parseUrl(value) {
  try {
    return new URL(value);
  } catch {
    if (/^(?:www\.)?(?:amazon\.com\.br|amzn\.to|link\.amazon|a\.co)\//i.test(value)) {
      return new URL(`https://${value}`);
    }
    return null;
  }
}

function isShortHost(hostname) {
  return SHORT_HOSTS.has(normalizeHost(hostname));
}

function isAmazonBr(hostname) {
  const parts = normalizeHost(hostname).split('.');
  if (parts.length < 3) return false;
  return parts.slice(-3).join('.') === 'amazon.com.br';
}

function normalizeHost(hostname) {
  return hostname.toLowerCase().replace(/\.$/, '').replace(/^www\./, '');
}
