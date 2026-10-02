import { log as defaultLog } from './log.js';
import { contextOptions, launchPersistentContext } from './launcher.js';

export function createBrowser({
  config,
  launch = launchPersistentContext,
  log = defaultLog,
}) {
  let context = null;
  let page = null;
  let gate = Promise.resolve();
  let maintenance = null;

  function exclusive(task) {
    const run = gate.then(task, task);
    gate = run.then(() => undefined, () => undefined);
    return run;
  }

  async function dispose() {
    const current = context;
    context = null;
    page = null;
    if (!current) return;
    try {
      await current.close();
    } catch (error) {
      log.error('browser_close_failed', { message: error.message });
    }
  }

  async function ensurePage() {
    if (page && !page.isClosed()) return page;
    await dispose();
    context = await launch(config.profileDir, contextOptions({ headless: config.headless }));
    context.on('close', () => {
      context = null;
      page = null;
    });
    const existing = typeof context.pages === 'function' ? context.pages() : [];
    page = existing[0] || await context.newPage();
    page.setDefaultTimeout?.(20_000);
    page.setDefaultNavigationTimeout?.(45_000);
    page.on?.('close', () => {
      page = null;
    });
    page.on?.('crash', () => {
      page = null;
    });
    await page.goto(`${config.origin}/`, { waitUntil: 'domcontentloaded' });
    return page;
  }

  function call(apiPath) {
    return exclusive(async () => {
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        try {
          const current = await ensurePage();
          return await current.evaluate(fetchInPage, apiPath);
        } catch (error) {
          log.error('browser_call_failed', { message: error.message, attempt });
          await dispose();
        }
      }
      return null;
    });
  }

  function startMaintenance() {
    if (!config.pageReloadMs) return () => {};
    maintenance = setInterval(() => {
      exclusive(async () => {
        if (!page || page.isClosed()) return;
        try {
          await page.goto(`${config.origin}/`, { waitUntil: 'domcontentloaded' });
          log.info('page_reload', {});
        } catch (error) {
          log.error('page_reload_failed', { message: error.message });
          await dispose();
        }
      }).catch((error) => {
        log.error('page_reload_failed', { message: error.message });
      });
    }, config.pageReloadMs);
    maintenance.unref?.();
    return () => clearInterval(maintenance);
  }

  async function close() {
    if (maintenance) clearInterval(maintenance);
    await exclusive(() => dispose());
  }

  return { call, startMaintenance, close };
}

export async function fetchInPage(apiPath) {
  const response = await globalThis.fetch(apiPath, {
    credentials: 'include',
    headers: { accept: 'application/json' },
  });
  const text = await response.text();
  try {
    const data = JSON.parse(text);
    if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
    return data;
  } catch {
    return null;
  }
}
