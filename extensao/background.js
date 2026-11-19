const DEFAULT_URL = "https://painel.promolivros.org";

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handle(message)
    .then(sendResponse)
    .catch((error) => sendResponse({ error: error.message || "Não falei com o painel." }));
  return true;
});

async function handle(message) {
  if (message.type === "config") {
    const stored = await chrome.storage.local.get({ panelUrl: DEFAULT_URL, token: "" });
    return stored;
  }
  if (message.type === "save-config") {
    await chrome.storage.local.set({
      panelUrl: String(message.panelUrl || DEFAULT_URL).replace(/\/$/, ""),
      token: String(message.token || "").trim(),
    });
    return { ok: true };
  }
  if (message.type === "guardar") return api("POST", "/extensao/livro", message.book || {});
  if (message.type === "caixa") return api("GET", "/extensao/caixa");
  if (message.type === "estado") return api("GET", "/extensao/estado?id=" + encodeURIComponent(message.id || ""));
  if (message.type === "previa") return api("POST", "/extensao/previa", { ordem: message.ordem || "" });
  if (message.type === "aplicar") return api("POST", "/extensao/aplicar", { previa_id: message.previaId || "" });
  if (message.type === "soltar") return api("POST", "/extensao/soltar", {});
  if (message.type === "tirar") return api("POST", "/extensao/tirar", { id: message.id, store: message.store });
  if (message.type === "ordem") return api("POST", "/extensao/ordem", { id: message.id, passo: message.passo });
  return { error: "Não entendi esse pedido." };
}

async function api(method, path, body) {
  const stored = await chrome.storage.local.get({ panelUrl: DEFAULT_URL, token: "" });
  if (!stored.token) return { error: "Cole o token da extensão nas configurações do painel lateral." };
  const response = await fetch(stored.panelUrl + path, {
    method,
    headers: {
      Authorization: "Bearer " + stored.token,
      "Content-Type": "application/json",
    },
    body: method === "GET" ? undefined : JSON.stringify(body || {}),
  });
  const payload = await response.json().catch(() => ({ error: "O painel não respondeu." }));
  if (!response.ok && !payload.error) payload.error = "O painel recusou o pedido.";
  return payload;
}
