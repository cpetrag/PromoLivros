import { log as defaultLog } from './log.js';

export function createAmazon({ browser, db, config, alert, log = defaultLog }) {
  let tags = new Set(db.listTags());
  let sessionOk = false;
  let lastTagsRefresh = null;
  let observed = false;
  let refreshing = null;
  let initialRefresh = null;
  const refreshEveryMs = (config.tagsRefreshMin || 30) * 60 * 1000;

  async function applySession(next) {
    const previous = sessionOk;
    const seen = observed;
    sessionOk = next;
    observed = true;
    if (!seen) {
      if (!next) await alert.sessionDown();
      return;
    }
    if (previous === next) return;
    if (next) await alert.sessionUp();
    else await alert.sessionDown();
  }

  function refreshTags() {
    if (refreshing) return refreshing;
    refreshing = doRefresh().finally(() => {
      refreshing = null;
    });
    return refreshing;
  }

  async function doRefresh() {
    const path = `/associates/sitestripe/getStoreTagMap?marketplaceId=${encodeURIComponent(config.marketplaceId)}`;
    let data = null;
    try {
      data = await browser.call(path);
    } catch (error) {
      log.error('tags_refresh_failed', { message: error.message });
    }

    const nextTags = data?.status === 1 ? readTags(data, config.storeId) : null;
    if (!nextTags?.length) {
      await applySession(false);
      log.info('tags_refresh', { sessionOk: false, tags: tags.size });
      return getState();
    }

    tags = new Set(nextTags);
    try {
      db.replaceTags(nextTags);
    } catch (error) {
      log.error('tags_persist_failed', { message: error.message });
    }
    lastTagsRefresh = new Date().toISOString();
    await applySession(true);
    log.info('tags_refresh', { sessionOk: true, tags: tags.size });
    return getState();
  }

  function boot() {
    initialRefresh = refreshTags();
    const timer = setInterval(() => {
      refreshTags().catch((error) => {
        log.error('tags_refresh_failed', { message: error.message });
      });
    }, refreshEveryMs);
    timer.unref?.();
    return () => clearInterval(timer);
  }

  function whenReady() {
    return initialRefresh || Promise.resolve();
  }

  async function shortenUrl(longUrl) {
    const path = '/associates/sitestripe/getShortUrl'
      + `?longUrl=${encodeURIComponent(longUrl)}`
      + `&marketplaceId=${encodeURIComponent(config.marketplaceId)}`
      + `&storeId=${encodeURIComponent(config.storeId)}`;
    let data = null;
    try {
      data = await browser.call(path);
    } catch (error) {
      log.error('shorten_failed', { message: error.message });
    }

    if (!data) {
      await applySession(false);
      return null;
    }
    if (data.ok !== true || !isHttpUrl(data.shortUrl)) return null;
    return data.shortUrl;
  }

  function getState() {
    return {
      sessionOk,
      lastTagsRefresh,
      tags: [...tags].sort(),
    };
  }

  return {
    boot,
    whenReady,
    refreshTags,
    shortenUrl,
    isTagValid(tag) {
      return tags.has(tag);
    },
    isSessionOk() {
      return sessionOk;
    },
    getState,
    get storeId() {
      return config.storeId;
    },
  };
}

function readTags(payload, storeId) {
  const map = payload.storeTagMap;
  if (!map || typeof map !== 'object' || Array.isArray(map)) return [];
  const direct = map[storeId];
  const source = Array.isArray(direct) ? direct : Object.values(map).flat();
  const unique = new Set();
  for (const value of source) {
    if (typeof value !== 'string') continue;
    const tag = value.trim();
    if (tag) unique.add(tag);
  }
  return [...unique];
}

function isHttpUrl(value) {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:';
  } catch {
    return false;
  }
}
