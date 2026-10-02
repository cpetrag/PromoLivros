import { createBrowser } from '../src/browser.js';
import { loadConfig, loadEnv } from '../src/config.js';
import { silentLog } from '../src/log.js';

loadEnv();
const config = loadConfig();
if (process.argv.includes('--headed')) config.headless = false;

const browser = createBrowser({ config, log: silentLog });
try {
  const data = await browser.call(
    `/associates/sitestripe/getStoreTagMap?marketplaceId=${encodeURIComponent(config.marketplaceId)}`,
  );
  const list = data?.storeTagMap?.[config.storeId];
  const tags = Array.isArray(list) ? list : [];
  console.log(JSON.stringify({
    sessionOk: data?.status === 1 && tags.length > 0,
    status: data?.status ?? null,
    storeId: config.storeId,
    tags,
  }));
} finally {
  await browser.close();
}
