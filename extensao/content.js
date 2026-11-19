const BUTTON_ID = "promo-livros-caixa";
const cardButtons = new Map();
const remembered = new Map();

function watch() {
  try {
    syncProductButton(readBook());
    syncCards();
  } catch (err) {
    console.warn("[promo-livros]", err);
  }
}

function syncProductButton(book) {
  const current = document.getElementById(BUTTON_ID);
  if (!book) {
    if (current) current.remove();
    return;
  }
  let button = current;
  if (!button) {
    button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.addEventListener("click", () => save(button, readBook()));
    document.documentElement.append(button);
  }
  if (button.dataset.id === book.id) return;
  button.dataset.id = book.id;
  button.textContent = "Por na caixa";
  askState(button, book.id);
}

function syncCards() {
  const live = new Set();
  listingCards().forEach((card) => {
    const book = card.read();
    if (!book) return;
    live.add(card.host);
    let button = cardButtons.get(card.host);
    if (!button || !button.isConnected) {
      button = makeCardButton(card);
      cardButtons.set(card.host, button);
      document.documentElement.append(button);
      askState(button, book.id);
    }
    placeCardButton(button, card.mount);
  });
  cardButtons.forEach((button, host) => {
    if (live.has(host) && host.isConnected) return;
    button.remove();
    cardButtons.delete(host);
  });
}

function makeCardButton(card) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "promo-livros-card";
  button.textContent = "Por na caixa";
  Object.assign(button.style, {
    position: "fixed",
    zIndex: "2147483646",
    display: "none",
    border: "0",
    borderRadius: "999px",
    padding: "6px 10px",
    background: "#1b1f24",
    color: "#fff",
    font: "600 12px/1.2 Segoe UI, sans-serif",
    cursor: "pointer",
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const chosen = card.read();
    if (chosen) save(button, chosen);
  });
  button.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  return button;
}

function placeCardButton(button, mount) {
  const rect = mount.getBoundingClientRect();
  const visible = rect.width > 40 && rect.height > 40 && rect.bottom > 0 && rect.top < window.innerHeight;
  if (!visible) {
    button.style.display = "none";
    return;
  }
  button.style.display = "block";
  button.style.top = Math.max(4, rect.top + 8) + "px";
  button.style.left = "auto";
  button.style.right = Math.max(4, window.innerWidth - rect.right + 8) + "px";
}

function listingCards() {
  const cards = [];
  document.querySelectorAll('[data-component-type="s-search-result"][data-asin]').forEach((node) => {
    const image = node.querySelector("img.s-image");
    cards.push({
      host: node,
      mount: (image && image.parentElement) || node,
      read: () => readSearchCard(node),
    });
  });
  document.querySelectorAll("bds-unified-book-faceout").forEach((node) => {
    const root = node.shadowRoot;
    if (!root) return;
    cards.push({
      host: node,
      mount: root.querySelector(".unified-book-faceout") || root,
      read: () => readFaceout(node),
    });
  });
  mercadoCards().forEach((card) => cards.push(card));
  return cards;
}

function mercadoCards() {
  const direct = [];
  const seen = new Set();
  document.querySelectorAll("li.ui-search-layout__item, .poly-card").forEach((node) => {
    const host = node.closest("li.ui-search-layout__item") || node;
    if (seen.has(host) || host.querySelector("h1.ui-pdp-title")) return;
    if (!mercadoId(host)) return;
    seen.add(host);
    direct.push({ host, mount: mercadoMount(host), read: () => readMercadoCard(host) });
  });
  if (direct.length) return direct;

  const cards = [];
  eachRoot(document).forEach((root) => {
    if (!root.querySelectorAll) return;
    root.querySelectorAll("a[href*='MLB'], a[href*='mlb']").forEach((link) => {
      const id = idFromHref(link.href);
      if (!id) return;
      const host = cardAround(link, id);
      if (!host || seen.has(host) || host.querySelector("h1.ui-pdp-title")) return;
      seen.add(host);
      cards.push({ host, mount: mercadoMount(host), read: () => readMercadoCard(host) });
    });
  });
  return cards;
}

function mercadoMount(host) {
  const cover = host.querySelector(".poly-card__portada");
  if (cover) return cover;
  const image = host.querySelector("img");
  return (image && image.parentElement) || host;
}

