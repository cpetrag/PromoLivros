import { createInterface } from 'node:readline';
import { loadConfig, loadEnv } from '../src/config.js';
import { contextOptions, launchPersistentContext } from '../src/launcher.js';

loadEnv();
const config = loadConfig();
const home = `${config.origin}/`;

let context;
try {
  context = await launchPersistentContext(
    config.profileDir,
    contextOptions({ headless: false }),
  );
} catch (error) {
  console.error('Não foi possível abrir o perfil da Amazon.');
  console.error('Pare o serviço antes do login: pm2 stop amz-link-api');
  console.error(error.message);
  process.exit(1);
}

const page = context.pages()[0] || await context.newPage();
try {
  await page.goto(home, { waitUntil: 'domcontentloaded' });
} catch (error) {
  console.error('A Amazon não abriu:', error.message);
  await context.close().catch(() => {});
  process.exit(1);
}

console.log('Faça login na Amazon (incluindo o 2FA) na janela que abriu.');
console.log('Quando terminar, feche a janela ou pressione Enter aqui.');
console.log('Não rode este comando com o serviço no ar: o perfil só pode ter um navegador.');

let closed = false;
async function finish() {
  if (closed) return;
  closed = true;
  await context.close().catch(() => {});
}

context.on('close', () => {
  closed = true;
});

const prompt = createInterface({ input: process.stdin, output: process.stdout });
const enter = new Promise((resolve) => {
  prompt.once('line', resolve);
});
const windowClosed = new Promise((resolve) => {
  context.once('close', resolve);
});

await Promise.race([enter, windowClosed]);
prompt.close();
await finish();
console.log('Perfil salvo. Suba o serviço de novo: pm2 start amz-link-api');
