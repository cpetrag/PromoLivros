"""Página em que a fila do dia é a marcação do CSV."""
from __future__ import annotations

import json
from html import escape

from promo_livros.catalog import CatalogBook, cover_url
from promo_livros.dashboard_pages import _page
from promo_livros.formatter import format_brl

_PAGE = 24

_STYLE = """
body.wide > main { width: min(76rem, calc(100% - 1.5rem)); padding-bottom: 5.5rem; }
.curation-head { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; flex-wrap: wrap; }
.curation-head h1 { margin-bottom: 0.2rem; }
.context { color: var(--muted); margin-top: 0; }
.context a { color: var(--blue); }
.import-menu summary { cursor: pointer; }
.token code { display: block; word-break: break-all; font-size: 0.82rem; }
.store-switch { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.7rem; margin: 0.8rem 0; }
.store-switch .store-shopee[aria-pressed="true"] { border-color: #ee4d2d; background: color-mix(in srgb, #ee4d2d 12%, var(--surface)); }
.store-switch .store-magalu[aria-pressed="true"] { border-color: #0086ff; background: color-mix(in srgb, #0086ff 12%, var(--surface)); }
.store-switch button { text-align: left; border-radius: 16px; min-height: 4.4rem; background: var(--surface); color: var(--ink); border: 1px solid var(--line); }
.store-switch .store-amazon[aria-pressed="true"] { border-color: var(--amber); background: color-mix(in srgb, var(--amber) 18%, var(--surface)); }
.store-switch .store-ml[aria-pressed="true"] { border-color: var(--blue); background: color-mix(in srgb, var(--amber) 14%, color-mix(in srgb, var(--blue) 12%, var(--surface))); }
.store-switch strong { display: block; }
.store-switch span { color: var(--muted); font-weight: 500; }
.curation-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 400px); gap: 1rem; align-items: start; }
.filters { position: sticky; top: 0; z-index: 3; background: color-mix(in srgb, var(--bg) 92%, transparent); padding: 0.6rem 0; display: grid; gap: 0.5rem; }
.filters-row, .pills, .seg { display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: center; }
.filters input[type="search"] { min-width: 12rem; flex: 1; }
.seg button, .pills button { border-radius: 999px; }
.books { display: grid; grid-template-columns: repeat(auto-fill, minmax(205px, 1fr)); gap: 0.7rem; }
.card { display: flex; flex-direction: column; gap: 0.35rem; text-align: left; width: 100%; background: var(--surface); color: var(--ink); border: 1px solid var(--line); border-radius: 16px; padding: 0.55rem; position: relative; }
.card img, .card .cover { width: 100%; height: 9.5rem; object-fit: contain; background: color-mix(in srgb, var(--line) 55%, var(--surface)); border-radius: 10px; }
.card strong { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 2.6em; }
.card em { color: var(--muted); font-style: normal; font-size: 0.85rem; }
.card-box { position: relative; display: flex; }
.store-link { display: inline-grid; place-items: center; min-width: 1.7rem; height: 1.7rem; border-radius: 999px; background: var(--surface); border: 1px solid var(--line); color: var(--ink); text-decoration: none; font-size: 0.85rem; }
.store-link:hover, .store-link:focus-visible { border-color: var(--blue); color: var(--blue); }
.card-box .store-link { position: absolute; top: 0.8rem; left: 0.8rem; z-index: 1; }
.card .url { color: var(--muted); font-size: 0.75rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card .reviews { color: var(--muted); font-size: 0.82rem; font-variant-numeric: tabular-nums; }
.card .price b, .half b { color: var(--chip-green-ink); }
.card.on { border-color: var(--blue); background: color-mix(in srgb, var(--blue) 12%, var(--surface)); }
.card.later { border-color: var(--amber); background: color-mix(in srgb, var(--amber) 16%, var(--surface)); }
.card.sent { border-style: dashed; opacity: 0.72; }
.mark { position: absolute; top: 0.8rem; right: 0.8rem; width: 1.7rem; height: 1.7rem; border-radius: 999px; display: grid; place-items: center; background: var(--surface); border: 1px solid var(--line); font-size: 0.8rem; }
.card.on .mark { background: var(--blue); color: white; border-color: var(--blue); }
.chips { display: flex; flex-wrap: wrap; gap: 0.25rem; }
.chip { border-radius: 999px; padding: 0.05rem 0.45rem; font-size: 0.75rem; background: var(--line); color: var(--ink); }
.chip.go { background: var(--chip-green); color: var(--chip-green-ink); }
.chip.hot { background: color-mix(in srgb, var(--red) 16%, var(--surface)); color: var(--red); }
.chip.wait { background: color-mix(in srgb, var(--amber) 20%, var(--surface)); color: var(--amber); }
.why { color: var(--muted); font-size: 0.85rem; }
.queue-col { position: sticky; top: 0.5rem; max-height: calc(100vh - 6.5rem); overflow: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 0.8rem; }
.queue-col h2 { margin: 0 0 0.4rem; }
.caps { display: grid; gap: 0.35rem; margin-bottom: 0.6rem; }
.cap { height: 0.45rem; background: var(--line); border-radius: 999px; overflow: hidden; }
.cap i { display: block; height: 100%; background: var(--blue); }
.cap.az i { background: var(--amber); }
.slot-row { display: grid; grid-template-columns: 3.2rem 1fr 1fr; gap: 0.35rem; margin: 0.35rem 0; align-items: stretch; }
.slot-row.warn { box-shadow: inset 3px 0 0 var(--amber); }
.clock { font-family: ui-monospace, monospace; color: var(--blue); font-weight: 700; padding-top: 0.4rem; }
.half { border-radius: 10px; padding: 0.35rem; min-height: 4.2rem; display: grid; grid-template-columns: 2rem 1fr; gap: 0.3rem; }
.half.amazon { background: color-mix(in srgb, var(--amber) 18%, var(--surface)); }
.half.ml { background: color-mix(in srgb, var(--amber) 10%, color-mix(in srgb, var(--blue) 14%, var(--surface))); }
.half img { width: 2rem; height: 2.8rem; object-fit: contain; background: var(--surface); }
.half .cover-gap { display: block; width: 2rem; height: 2.8rem; border-radius: 4px; background: color-mix(in srgb, var(--line) 55%, var(--surface)); }
.half p { margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 0.82rem; }
.half.empty { display: grid; place-items: center; border: 1px dashed var(--line); color: var(--muted); font-size: 0.8rem; background: transparent; }
.half .tools { grid-column: 1 / -1; display: flex; gap: 0.2rem; }
.half { cursor: pointer; border: 1px solid transparent; }
.half.is-picked { border-color: var(--ink); box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 35%, transparent); }
.half.is-target { border-color: var(--blue); border-style: dashed; }
.clock { display: flex; flex-direction: column; gap: 0.2rem; align-items: flex-start; }
.clock .row-menu { min-height: 32px; padding: 0 0.45rem; font-size: 1rem; line-height: 1; }
.draft-hint { color: var(--muted); font-size: 0.8rem; margin: 0.4rem 0; }
.draft-note { background: color-mix(in srgb, var(--blue) 10%, var(--surface)); border-radius: 10px; padding: 0.45rem 0.6rem; font-size: 0.85rem; }
.draft-note button { margin-top: 0.3rem; }
.draft-pick { position: sticky; top: 0.5rem; z-index: 4; display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; justify-content: space-between; background: color-mix(in srgb, var(--blue) 14%, var(--surface)); border-radius: 10px; padding: 0.45rem 0.6rem; font-size: 0.85rem; }
.draft-pick[hidden], .draft-note[hidden] { display: none; }
#draft-menu { border: 0; border-radius: 14px; width: min(26rem, calc(100% - 1.5rem)); padding: 1rem 1.1rem; }
#draft-menu label { display: grid; gap: 0.3rem; margin: 0.5rem 0; }
#draft-menu select { min-height: 40px; }
.draft-actions { display: grid; gap: 0.45rem; margin-top: 0.6rem; }
.blocked { background: color-mix(in srgb, var(--red) 12%, var(--surface)); color: var(--red); border-radius: 12px; padding: 0.5rem 0.7rem; }
.action-bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 6; display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; justify-content: space-between; padding: 0.7rem 1rem; background: var(--surface); border-top: 1px solid var(--line); }
.action-bar .warn { color: var(--amber); }
.action-bar .bad { color: var(--red); }
dialog { border: 0; border-radius: 16px; background: var(--surface); color: var(--ink); width: min(40rem, calc(100% - 1.5rem)); }
#fila-run { max-height: min(36rem, calc(100vh - 2rem)); display: flex; flex-direction: column; padding: 1rem 1.1rem; }
#fila-now { margin: 0.2rem 0 0.6rem; font-weight: 700; }
#fila-steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.35rem; overflow: auto; min-height: 8rem; }
#fila-steps li[data-state="ok"] { color: var(--chip-green-ink); }
#fila-steps li[data-state="run"] { font-weight: 700; }
#fila-steps li[data-state="erro"] { color: var(--red); }
#fila-quebrados:not([hidden]) { display: grid; gap: 0.45rem; margin-top: 0.8rem; }
#fila-quebrados ul { margin: 0; padding-left: 1.1rem; }
#fila-quebrados li { margin: 0.35rem 0; }
#fila-quebrados a { word-break: break-all; }
#fila-run-close, #fila-run-resolve { margin-top: 0.8rem; align-self: start; }
dialog::backdrop { background: color-mix(in srgb, var(--ink) 40%, transparent); }
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 0.8rem; }
#toast { position: fixed; bottom: 4.6rem; left: 50%; transform: translateX(-50%); background: var(--pill); color: var(--pill-ink); border-radius: 999px; padding: 0.45rem 0.8rem; z-index: 7; }
@media (max-width: 1060px) {
  .curation-layout { grid-template-columns: 1fr; }
  .queue-col { position: static; max-height: none; order: 2; }
}
@media (max-width: 520px) {
  body.wide > main { width: calc(100% - 1rem); }
  .books, .store-switch, .cols, .slot-row { grid-template-columns: 1fr; }
  .clock { padding-top: 0; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
"""