function eachRoot(start) {
  const roots = [];
  const stack = [start];
  const visited = new Set();
  while (stack.length) {
    const root = stack.pop();
    if (!root || visited.has(root)) continue;
    visited.add(root);
    roots.push(root);
    if (!root.querySelectorAll) continue;
    root.querySelectorAll("*").forEach((node) => {
      if (node.shadowRoot) stack.push(node.shadowRoot);
    });
  }
  return roots;
}

function cardAround(link, id) {
  let node = link.parentElement;
  let chosen = node || link;
  const seen = new Set();
  while (node && !seen.has(node) && node !== document.body && node !== document.documentElement) {
    seen.add(node);
    const ids = mlbIn(node);
    if (ids.length > 1) break;
    if (ids.length === 1 && ids[0] === id) chosen = node;
    const root = node.getRootNode ? node.getRootNode() : null;
    node = node.parentElement || (root && root.host) || null;
  }
  return chosen;
}

function mlbIn(node) {
  const found = new Set();
  if (!node.querySelectorAll) return [];
  node.querySelectorAll("a[href*='MLB'], a[href*='mlb']").forEach((link) => {
    const id = idFromHref(link.href);
    if (id) found.add(id);
  });
  return [...found];
}

function idFromHref(href) {
  const parsed = mlParse(href);
  return parsed ? parsed.id : "";
}

function mlParse(href) {
  let url;
  try {
    url = new URL(href, location.href);
  } catch (err) {
    return null;
  }
  if (url.hostname === "click1.mercadolivre.com.br" || url.pathname.includes("/mclics/")) return null;
  const path = url.pathname;
  const clean = url.origin + path;
  let match = path.match(/\/p\/(MLB\d{6,14})/i);
  if (match) return { id: match[1].toUpperCase(), url: clean };
  match = path.match(/\/up\/(MLBU\d{6,14})/i);
  if (match) return { id: match[1].toUpperCase(), url: clean };
  match = path.match(/\/(MLB)-?(\d{6,14})/i);
  if (match) return { id: "MLB" + match[2], url: clean };
  return null;
}

function readSearchCard(node) {
  const id = (node.getAttribute("data-asin") || "").toUpperCase();
  if (!/^[A-Z0-9]{10}$/.test(id) || node.querySelector("#productTitle")) return null;
  const title = textOf(node.querySelector("h2 span"));
  if (!title) return null;
  const image = node.querySelector("img.s-image");
  return {
    id,
    title,
    price: textOf(node.querySelector(".a-price:not(.a-text-price) .a-offscreen")),
    list_price: textOf(node.querySelector(".a-text-price .a-offscreen")),
    url: "https://www.amazon.com.br/dp/" + id,
    image: image ? image.currentSrc || image.src : "",
    author: "",
    category: "",
  };
}

function readFaceout(node) {
  const root = node.shadowRoot;
  const id = (node.getAttribute("data-csa-c-item-id") || "").toUpperCase();
  if (!root || !/^[A-Z0-9]{10}$/.test(id)) return null;
  const cover = root.querySelector("bds-book-cover-image");
  const image = cover && cover.shadowRoot ? cover.shadowRoot.querySelector("img") : null;
  const title = image && image.alt ? image.alt.trim() : "";
  if (!title) return null;
  const priceHost = root.querySelector("bds-book-price");
  const raw = priceHost && priceHost.shadowRoot ? priceHost.shadowRoot.textContent : "";
  return {
    id,
    title,
    price: lastPrice(raw),
    list_price: "",
    url: "https://www.amazon.com.br/dp/" + id,
    image: image ? image.currentSrc || image.src : "",
    author: "",
    category: "",
  };
}

function readMercadoCard(node) {
  const found = mercadoId(node);
  if (!found) return null;
  const title = textOf(
    node.querySelector(
      "a.poly-component__title, h2.poly-component__title-wrapper, h2 a, h3 a, .ui-search-item__title, .poly-component__title",
    ),
  );
  const image = node.querySelector("img");
  const named = title || (image && image.alt && image.alt.trim()) || "";
  if (!named || named.length < 3) return null;
  return {
    id: found.id,
    title: named,
    price: money(node) || lastPrice(node.textContent),
    list_price: oldMoney(node),
    url: found.url,
    image: pictureFromImage(image),
    author: "",
    category: "",
  };
}

function mercadoId(node) {
  if (!node.querySelectorAll) return null;
  for (const link of node.querySelectorAll("a[href]")) {
    const parsed = mlParse(link.href);
    if (parsed) return parsed;
  }
  return null;
}

