#!/usr/bin/env node
// Abre o perfil do coletor para você entrar na Shopee à mão (o script nunca digita senha).
// Fecha sozinho quando a sessão aparece, ou depois de 10 minutos.
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WAIT_MS = 10 * 60 * 1000;

async function hasSession(context) {
  const cookies = await context.cookies('https://shopee.com.br');
  return cookies.some((cookie) => cookie.name === 'SPC_U' && cookie.value && cookie.value !== '-');
}

async function main() {
  const context = await chromium.launchPersistentContext(path.join(HERE, 'profile'), {
    channel: 'chrome',
    headless: false,
    locale: 'pt-BR',
    viewport: { width: 1366, height: 860 },
  });
  const page = context.pages()[0] ?? (await context.newPage());
  await page.goto('https://shopee.com.br/buyer/login', { waitUntil: 'domcontentloaded' });
  console.log('Entre na Shopee na janela do Chrome que abriu...');
  const deadline = Date.now() + WAIT_MS;
  while (Date.now() < deadline) {
    if (await hasSession(context)) {
      console.log('Sessão salva no perfil. Pode fechar.');
      await page.waitForTimeout(3000);
      await context.close();
      return;
    }
    await page.waitForTimeout(3000);
  }
  await context.close();
  console.error('Tempo esgotado sem login.');
  process.exit(3);
}

main().catch((error) => {
  console.error('Login falhou:', error.message);
  process.exit(1);
});