_SCRIPT = r"""
(function () {
  var node = document.getElementById("curation-data");
  if (!node) return;
  var data = JSON.parse(node.textContent);
  var state = {
    loja: data.loja || "amazon",
    shown: 24,
    q: "",
    sort: "discount",
    min: 0,
    onlyPicked: false,
    onlyLow: false,
    hideKids: true,
    hideNotBook: true,
    hideSent: true
  };
  var plan = data.plan || { slots: [], bloqueados: [], amanha: [], clocks: [], avisos: 0, previa_id: "" };
  var timer = 0;
  var toastTimer = 0;

  function $(id) { return document.getElementById(id); }
  var LOJA_PARAM = { amazon: "amazon", ml: "mercadolivre", shopee: "shopee", magalu: "magalu" };
  data.shopee = data.shopee || [];
  data.magalu = data.magalu || [];
  function listOf(loja) {
    return loja === "ml" ? data.ml : loja === "shopee" ? data.shopee : loja === "magalu" ? data.magalu : data.amazon;
  }
  function books() { return listOf(state.loja); }
  function allBooks() { return data.amazon.concat(data.ml, data.shopee, data.magalu); }
  function secondStore() { return state.loja === "ml" || state.loja === "shopee" || state.loja === "magalu"; }
  function money(cents) {
    if (!cents) return "";
    return "R$ " + (cents / 100).toFixed(2).replace(".", ",");
  }
  function sentClocks(book) {
    var list = (data.enviados && data.enviados[book.asin]) || [];
    if (book.state === "enviado" && !list.length) return ["hoje"];
    return list;
  }
  function placeOf(asin) {
    var found = null;
    (plan.slots || []).forEach(function (slot) {
      ["amazon", "ml"].forEach(function (side) {
        if (slot[side] && slot[side].asin === asin) found = { kind: "fila", clock: slot.clock };
      });
    });
    if (found) return found;
    (plan.amanha || []).forEach(function (item) {
      if (item.id === asin) found = { kind: "amanha" };
    });
    if (found) return found;
    (plan.bloqueados || []).forEach(function (item) {
      if (item.id === asin) found = { kind: "bloqueado", clocks: item.clocks || [] };
    });
    return found;
  }
  function filtered() {
    var query = state.q.trim().toLowerCase();
    return books().filter(function (book) {
      var sent = sentClocks(book).length > 0 || book.state === "enviado";
      if (state.hideSent && sent) return false;
      if (state.hideKids && book.kids) return false;
      if (state.hideNotBook && book.notBook) return false;
      if (state.onlyPicked && !(book.picked || book.state === "reserva" || book.state === "na_fila")) return false;
      if (state.onlyLow && !book.low && !book.lowDays) return false;
      if (state.min && (book.discount || 0) < state.min) return false;
      if (!query) return true;
      return (book.title + " " + book.author + " " + book.category).toLowerCase().indexOf(query) >= 0;
    }).sort(function (a, b) {
      if (state.sort === "price-asc") return (a.price_cents || 1e12) - (b.price_cents || 1e12);
      if (state.sort === "price-desc") return (b.price_cents || 0) - (a.price_cents || 0);
      if (state.sort === "title") return a.title.localeCompare(b.title, "pt");
      if (state.sort === "reviews") return (b.reviews || b.sold || 0) - (a.reviews || a.sold || 0) || (b.rating || 0) - (a.rating || 0);
      return (b.discount || 0) - (a.discount || 0) || a.position - b.position;
    });
  }
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body
    }).then(function (response) { return response.json(); }).then(function (payload) {
      if (payload.error) throw new Error(payload.error);
      return payload;
    });
  }
  function toast(message, undo) {
    var box = $("toast");
    box.hidden = false;
    box.textContent = "";
    box.append(document.createTextNode(message + " "));
    if (undo) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "ghost";
      button.textContent = "Desfazer";
      button.addEventListener("click", function () { undo(); box.hidden = true; });
      box.append(button);
    }
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.hidden = true; }, 8000);
  }
  function schedulePreview() {
    clearTimeout(timer);
    timer = setTimeout(loadPreview, 250);
  }
  function loadPreview() {
    return post("/curadoria/fila/previa", "ordem=" + encodeURIComponent(data.ordem || "mine"))
      .then(function (payload) {
        plan = payload;
        renderQueue();
        renderCards();
        renderBar();
      })
      .catch(function (error) { toast(error.message || "Não consegui recalcular a fila."); });
  }
  function setPressed(id, on) {
    var button = $(id);
    if (button) button.setAttribute("aria-pressed", on ? "true" : "false");
  }
  function renderStores() {
    ["amazon", "ml", "shopee", "magalu"].forEach(function (loja) {
      var button = $("store-" + loja);
      if (!button) return;
      var list = listOf(loja);
      var marked = list.filter(function (book) {
        return book.picked || book.state === "marcado" || book.state === "na_fila" || book.state === "reserva";
      }).length;
      button.setAttribute("aria-pressed", state.loja === loja ? "true" : "false");
      button.querySelector("b").textContent = list.length + " no CSV · " + marked + " marcados";
    });
    var low = $("only-low");
    if (low) {
      var storeName = state.loja === "shopee" ? "da Shopee" : state.loja === "magalu" ? "da Magazine Luiza" : "do Mercado Livre";
      var history = books().some(function (book) { return book.historyDays; });
      low.disabled = secondStore() && !history;
      low.title = !secondStore() ? "" : history
        ? "Menor preço desde que o painel começou a guardar o histórico " + storeName + "."
        : "O histórico " + storeName + " precisa de 7 dias para comparar.";
    }
  }
  function renderCards() {
    var box = $("catalog");
    var rows = filtered();
    var visible = rows.slice(0, state.shown);
    box.textContent = "";
    $("shown").textContent = visible.length + " livros · " + (books().length - rows.length) + " ocultos pelos filtros";
    if (!rows.length) {
      var empty = document.createElement("p");
      empty.textContent = "Nenhum livro com esses filtros.";
      var clear = document.createElement("button");
      clear.type = "button";
      clear.className = "ghost";
      clear.textContent = "Limpar filtros";
      clear.addEventListener("click", resetFilters);
      box.append(empty, clear);
      $("more").hidden = true;
      return;
    }
    visible.forEach(function (book) { box.append(card(book)); });
    var more = $("more");
    var left = rows.length - visible.length;
    more.hidden = left <= 0;
    more.textContent = "Mostrar mais " + Math.min(24, left) + " de " + rows.length;
  }
  function card(book) {
    var place = placeOf(book.asin);
    var sent = sentClocks(book);
    var button = document.createElement("button");
    button.type = "button";
    button.className = "card";
    var marked = book.picked || book.state === "marcado" || book.state === "na_fila" || book.state === "reserva";
    if (sent.length || (place && place.kind === "bloqueado")) button.classList.add("sent");
    else if (place && place.kind === "fila") button.classList.add("on");
    else if ((place && place.kind === "amanha") || book.state === "reserva") button.classList.add("later");
    button.setAttribute("aria-pressed", marked && !button.classList.contains("sent") ? "true" : "false");
    var img = document.createElement("img");
    img.alt = "";
    img.src = book.image || "";
    var title = document.createElement("strong");
    title.textContent = book.title;
    var category = document.createElement("em");
    category.textContent = book.category || "";
    var price = document.createElement("span");
    price.className = "price";
    price.innerHTML = escapeText(book.price || money(book.price_cents));
    if (book.discount) price.innerHTML += " <b>−" + book.discount + "%</b>";
    var social = reviewLine(book);
    var chips = document.createElement("span");
    chips.className = "chips";
    if (place && place.kind === "fila") chips.append(chip(place.clock, "go"));
    if ((place && place.kind === "amanha") || book.state === "reserva") chips.append(chip("não cabe · amanhã", "wait"));
    if (sent.length) chips.append(chip("saiu " + sent.join(" e "), "hot"));
    if (book.low) chips.append(chip("menor 365d", "go"));
    if (book.lowDays) chips.append(chip(book.lowDays >= 365 ? "menor 365d" : "menor em " + book.lowDays + "d", "go"));
    else if (secondStore() && !book.low && !book.historyDays) chips.append(chip("sem histórico", ""));
    if (book.kids) chips.append(chip("infantil", ""));
    if (book.notBook) chips.append(chip("não é livro", ""));
    if (book.state === "caixa") chips.append(chip("na caixa", "wait"));
    var mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = button.classList.contains("on") && data.ordem === "mine" ? "✓" : (marked ? "✓" : "");
    button.append(img, title, category, price);
    if (social) button.append(social);
    var address = urlLine(book.url);
    if (address) button.append(address);
    button.append(chips, mark);
    var why = document.createElement("span");
    why.className = "why";
    why.hidden = true;
    button.append(why);
    button.addEventListener("click", function () {
      if (sent.length || (place && place.kind === "bloqueado")) {
        var hour = (sent[0] && sent[0] !== "hoje") ? sent[0] : ((place && place.clocks && place.clocks[0]) || "");
        why.hidden = false;
        why.textContent = hour
          ? "Este livro saiu hoje às " + hour + ". Ele volta a ficar disponível amanhã."
          : "Este livro saiu hoje. Ele volta a ficar disponível amanhã.";
        return;
      }
      var next = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", next ? "true" : "false");
      book.picked = next;
      book.state = next ? "marcado" : "";
      post("/curadoria/marcar", "asin=" + encodeURIComponent(book.asin) + "&loja=" + encodeURIComponent(secondStore() ? state.loja : "amazon") + "&on=" + (next ? "1" : "0"))
        .then(function () { schedulePreview(); renderStores(); })
        .catch(function (error) { toast(error.message || "Não salvei a marcação."); });
    });
    // Link dentro de <button> é HTML inválido; o card vira um contêiner com o botão e o link lado a lado.
    var link = storeLink(book.url, state.loja);
    if (!link) return button;
    var box = document.createElement("div");
    box.className = "card-box";
    box.append(button, link);
    return box;
  }
  var STORE_NAMES = { amazon: "Amazon", ml: "Mercado Livre", shopee: "Shopee", magalu: "Magazine Luiza" };
  function safeUrl(url) {
    // A URL vem de CSV e de crawler: só https vira link, para não abrir javascript: nem outro esquema.
    var target;
    try { target = new URL(String(url || "")); } catch (error) { return null; }
    return target.protocol === "https:" ? target : null;
  }
  function urlLine(url) {
    var target = safeUrl(url);
    if (!target) return null;
    var line = document.createElement("span");
    line.className = "url";
    var path = target.pathname;
    try { path = decodeURIComponent(path); } catch (error) { /* % solto no link: mostra como veio */ }
    line.textContent = target.hostname.replace(/^www\./, "") + path.replace(/\/$/, "");
    line.title = target.href;
    return line;
  }
  function storeLink(url, store) {
    var target = safeUrl(url);
    if (!target) return null;
    var link = document.createElement("a");
    link.className = "store-link";
    link.href = target.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "↗";
    var host = target.hostname;
    var known = /shopee\./.test(host) ? "shopee" : /magalu\.|magazineluiza\.|magazinevoce\./.test(host) ? "magalu" : /mercadoli[vb]re\.|meli\.la$/.test(host) ? "ml" : /amazon\.|amzn\./.test(host) ? "amazon" : store;
    var name = "Abrir na " + (STORE_NAMES[known] || "loja");
    link.title = name;
    link.setAttribute("aria-label", name);
    return link;
  }
  function reviewLine(book) {
    var parts = [];
    if (book.rating) parts.push("★ " + String(book.rating.toFixed(1)).replace(".", ","));
    if (book.reviews) parts.push(book.reviews.toLocaleString("pt-BR") + (book.reviews === 1 ? " avaliação" : " avaliações"));
    else if (book.sold) parts.push("+" + book.sold.toLocaleString("pt-BR") + " vendidos");
    if (!parts.length) return null;
    var line = document.createElement("span");
    line.className = "reviews";
    line.textContent = parts.join(" · ");
    return line;
  }
  function chip(text, kind) {
    var span = document.createElement("span");
    span.className = "chip" + (kind ? " " + kind : "");
    span.textContent = text;
    return span;
  }
  function escapeText(value) {
    return String(value || "").replace(/[&<>]/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char];
    });
  }
  function renderQueue() {
    var list = $("queue");
    list.textContent = "";
    var slots = plan.slots || [];
    var clocks = plan.clocks || [];
    var amazonCount = slots.filter(function (slot) { return slot.amazon; }).length;
    var mlCount = slots.filter(function (slot) { return slot.ml; }).length;
    var shopeeCount = slots.filter(function (slot) { return slot.shopee; }).length;
    var magaluCount = slots.filter(function (slot) { return slot.magalu; }).length;
    var secondCount = mlCount + shopeeCount + magaluCount;
    $("cap-az").style.width = (clocks.length ? Math.round(amazonCount / clocks.length * 100) : 0) + "%";
    $("cap-ml").style.width = (clocks.length ? Math.round(secondCount / clocks.length * 100) : 0) + "%";
    $("cap-az-label").textContent = "Amazon " + amazonCount + "/" + clocks.length;
    var parts = ["Mercado Livre " + mlCount];
    if (shopeeCount) parts.push("Shopee " + shopeeCount);
    if (magaluCount) parts.push("Magalu " + magaluCount);
    parts.push(secondCount + "/" + clocks.length);
    $("cap-ml-label").textContent = shopeeCount || magaluCount ? parts.join(" · ") : "Mercado Livre " + mlCount + "/" + clocks.length;
    var blocked = $("blocked");
    var nomes = (plan.bloqueados || []).map(function (item) { return item.title; });
    blocked.hidden = !nomes.length;
    blocked.textContent = nomes.length
      ? nomes.length + " marcados ficaram fora porque já saíram hoje: " + nomes.join(", ")
      : "";
    slots.forEach(function (slot, index) {
      var row = document.createElement("div");
      row.className = "slot-row";
      var warn = ((slot.amazon && slot.amazon.avisos) || []).concat((slot.ml && slot.ml.avisos) || []).concat((slot.shopee && slot.shopee.avisos) || []).concat((slot.magalu && slot.magalu.avisos) || []);
      if (warn.length) row.classList.add("warn");
      var clock = document.createElement("div");
      clock.className = "clock";
      clock.textContent = slot.clock;
      if (canArrange()) {
        var more = document.createElement("button");
        more.type = "button";
        more.className = "ghost row-menu";
        more.textContent = "⋯";
        more.setAttribute("aria-label", "Mover o post das " + slot.clock);
        more.addEventListener("click", function () { openDraftMenu(index); });
        clock.append(more);
      }
      row.append(clock, half(slot, "amazon", index), half(slot, "ml", index));
      list.append(row);
    });
    var note = $("draft-note");
    if (note) note.hidden = !plan.manual;
    paintPick();
    var sobras = $("sobras");
    var items = plan.amanha || [];
    sobras.hidden = !items.length;
    sobras.querySelector("summary").textContent = items.length + " não cabem hoje · vão para a reserva de amanhã";
    var ul = sobras.querySelector("ul");
    ul.textContent = "";
    items.forEach(function (item) {
      var li = document.createElement("li");
      var lojaLabel = item.store === "ml" ? "Mercado Livre" : item.store === "shopee" ? "Shopee" : item.store === "magalu" ? "Magazine Luiza" : "Amazon";
      li.textContent = lojaLabel + " · " + item.title + (item.discount ? " · −" + item.discount + "%" : "");
      ul.append(li);
    });
    renderBar();
  }
  function half(slot, side, index) {
    var item = slot[side];
    if (side === "ml" && !item) item = slot.shopee || slot.magalu || slot.extra || null;
    var cell = document.createElement("div");
    cell.className = "half " + side;
    cell.dataset.side = side;
    cell.dataset.index = String(index);
    if (canArrange()) {
      cell.addEventListener("click", function (event) {
        if (event.target.closest(".tools")) return;
        pickCell(side, index, item);
      });
    }
    if (!item) {
      cell.classList.add("empty");
      cell.textContent = side === "ml" ? "vazio · marque no Mercado Livre, na Shopee ou na Magazine Luiza" : "vazio · marque na Amazon";
      return cell;
    }
    var picture = imageOf(item);
    if (picture) {
      var img = document.createElement("img");
      img.alt = "";
      img.src = picture;
      img.addEventListener("error", function () { img.replaceWith(coverGap()); });
      cell.append(img);
    } else {
      cell.append(coverGap());
    }
    var text = document.createElement("div");
    var name = document.createElement("p");
    name.textContent = item.title;
    var price = document.createElement("span");
    price.innerHTML = escapeText(money(item.price_cents));
    if (item.discount) price.innerHTML += " <b>−" + item.discount + "%</b>";
    text.append(name, price);
    if (item.store === "shopee") text.append(chip("Shopee", ""));
    if (item.store === "magalu") text.append(chip("Magazine Luiza", ""));
    (item.avisos || []).forEach(function (aviso) { text.append(chip(aviso, "wait")); });
    cell.append(text);
    var tools = document.createElement("div");
    tools.className = "tools";
    if (canArrange()) {
      var size = columns()[side === "amazon" ? "amazon" : "segunda"].length;
      tools.append(move(side, index, -1, index > 0), move(side, index, 1, index < size - 1));
    }
    var link = storeLink(item.url, item.store);
    if (link) tools.append(link);
    // Shopee da fila importada pode não estar no catálogo; aí não há marcação para tirar.
    if (item.store !== "shopee" || bookById(item.asin)) tools.append(drop(item));
    if (tools.childNodes.length) cell.append(tools);
    return cell;
  }
  function canArrange() { return plan.origem !== "csv"; }
  function columns() {
    var amazon = [];
    var segunda = [];
    (plan.slots || []).forEach(function (slot) {
      if (slot.amazon) amazon.push(slot.amazon.id);
      var second = slot.ml || slot.shopee || slot.magalu;
      if (second) segunda.push(second.id);
    });
    // A reserva de amanhã fica depois, na ordem em que já estava.
    (plan.amanha || []).forEach(function (item) {
      if (item.store === "amazon") amazon.push(item.id); else segunda.push(item.id);
    });
    return { amazon: amazon, segunda: segunda };
  }
  function moveIn(list, from, to) {
    if (from >= list.length) return;
    var item = list.splice(from, 1)[0];
    list.splice(Math.min(Math.max(to, 0), list.length), 0, item);
  }
  function swapIn(list, a, b) {
    if (a >= list.length && b >= list.length) return;
    if (b >= list.length) { moveIn(list, a, list.length); return; }
    if (a >= list.length) { moveIn(list, b, list.length); return; }
    var keep = list[a];
    list[a] = list[b];
    list[b] = keep;
  }
  function saveOrder(next, message) {
    var before = columns();
    var body = new URLSearchParams();
    next.amazon.forEach(function (id) { body.append("amazon", id); });
    next.segunda.forEach(function (id) { body.append("segunda", id); });
    return post("/curadoria/fila/ordem", body.toString())
      .then(function (payload) {
        plan = payload;
        data.ordem = "mine";
        if ($("order")) $("order").value = "mine";
        renderQueue();
        renderCards();
        if (message) toast(message, function () { saveOrder(before, "A ordem anterior voltou."); });
      })
      .catch(function (error) { toast(error.message || "Não mudei a ordem."); });
  }
  var draftPick = null;
  function pickCell(side, index, item) {
    if (!draftPick) {
      if (!item) return;
      draftPick = { side: side, index: index, title: item.title };
      paintPick();
      return;
    }
    if (draftPick.side !== side) { toast("Troque livros da mesma loja: Amazon com Amazon, a outra loja com a outra."); return; }
    if (draftPick.index === index) { draftPick = null; paintPick(); return; }
    var from = draftPick;
    draftPick = null;
    var next = columns();
    swapIn(next[side === "amazon" ? "amazon" : "segunda"], from.index, index);
    var target = (plan.slots[index] || {}).clock || "";
    var origin = (plan.slots[from.index] || {}).clock || "";
    saveOrder(next, "“" + from.title.slice(0, 40) + "” foi para as " + target + (item ? " e trocou com o das " + origin + "." : "."));
  }
  function paintPick() {
    var bar = $("draft-pick");
    document.querySelectorAll("#queue .half").forEach(function (cell) {
      var picked = draftPick && cell.dataset.side === draftPick.side && Number(cell.dataset.index) === draftPick.index;
      cell.classList.toggle("is-picked", !!picked);
      cell.classList.toggle("is-target", !!draftPick && !picked && cell.dataset.side === draftPick.side);
    });
    if (!bar) return;
    bar.hidden = !draftPick;
    if (draftPick) $("draft-pick-text").textContent = "Toque no horário para onde vai “" + draftPick.title.slice(0, 40) + "”.";
  }
  function openDraftMenu(index) {
    var dialog = $("draft-menu");
    var slot = plan.slots[index];
    if (!dialog || !slot) return;
    dialog.dataset.index = String(index);
    $("draft-menu-title").textContent = "Post das " + slot.clock;
    var select = $("draft-target");
    select.textContent = "";
    plan.slots.forEach(function (other, otherIndex) {
      if (otherIndex === index) return;
      var option = document.createElement("option");
      option.value = String(otherIndex);
      var name = (other.amazon && other.amazon.title) || ((other.ml || other.shopee || other.magalu) || {}).title || "vazio";
      option.textContent = other.clock + " · " + name.slice(0, 40);
      select.append(option);
    });
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
  }
  function draftMenuAction(kind) {
    var dialog = $("draft-menu");
    var from = Number(dialog.dataset.index);
    var to = Number($("draft-target").value);
    dialog.close();
    if (isNaN(from) || isNaN(to)) return;
    var next = columns();
    ["amazon", "segunda"].forEach(function (key) {
      if (kind === "trocar") swapIn(next[key], from, to);
      else if (from < next[key].length) moveIn(next[key], from, to);
    });
    var target = plan.slots[to].clock;
    saveOrder(next, kind === "trocar"
      ? "Os posts das " + plan.slots[from].clock + " e das " + target + " trocaram de lugar."
      : "O post foi para as " + target + ". Os do meio andaram uma casa.");
  }
  if ($("draft-swap")) $("draft-swap").addEventListener("click", function () { draftMenuAction("trocar"); });
  if ($("draft-move")) $("draft-move").addEventListener("click", function () { draftMenuAction("mover"); });
  if ($("draft-close")) $("draft-close").addEventListener("click", function () { $("draft-menu").close(); });
  if ($("draft-pick-cancel")) $("draft-pick-cancel").addEventListener("click", function () { draftPick = null; paintPick(); });
  if ($("draft-reset")) $("draft-reset").addEventListener("click", function () {
    post("/curadoria/preferencia", "ordem=mine")
      .then(function (payload) { plan = payload; renderQueue(); renderCards(); toast("A fila voltou para a ordem das marcações."); })
      .catch(function () { toast("Não desfiz a arrumação."); });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && draftPick) { draftPick = null; paintPick(); }
  });
  function imageOf(item) {
    var source = bookById(item.asin);
    if (source && source.image) return source.image;
    if (plan.imagens && plan.imagens[item.asin]) return plan.imagens[item.asin];
    var livro = (plan.livros || []).filter(function (row) { return row.asin === item.asin; })[0];
    return livro && livro.image_url ? livro.image_url : "";
  }
  function coverGap() {
    var gap = document.createElement("span");
    gap.className = "cover-gap";
    gap.setAttribute("aria-hidden", "true");
    return gap;
  }
  function bookById(asin) {
    return allBooks().filter(function (book) { return book.asin === asin; })[0] || null;
  }
  function move(side, index, step, enabled) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = step < 0 ? "↑" : "↓";
    button.disabled = !enabled;
    var slot = plan.slots[index] || {};
    var item = side === "amazon" ? slot.amazon : (slot.ml || slot.shopee || slot.magalu || slot.extra);
    button.setAttribute("aria-label", (step < 0 ? "Subir " : "Descer ") + ((item && item.title) || ""));
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var next = columns();
      swapIn(next[side === "amazon" ? "amazon" : "segunda"], index, index + step);
      saveOrder(next, "");
    });
    return button;
  }
  function drop(item) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = "✕";
    button.setAttribute("aria-label", "Tirar " + item.title + " da fila");
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var book = bookById(item.asin);
      if (book) { book.picked = false; book.state = ""; }
      post("/curadoria/marcar", "asin=" + encodeURIComponent(item.asin) + "&loja=" + encodeURIComponent(item.store) + "&on=0")
        .then(function () { renderStores(); return loadPreview(); })
        .catch(function () { toast("Não tirei o livro."); });
    });
    return button;
  }
  function renderBar() {
    var slots = plan.slots || [];
    var both = slots.filter(function (slot) {
      return [slot.amazon, slot.ml, slot.shopee, slot.magalu, slot.extra].filter(Boolean).length > 1;
    }).length;
    $("summary").innerHTML =
      slots.length + " horários · " + both + " com as duas lojas · " +
      '<span class="warn">' + (plan.avisos || 0) + " avisos</span> · " +
      (plan.amanha || []).length + " para amanhã · " +
      '<span class="bad">' + (plan.bloqueados || []).length + " bloqueados</span>";
  }
  function resetFilters() {
    state.q = "";
    state.sort = "discount";
    state.min = 0;
    state.onlyPicked = false;
    state.onlyLow = false;
    state.hideKids = true;
    state.hideNotBook = true;
    state.hideSent = true;
    state.shown = 24;
    $("q").value = "";
    $("sort-by").value = "discount";
    document.querySelectorAll(".seg button").forEach(function (button) {
      button.setAttribute("aria-pressed", button.dataset.min === "0" ? "true" : "false");
    });
    ["only-picked", "only-low", "hide-kids", "hide-not-book", "hide-sent"].forEach(function (id) {
      setPressed(id, id !== "only-picked" && id !== "only-low");
    });
    renderCards();
  }
  function chooseStore(loja) {
    state.loja = loja;
    state.shown = 24;
    data.loja = loja;
    var url = new URL(window.location.href);
    url.searchParams.set("loja", LOJA_PARAM[loja] || "amazon");
    history.replaceState(null, "", url);
    renderStores();
    renderCards();
  }
  function showReview() {
    var dialog = $("review");
    $("review-title").textContent = "A fila de " + ((plan.slots[0] && plan.slots[0].clock) || "") + " a " + ((plan.slots.length && plan.slots[plan.slots.length - 1].clock) || "") + " vai ficar assim";
    $("review-numbers").textContent =
      (plan.entram || []).length + " entram · " + (plan.saem || []).length + " saem da fila atual · " +
      (plan.continuam || []).length + " continuam · " + (plan.amanha || []).length + " vão para amanhã";
    fillList($("review-in"), plan.entram || []);
    fillList($("review-out"), plan.saem || []);
    $("review-blocked").hidden = !(plan.bloqueados || []).length;
    $("review-blocked").textContent = (plan.bloqueados || []).length + " já saíram hoje e ficam de fora.";
    $("review-warn").textContent = (plan.avisos || 0) + " avisos de obra repetida.";
    $("review-apply").textContent = "Aplicar nos " + (plan.slots || []).length + " horários";
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }
  function openReview() {
    if (plan.origem === "csv") { showReview(); return; }
    loadPreview().then(showReview);
  }
  function fillList(list, rows) {
    list.textContent = "";
    rows.forEach(function (row) {
      var li = document.createElement("li");
      li.textContent = row.clock + " · " + row.title;
      list.append(li);
    });
    if (!rows.length) {
      var li = document.createElement("li");
      li.textContent = "Nenhum.";
      list.append(li);
    }
  }
  $("store-amazon").addEventListener("click", function () { chooseStore("amazon"); });
  $("store-ml").addEventListener("click", function () { chooseStore("ml"); });
  $("store-shopee").addEventListener("click", function () { chooseStore("shopee"); });
  $("store-magalu").addEventListener("click", function () { chooseStore("magalu"); });
  $("q").addEventListener("input", function () { state.q = $("q").value; state.shown = 24; renderCards(); });
  $("sort-by").addEventListener("change", function () { state.sort = $("sort-by").value; renderCards(); });
  document.querySelectorAll(".seg button").forEach(function (button) {
    button.addEventListener("click", function () {
      state.min = Number(button.dataset.min || 0);
      state.shown = 24;
      document.querySelectorAll(".seg button").forEach(function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      renderCards();
    });
  });
  function wireToggle(id, key) {
    $(id).addEventListener("click", function () {
      state[key] = $(id).getAttribute("aria-pressed") !== "true";
      setPressed(id, state[key]);
      state.shown = 24;
      renderCards();
    });
  }
  wireToggle("only-picked", "onlyPicked");
  wireToggle("only-low", "onlyLow");
  wireToggle("hide-kids", "hideKids");
  wireToggle("hide-not-book", "hideNotBook");
  wireToggle("hide-sent", "hideSent");
  $("more").addEventListener("click", function () { state.shown += 24; renderCards(); });
  $("order").addEventListener("change", function () {
    data.ordem = $("order").value;
    post("/curadoria/preferencia", "ordem=" + encodeURIComponent(data.ordem))
      .then(function (payload) { plan = payload; renderQueue(); renderCards(); })
      .catch(function () { toast("Não salvei a ordem."); });
  });
  $("clear-all").addEventListener("click", function () {
    post("/curadoria/desmarcar", "").then(function () {
      allBooks().forEach(function (book) {
        if (book.state !== "enviado") { book.picked = false; book.state = ""; }
      });
      toast("Marcações tiradas.", function () {
        post("/curadoria/desmarcar/desfazer", "").then(loadPreview);
      });
      loadPreview();
    }).catch(function () { toast("Não desmarquei."); });
  });
  $("fill").addEventListener("click", function () {
    post("/curadoria/preencher", "").then(function (payload) {
      plan = payload;
      (payload.added || []).forEach(function (item) {
        var book = bookById(item.asin);
        if (book) { book.picked = true; book.state = "marcado"; }
      });
      renderQueue();
      renderCards();
      renderStores();
      toast(payload.message || "Completei os horários vazios.", function () {
        post("/curadoria/preencher/desfazer", "").then(function () {
          (payload.added || []).forEach(function (item) {
            var book = bookById(item.asin);
            if (book) { book.picked = false; book.state = ""; }
          });
          loadPreview();
        });
      });
    }).catch(function (error) { toast(error.message || "Não preenchi."); });
  });
  $("review-open").addEventListener("click", openReview);
  $("review-back").addEventListener("click", function () { $("review").close(); });
  $("review-apply").addEventListener("click", function () {
    if (!plan.previa_id) { toast("Revise a fila de novo."); return; }
    var veioDoCsv = plan.origem === "csv";
    post("/curadoria/fila", "previa_id=" + encodeURIComponent(plan.previa_id) + "&resposta=json")
      .then(function (payload) {
        $("review").close();
        if (veioDoCsv) { window.location = "/hoje"; return; }
        toast(payload.message || "Fila aplicada.", function () {
          post("/curadoria/desfazer", "").then(function (done) { toast(done.message || "Fila anterior de volta."); loadPreview(); });
        });
        loadPreview();
      })
      .catch(function (error) { toast(error.message || "Não apliquei a fila."); });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && $("review").open) $("review").close();
  });
  var file = $("csv-file");
  if (file) {
    file.addEventListener("change", function () {
      var chosen = file.files && file.files[0];
      if (!chosen) return;
      chosen.text().then(function (text) {
        return fetch("/curadoria/csv", { method: "POST", headers: { "Content-Type": "text/csv; charset=utf-8" }, body: text });
      }).then(function (response) { return response.json(); }).then(function (payload) {
        if (payload.error) throw new Error(payload.error);
        window.location = "/curadoria?loja=" + encodeURIComponent(LOJA_PARAM[state.loja] || "amazon");
      }).catch(function () { toast("Não consegui ler esse arquivo."); });
    });
  }
  var filaParada = false;
  var filaJob = "";
  var filaFile = $("fila-csv");
  if (filaFile) {
    filaFile.addEventListener("change", function () {
      var chosen = filaFile.files && filaFile.files[0];
      filaFile.value = "";
      if (!chosen) return;
      abrirFila();
      chosen.text().then(function (text) {
        return fetch("/curadoria/fila/csv", { method: "POST", headers: { "Content-Type": "text/csv; charset=utf-8" }, body: text });
      }).then(function (response) { return response.json(); }).then(function (payload) {
        if (payload.error) throw new Error(payload.error);
        filaJob = payload.job || "";
        pintarFila(payload);
        return andarFila(filaJob);
      }).catch(function (error) { falhaFila(error.message || "Não consegui ler a fila."); });
    });
  }
  function abrirFila() {
    filaParada = false;
    $("fila-skip").textContent = "Lendo o arquivo…";
    $("fila-now").textContent = "Lendo o arquivo…";
    $("fila-steps").textContent = "";
    $("fila-run-error").hidden = true;
    $("fila-run-done").hidden = true;
    $("fila-quebrados").hidden = true;
    $("fila-run-resolve").hidden = true;
    $("fila-run-close").hidden = false;
    $("fila-run-close").textContent = "Fechar";
    $("fila-run-close").onclick = null;
    var dialog = $("fila-run");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }
  function pintarFila(payload) {
    var skip = $("fila-skip");
    var partes = [];
    if ((payload.avisos || []).length) partes.push(payload.avisos.join(" "));
    if ((payload.rejeitados || []).length) partes.push(payload.rejeitados.join(" "));
    if ((payload.pulados || []).length) partes.push("Deixados de fora: " + payload.pulados.join(" · "));
    if (payload.sem_foto) partes.push(payload.sem_foto + (payload.sem_foto === 1 ? " anúncio do Mercado Livre veio sem foto. Falta a coluna imagem_ml." : " anúncios do Mercado Livre vieram sem foto. Falta a coluna imagem_ml."));
    if (payload.livros) partes.unshift(payload.livros + (payload.livros === 1 ? " livro nesta importação." : " livros nesta importação."));
    skip.textContent = partes.join(" ");
    var list = $("fila-steps");
    list.textContent = "";
    var atual = "";
    (payload.passos || []).forEach(function (step) {
      var li = document.createElement("li");
      li.dataset.state = step.state || "wait";
      var mark = step.state === "ok" ? "✓ " : (step.state === "erro" || step.state === "pulado" ? "✗ " : (step.state === "run" ? "… " : ""));
      li.textContent = mark + step.label;
      list.append(li);
      if (step.state === "run" || step.state === "erro" || (!atual && step.state !== "ok")) atual = step.label;
    });
    pintarQuebrados(payload);
    $("fila-now").textContent = atual ? "Agora: " + atual : ($("fila-now").textContent || "");
    var current = list.querySelector('[data-state="run"], [data-state="erro"]');
    if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
  }
  function pintarQuebrados(payload) {
    var box = $("fila-quebrados");
    var lista = box.querySelector("ul");
    lista.textContent = "";
    (payload.quebrados || []).forEach(function (item) {
      var li = document.createElement("li");
      li.append(document.createTextNode((item.titulo || "Anúncio") + " — " + (item.motivo || "link quebrado")));
      if (item.url) {
        li.append(document.createTextNode(" "));
        var link = document.createElement("a");
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = item.url;
        li.append(link);
      }
      lista.append(li);
    });
    box.hidden = !(payload.quebrados || []).length;
    $("fila-run-resolve").hidden = !payload.aguardando;
  }
  function falhaFila(message) {
    filaParada = true;
    var box = $("fila-run-error");
    box.hidden = false;
    box.textContent = message;
    $("fila-now").textContent = "A importação parou.";
    $("fila-run-close").hidden = false;
    $("fila-run-close").textContent = "Fechar";
  }
  function andarFila(job) {
    if (filaParada) return;
    var list = $("fila-steps");
    var waiting = list.querySelector('[data-state="wait"]');
    if (waiting) {
      waiting.dataset.state = "run";
      waiting.textContent = "… " + waiting.textContent.replace(/^… /, "");
      $("fila-now").textContent = "Agora: " + waiting.textContent.replace(/^… /, "");
      if (waiting.scrollIntoView) waiting.scrollIntoView({ block: "nearest" });
    }
    return post("/curadoria/fila/csv/passo", "job=" + encodeURIComponent(job)).then(function (payload) {
      if (filaParada) return;
      pintarFila(payload);
      if (payload.falha) { falhaFila(payload.falha); return; }
      if (payload.aguardando) {
        $("fila-now").textContent = "A importação ficou com erro. A fila de hoje ainda não foi substituída.";
        $("fila-run-resolve").hidden = false;
        $("fila-run-close").hidden = false;
        return;
      }
      if (payload.done) {
        $("fila-now").textContent = (payload.quebrados || []).length
          ? "Fila substituída. O anúncio sem link de afiliado ficou de fora."
          : "Fila substituída.";
        $("fila-run-done").hidden = false;
        $("fila-run-done").textContent = payload.message || "A fila de hoje foi substituída.";
        $("fila-run-close").hidden = false;
        $("fila-run-close").textContent = "Ver a fila de hoje";
        $("fila-run-close").onclick = function () { window.location = "/hoje"; };
        return;
      }
      return andarFila(job);
    }).catch(function (error) { falhaFila(error.message || "A importação parou."); });
  }
  $("fila-run").addEventListener("cancel", function (event) {
    filaParada = true;
  });
  $("fila-run-resolve").addEventListener("click", function () {
    if (!filaJob || filaParada) return;
    $("fila-run-resolve").hidden = true;
    $("fila-now").textContent = "Resolvendo os links do Mercado Livre…";
    post("/curadoria/fila/csv/resolver", "job=" + encodeURIComponent(filaJob)).then(function (payload) {
      pintarFila(payload);
      if (payload.falha) { falhaFila(payload.falha); return; }
      if (payload.aguardando) {
        $("fila-now").textContent = "Ainda há links do Mercado Livre quebrados.";
        $("fila-run-resolve").hidden = false;
        return;
      }
      return andarFila(filaJob);
    }).catch(function (error) { falhaFila(error.message || "Não consegui resolver os links."); });
  });
  $("fila-run-close").addEventListener("click", function () {
    if ($("fila-run-close").textContent === "Ver a fila de hoje") return;
    filaParada = true;
    $("fila-run").close();
  });
  renderStores();
  renderCards();
  renderQueue();
})();
"""