function save(button, book) {
  if (!book) return;
  button.disabled = true;
  chrome.runtime.sendMessage({ type: "guardar", book }, (payload) => {
    button.disabled = false;
    if (!payload || payload.error) {
      button.textContent = payload && payload.error ? payload.error : "Não guardei.";
      return;
    }
    const place = payload.place || {};
    const state = (payload.book && payload.book.state) || place.kind;
    paint(button, state, place);
    const shot = pictureUrl((payload.book && payload.book.image) || book.image);
    if (shot) remembered.set(book.id, shot);
    openTray();
  });
}

function openTray() {
  chrome.runtime.sendMessage({ type: "caixa" }, (payload) => {
    if (!payload || payload.error) return;
    drawTray(payload);
  });
}

function drawTray(payload) {
  const plan = payload.plan || {};
  let tray = document.getElementById("promo-livros-tray");
  if (!tray) {
    tray = document.createElement("aside");
    tray.id = "promo-livros-tray";
    document.documentElement.append(tray);
  }
  tray.hidden = false;
  tray.textContent = "";
  const head = document.createElement("div");
  head.className = "promo-tray-head";
  const title = document.createElement("strong");
  const books = payload.books || [];
  title.textContent = "Caixa · " + books.length;
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Fechar";
  close.addEventListener("click", () => {
    tray.hidden = true;
  });
  head.append(title, close);
  const hint = document.createElement("p");
  hint.textContent = "A fila do site só muda quando você aplica. O que já saiu fica.";
  tray.append(head, hint);
  const covers = coverMap(payload);
  (plan.slots || []).forEach((slot) => {
    tray.append(trayLine(slot.clock, slot.amazon, covers), trayLine("", slot.ml, covers));
  });
  (plan.amanha || []).forEach((item) => tray.append(trayLine("Amanhã", item, covers)));
  const apply = document.createElement("button");
  apply.type = "button";
  apply.className = "promo-tray-apply";
  apply.textContent = "Substituir a fila daqui pra frente";
  apply.addEventListener("click", () => {
    apply.disabled = true;
    chrome.runtime.sendMessage({ type: "aplicar", previaId: plan.previa_id }, (result) => {
      apply.disabled = false;
      hint.textContent = result && result.error ? result.error : (result && result.message) || "Fila substituída.";
      if (result && result.plan) drawTray({ books, plan: result.plan });
    });
  });
  tray.append(apply);
}

function trayLine(clock, item, covers) {
  const row = document.createElement("div");
  row.className = "promo-tray-line";
  if (!item) return row;
  const when = document.createElement("span");
  when.textContent = clock;
  const name = document.createElement("span");
  name.textContent = item.title || "";
  const src = coverFor(item, covers);
  if (!src) {
    row.append(when, name);
    return row;
  }
  const image = document.createElement("img");
  image.alt = "";
  if (src.includes("media-amazon.com")) image.referrerPolicy = "no-referrer";
  image.addEventListener("error", () => image.remove());
  image.src = src;
  row.append(when, image, name);
  return row;
}

function coverMap(payload) {
  const covers = new Map();
  (payload.books || []).forEach((book) => {
    const url = pictureUrl(book.image);
    if (url) covers.set(book.id, url);
  });
  remembered.forEach((url, id) => {
    const clean = pictureUrl(url);
    if (clean) covers.set(id, clean);
  });
  return covers;
}

function coverFor(item, covers) {
  const known = (covers && covers.get(item.id)) || pictureUrl(item.image);
  if (known) return known;
  if (/^[A-Z0-9]{10}$/.test(item.id || "")) {
    return "https://m.media-amazon.com/images/P/" + item.id + ".jpg";
  }
  return "";
}

function pictureFromImage(image) {
  if (!image) return "";
  const candidates = [image.getAttribute("data-src"), image.getAttribute("data-zoom"), image.currentSrc, image.src];
  for (const candidate of candidates) {
    const url = pictureUrl(candidate);
    if (/^https:\/\/http2\.mlstatic\.com\/D_/.test(url)) return url;
  }
  for (const candidate of candidates) {
    const url = pictureUrl(candidate);
    if (url) return url;
  }
  return "";
}

function pictureUrl(value) {
  const url = String(value || "").split("?")[0].split("#")[0];
  if (!url.startsWith("https://") || url.includes("/frontend-assets/")) return "";
  if (/\.(jpg|jpeg|png|webp|gif)$/i.test(url)) return url;
  if (url.startsWith("https://m.media-amazon.com/images/")) return url;
  if (url.startsWith("https://http2.mlstatic.com/D_")) return url;
  return "";
}

