const USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

// Único lugar que abre o Chromium. Login e serviço usam o mesmo perfil.
// Para trocar pelo CloakBrowser, substitua launchPersistentContext e mantenha contextOptions.

export function contextOptions({ headless }) {
  return {
    headless: Boolean(headless),
    locale: 'pt-BR',
    timezoneId: 'America/Sao_Paulo',
    viewport: { width: 1366, height: 900 },
    userAgent: USER_AGENT,
    handleSIGINT: false,
    handleSIGTERM: false,
    handleSIGHUP: false,
  };
}

export async function launchPersistentContext(profileDir, options) {
  const { chromium } = await import('playwright');
  return chromium.launchPersistentContext(profileDir, options);
}