def render_curation(
    books: list[CatalogBook],
    *,
    source: str,
    folder_file: str,
    notice: str | None,
    captured: str = "",
    clocks: list[str] | None = None,
    interval: int = 40,
    store: str = "amazon",
    peers: dict[str, str] | None = None,
    covers: dict[str, str] | None = None,
    marked: int | None = None,
    photos_ready: bool = False,
    amazon_marked: int | None = None,
    ml_marked: int | None = None,
    plan: list | dict | None = None,
    amazon_books: list[CatalogBook] | None = None,
    ml_books: list[CatalogBook] | None = None,
    agora: str = "",
    inicio: str = "",
    fim: str = "",
    ordem: str = "mine",
    amazon_file: str = "",
    ml_file: str = "",
    amazon_captured: str = "",
    ml_captured: str = "",
    extension_token: str = "",
    reviews: dict | None = None,
    ml_lows: dict | None = None,
    shopee_books: list[CatalogBook] | None = None,
    shopee_file: str = "",
    shopee_captured: str = "",
    magalu_books: list[CatalogBook] | None = None,
    magalu_file: str = "",
    magalu_captured: str = "",
) -> str:
    del marked, amazon_marked, ml_marked
    loja = store if store in {"ml", "shopee", "magalu"} else "amazon"
    amazon = amazon_books if amazon_books is not None else (books if loja == "amazon" else [])
    mercado = ml_books if ml_books is not None else (books if loja == "ml" else [])
    shopee = shopee_books if shopee_books is not None else (books if loja == "shopee" else [])
    magalu = magalu_books if magalu_books is not None else (books if loja == "magalu" else [])
    photos = covers or {}

    def second(book: CatalogBook, kind: str) -> dict:
        public = _public(book, kind, photos, photos_ready, (peers or {}).get(book.asin, ""))
        return _with_low(_with_reviews(public, (reviews or {}).get((kind, book.asin))), (ml_lows or {}).get(book.asin))

    payload = {
        "loja": loja,
        "ordem": ordem if ordem in {"mine", "desc", "mix"} else "mine",
        "agora": agora,
        "plan": plan if isinstance(plan, dict) else {"slots": [], "bloqueados": [], "amanha": [], "clocks": clocks or [], "avisos": 0},
        "enviados": {
            item["id"]: item.get("clocks") or []
            for item in ((plan or {}).get("bloqueados") if isinstance(plan, dict) else []) or []
        },
        "amazon": [
            _with_reviews(_public(book, "amazon", photos, photos_ready, (peers or {}).get(book.asin, "")), (reviews or {}).get(("amazon", book.asin)))
            for book in amazon
        ],
        "ml": [second(book, "ml") for book in mercado],
        "shopee": [second(book, "shopee") for book in shopee],
        "magalu": [second(book, "magalu") for book in magalu],
    }
    raw = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    grade = clocks or (payload["plan"].get("clocks") if isinstance(payload["plan"], dict) else []) or []
    if grade:
        faixa = f"{grade[0]} a {grade[-1]}"
    else:
        faixa = "nenhum horário livre"
    agora_label = agora or "agora"
    note = f'<p class="alert" role="status">{escape(notice)}</p>' if notice else ""
    photo = ""
    if not photos_ready:
        photo = (
            '<p class="muted">A foto do anúncio do Mercado Livre entra depois que os cookies '
            "estão em Configurações.</p>"
        )
    folder = f'<p class="muted">Na pasta: {escape(folder_file)}</p>' if folder_file else ""
    amazon_cap = amazon_captured or (captured if loja == "amazon" else "")
    ml_cap = ml_captured or (captured if loja == "ml" else "")
    shopee_cap = shopee_captured or (captured if loja == "shopee" else "")
    magalu_cap = magalu_captured or (captured if loja == "magalu" else "")
    body = f"""
    <header class="curation-head">
      <div>
        <h1>Montar a fila de hoje</h1>
        <p class="context">Agora {escape(agora_label)} · {len(grade)} horários livres de {escape(faixa)} · a cada {int(interval)} min · <a href="/hoje#regras">Mudar em Regras</a></p>
      </div>
      <div class="import-menus">
      <details class="import-menu">
        <summary>Importar fila</summary>
        <p class="muted">Substitui a fila de hoje. Horário que já passou fica de fora. Cada linha é um post com no máximo duas ofertas, e a segunda pode ser da mesma loja. Shopee entra por asin_shopee e link_shopee. A oferta extra, se houver, entra por asin_2, titulo_2, preco_2 e link_2.</p>
        <label class="muted">Arquivo CSV
          <input id="fila-csv" type="file" accept=".csv,text/csv">
        </label>
      </details>
      <details class="import-menu">
        <summary>Importar CSVs da pasta</summary>
        <form method="post" action="/curadoria/pasta">
          <button type="submit">Trazer os arquivos da pasta</button>
        </form>
        <label class="muted">Ou carregar do computador
          <input id="csv-file" type="file" accept=".csv,text/csv">
        </label>
        {folder}
        <p class="muted">{escape(source) if source else "Nenhum arquivo importado."}</p>
        <p class="muted">Token da extensão</p>
        <p class="token"><code>{escape(extension_token)}</code></p>
      </details>
      </div>
    </header>
    {note}
    {photo}
    <div class="store-switch" role="group" aria-label="Loja">
      <button type="button" id="store-amazon" class="store-amazon" aria-pressed="{str(loja == 'amazon').lower()}">
        <strong>Amazon</strong>
        <span><b></b></span>
        <span class="captured">Capturado em {escape(amazon_cap or "—")}</span>
        <span class="file">{escape(amazon_file)}</span>
      </button>
      <button type="button" id="store-ml" class="store-ml" aria-pressed="{str(loja == 'ml').lower()}">
        <strong>Mercado Livre</strong>
        <span><b></b></span>
        <span class="captured">Capturado em {escape(ml_cap or "—")}</span>
        <span class="file">{escape(ml_file)}</span>
      </button>
      <button type="button" id="store-shopee" class="store-shopee" aria-pressed="{str(loja == 'shopee').lower()}">
        <strong>Shopee</strong>
        <span><b></b></span>
        <span class="captured">Capturado em {escape(shopee_cap or "—")}</span>
        <span class="file">{escape(shopee_file)}</span>
      </button>
      <button type="button" id="store-magalu" class="store-magalu" aria-pressed="{str(loja == 'magalu').lower()}">
        <strong>Magazine Luiza</strong>
        <span><b></b></span>
        <span class="captured">Capturado em {escape(magalu_cap or "—")}</span>
        <span class="file">{escape(magalu_file)}</span>
      </button>
    </div>
    <div class="curation-layout">
      <section>
        <div class="filters">
          <div class="filters-row">
            <label class="search">Buscar
              <input id="q" type="search" placeholder="Título, autor ou categoria">
            </label>
            <label>Ordenar
              <select id="sort-by">
                <option value="discount">Maior desconto</option>
                <option value="price-asc">Menor preço</option>
                <option value="price-desc">Maior preço</option>
                <option value="title">A–Z</option>
                <option value="reviews">Mais avaliações</option>
              </select>
            </label>
            <div class="seg" role="group" aria-label="Desconto mínimo">
              <button type="button" data-min="0" aria-pressed="true">Todos</button>
              <button type="button" data-min="40" aria-pressed="false">40%+</button>
              <button type="button" data-min="50" aria-pressed="false">50%+</button>
              <button type="button" data-min="70" aria-pressed="false">70%+</button>
            </div>
          </div>
          <div class="pills">
            <button type="button" id="only-picked" aria-pressed="false">Só marcados</button>
            <button type="button" id="only-low" aria-pressed="false">Menor preço 365d</button>
            <button type="button" id="hide-kids" aria-pressed="true">Ocultar infantis</button>
            <button type="button" id="hide-not-book" aria-pressed="true">Ocultar não-livros</button>
            <button type="button" id="hide-sent" aria-pressed="true">Ocultar já enviados</button>
            <span id="shown" aria-live="polite"></span>
          </div>
        </div>
        <div class="books" id="catalog"></div>
        <button type="button" id="more" class="ghost" hidden>Mostrar mais</button>
      </section>
      <aside class="queue-col" aria-label="Fila de hoje">
        <h2>Fila de hoje</h2>
        <div class="caps">
          <span id="cap-az-label">Amazon</span>
          <div class="cap az"><i id="cap-az"></i></div>
          <span id="cap-ml-label">Mercado Livre</span>
          <div class="cap"><i id="cap-ml"></i></div>
        </div>
        <label>Ordem da fila
          <select id="order">
            <option value="mine" {"selected" if ordem == "mine" else ""}>Minha ordem</option>
            <option value="desc" {"selected" if ordem == "desc" else ""}>Maior desconto</option>
            <option value="mix" {"selected" if ordem == "mix" else ""}>Intercalar</option>
          </select>
        </label>
        <button type="button" id="clear-all" class="ghost">Desmarcar tudo</button>
        <p id="blocked" class="blocked" hidden></p>
        <p id="draft-note" class="draft-note" hidden>
          Você arrumou esta fila à mão. Livro marcado agora entra no fim.
          <button type="button" class="ghost" id="draft-reset">Voltar à ordem das marcações</button>
        </p>
        <p class="draft-hint">Toque num livro e depois em outro horário para trocar os dois. O ⋯ move o post inteiro.</p>
        <div id="draft-pick" class="draft-pick" role="status" hidden>
          <span id="draft-pick-text"></span>
          <button type="button" class="ghost" id="draft-pick-cancel">Cancelar</button>
        </div>
        <div id="queue"></div>
        <details id="sobras">
          <summary>0 não cabem hoje · vão para a reserva de amanhã</summary>
          <ul></ul>
        </details>
      </aside>
    </div>
    <div class="action-bar">
      <p id="summary"></p>
      <div>
        <button type="button" id="fill" class="ghost">Preencher sozinho</button>
        <button type="button" id="review-open">Revisar e aplicar</button>
      </div>
    </div>
    <dialog id="draft-menu" aria-labelledby="draft-menu-title">
      <h2 id="draft-menu-title">Post</h2>
      <label>Com o horário <select id="draft-target"></select></label>
      <div class="draft-actions">
        <button type="button" id="draft-swap">Trocar os dois posts</button>
        <button type="button" class="ghost" id="draft-move">Mover para lá (os do meio andam uma casa)</button>
        <button type="button" class="ghost" id="draft-close">Fechar</button>
      </div>
    </dialog>
    <dialog id="review" aria-labelledby="review-title">
      <h2 id="review-title">A fila vai ficar assim</h2>
      <p id="review-numbers"></p>
      <p id="review-blocked" class="blocked" hidden></p>
      <div class="cols">
        <section><h3>Entram</h3><ul id="review-in"></ul></section>
        <section><h3>Saem da fila atual</h3><ul id="review-out"></ul></section>
      </div>
      <p id="review-warn"></p>
      <button type="button" id="review-back" class="ghost">Voltar e ajustar</button>
      <button type="button" id="review-apply">Aplicar nos horários</button>
    </dialog>
    <dialog id="fila-run" aria-labelledby="fila-run-title">
      <h2 id="fila-run-title">Importando a fila</h2>
      <p id="fila-now">Lendo o arquivo…</p>
      <p id="fila-skip" class="muted"></p>
      <ol id="fila-steps"></ol>
      <div id="fila-quebrados" hidden>
        <p class="blocked">Links do Mercado Livre que ficaram de fora</p>
        <ul></ul>
        <p class="muted">Esse anúncio não entra no horário. O resto da fila segue. Se a sessão expirou, atualize os cookies e importe de novo.</p>
        <a href="/configuracoes" target="_blank">Abrir configurações</a>
      </div>
      <p id="fila-run-error" class="blocked" hidden></p>
      <p id="fila-run-done" hidden></p>
      <button type="button" id="fila-run-resolve" hidden>Resolver</button>
      <button type="button" id="fila-run-close" class="ghost" hidden>Fechar</button>
    </dialog>
    <script type="application/json" id="curation-data">{raw}</script>
    """
    return _page("Curadoria", f"<main>{body}</main>", nav=True, body_class="wide", extra_style=_STYLE, extra_script=_SCRIPT)