function askState(button, id) {
  chrome.runtime.sendMessage({ type: "estado", id }, (payload) => {
    if (!payload || payload.error) return;
    paint(button, payload.state, payload);
  });
}

function paint(button, state, place) {
  const compact = button.classList.contains("promo-livros-card");
  if (state === "na_fila" || state === "fila") {
    button.textContent = !compact && place.clock ? "Na fila · " + place.clock : "Na fila";
    return;
  }
  if (state === "enviado" || state === "bloqueado") {
    button.textContent = !compact && place.clock ? "Saiu hoje · " + place.clock : "Saiu";
    return;
  }
  if (state === "reserva" || state === "amanha") {
    button.textContent = compact ? "Amanhã" : "Reserva de amanhã";
    return;
  }
  if (state === "caixa") {
    button.textContent = "Na caixa";
    return;
  }
  button.textContent = "Por na caixa";
}

function readBook() {
  const host = location.hostname;
  if (host.includes("amazon.")) return readAmazon();
  if (host.includes("mercadolivre.")) return readMercadoLivre();
  return null;
}

function readAmazon() {
  const fromUrl = location.pathname.match(/\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i);
  const fromField = document.querySelector("#ASIN, input[name='ASIN']");
  const id = ((fromUrl && fromUrl[1]) || (fromField && fromField.value) || "").toUpperCase();
  if (!/^[A-Z0-9]{10}$/.test(id)) return null;
  const title = text("#productTitle");
  if (!title) return null;
  const price = text("#corePriceDisplay_desktop_feature_div .a-price .a-offscreen")
    || text("#corePrice_feature_div .a-price .a-offscreen")
    || text(".a-price .a-offscreen");
  const list = text("#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen")
    || text(".a-price.a-text-price .a-offscreen");
  const image = document.querySelector("#landingImage, #imgBlkFront, #ebooksImgBlkFront");
  return {
    id,
    title,
    price,
    list_price: list,
    url: "https://www.amazon.com.br/dp/" + id,
    image: image ? image.src : "",
    author: text("#bylineInfo"),
    category: text("#wayfinding-breadcrumbs_feature_div"),
  };
}

function readMercadoLivre() {
  const found = mlParse(location.href);
  if (!found) return null;
  const title = text("h1.ui-pdp-title") || text("h1");
  if (!title) return null;
  const image = document.querySelector("img.ui-pdp-image, .ui-pdp-gallery__figure img");
  return {
    id: found.id,
    title,
    price: money(document),
    list_price: oldMoney(document),
    url: found.url,
    image: pictureFromImage(image),
    author: "",
    category: text(".ui-pdp-breadcrumb"),
  };
}

function text(selector) {
  return textOf(document.querySelector(selector));
}

function textOf(node) {
  return node ? node.textContent.replace(/\s+/g, " ").trim() : "";
}

function money(root) {
  const selectors = [
    ".poly-price__current .andes-money-amount",
    ".ui-pdp-price__second-line .andes-money-amount",
    ".ui-search-price__second-line .andes-money-amount",
    ".andes-money-amount:not(.andes-money-amount--previous)",
  ];
  for (const selector of selectors) {
    const node = root.querySelector(selector);
    const formatted = node && formatMoney(node);
    if (formatted) return formatted;
  }
  return "";
}

function oldMoney(root) {
  for (const selector of ["s.andes-money-amount--previous", ".ui-pdp-price__original-value"]) {
    const node = root.querySelector(selector);
    const formatted = node && formatMoney(node);
    if (formatted) return formatted;
  }
  return "";
}

function formatMoney(node) {
  const fractionNode = node.querySelector(".andes-money-amount__fraction");
  const centsNode = node.querySelector(".andes-money-amount__cents");
  if (fractionNode) {
    const fraction = textOf(fractionNode).replace(/[^\d.]/g, "");
    const cents = centsNode ? textOf(centsNode).replace(/\D/g, "").slice(0, 2).padStart(2, "0") : "00";
    return fraction ? "R$ " + fraction + "," + cents : "";
  }
  const match = textOf(node).match(/(\d{1,3}(?:\.\d{3})*|\d+)\s*,\s*(\d{2})/);
  return match ? "R$ " + match[1] + "," + match[2] : "";
}

function lastPrice(raw) {
  const matches = String(raw || "").match(/R\$\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?/g);
  if (!matches) return "";
  return matches[matches.length - 1].replace(/\s+/g, "");
}

watch();
setInterval(watch, 1000);
setTimeout(openTray, 800);