def _public(book: CatalogBook, store: str, covers: dict[str, str], photos_ready: bool, peer: str = "") -> dict:
    remote = covers.get(book.asin, "")
    if store in {"ml", "shopee", "magalu"} and book.image_url:
        image = book.image_url
    elif store == "shopee":
        image = ""
    elif remote:
        image = remote
    elif store == "ml" and not photos_ready:
        image = ""
    else:
        image = f"/curadoria/capa/{book.asin}.jpg"
    return {
        "asin": book.asin,
        "title": book.title,
        "author": book.author,
        "category": book.category,
        "price_cents": book.price_cents,
        "price": format_brl(book.price_cents) if book.price_cents else "",
        "discount": discount_percent(book),
        "savings": _savings_cents(book),
        "low": book.low_365,
        "kids": book.kids,
        "notBook": book.not_book,
        "picked": book.picked and book.pick_state != "enviado",
        "state": book.pick_state,
        "position": book.position,
        "image": image,
        "url": book.url,
        "peer": peer,
    }


def _with_low(public: dict, found) -> dict:
    if found is None:
        return public
    return {**public, "historyDays": found.days, "lowDays": found.days if found.lowest else 0}


def _with_reviews(public: dict, found) -> dict:
    if found is None:
        return public
    return {**public, "reviews": found.count, "rating": found.rating, "sold": found.sold}


def discount_percent(book: CatalogBook) -> int:
    if book.price_cents is None or not book.list_cents or book.list_cents <= book.price_cents:
        return 0
    return round((book.list_cents - book.price_cents) * 100 / book.list_cents)


def _savings_cents(book: CatalogBook) -> int:
    if book.price_cents is None or not book.list_cents or book.list_cents <= book.price_cents:
        return 0
    return book.list_cents - book.price_cents
