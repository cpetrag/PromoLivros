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
.store-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 0.7rem; margin: 0.8rem 0; }
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
.half p { margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 0.82rem; }
.half.empty { display: grid; place-items: center; border: 1px dashed var(--line); color: var(--muted); font-size: 0.8rem; background: transparent; }
.half .tools { grid-column: 1 / -1; display: flex; gap: 0.2rem; }
.blocked { background: color-mix(in srgb, var(--red) 12%, var(--surface)); color: var(--red); border-radius: 12px; padding: 0.5rem 0.7rem; }
.action-bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 6; display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; justify-content: space-between; padding: 0.7rem 1rem; background: var(--surface); border-top: 1px solid var(--line); }
.action-bar .warn { color: var(--amber); }
.action-bar .bad { color: var(--red); }
dialog { border: 0; border-radius: 16px; background: var(--surface); color: var(--ink); width: min(40rem, calc(100% - 1.5rem)); }
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
  function books() { return state.loja === "ml" ? data.ml : data.amazon; }
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
      if (state.onlyLow && !book.low) return false;
      if (state.min && (book.discount || 0) < state.min) return false;
      if (!query) return true;
      return (book.title + " " + book.author + " " + book.category).toLowerCase().indexOf(query) >= 0;
    }).sort(function (a, b) {
      if (state.sort === "price-asc") return (a.price_cents || 1e12) - (b.price_cents || 1e12);
      if (state.sort === "price-desc") return (b.price_cents || 0) - (a.price_cents || 0);
      if (state.sort === "title") return a.title.localeCompare(b.title, "pt");
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
    ["amazon", "ml"].forEach(function (loja) {
      var button = $(loja === "amazon" ? "store-amazon" : "store-ml");
      var list = loja === "amazon" ? data.amazon : data.ml;
      var marked = list.filter(function (book) {
        return book.picked || book.state === "marcado" || book.state === "na_fila" || book.state === "reserva";
      }).length;
      button.setAttribute("aria-pressed", state.loja === loja ? "true" : "false");
      button.querySelector("b").textContent = list.length + " no CSV · " + marked + " marcados";
    });
    var low = $("only-low");
    if (low) {
      low.disabled = state.loja === "ml";
      low.title = state.loja === "ml" ? "O CSV do Mercado Livre não traz histórico." : "";
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
    var chips = document.createElement("span");
    chips.className = "chips";
    if (place && place.kind === "fila") chips.append(chip(place.clock, "go"));
    if ((place && place.kind === "amanha") || book.state === "reserva") chips.append(chip("não cabe · amanhã", "wait"));
    if (sent.length) chips.append(chip("saiu " + sent.join(" e "), "hot"));
    if (book.low) chips.append(chip("menor 365d", "go"));
    if (state.loja === "ml" && !book.low) chips.append(chip("sem histórico", ""));
    if (book.kids) chips.append(chip("infantil", ""));
    if (book.notBook) chips.append(chip("não é livro", ""));
    var mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = button.classList.contains("on") && data.ordem === "mine" ? "✓" : (marked ? "✓" : "");
    button.append(img, title, category, price, chips, mark);
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
      post("/curadoria/marcar", "asin=" + encodeURIComponent(book.asin) + "&loja=" + encodeURIComponent(state.loja === "ml" ? "ml" : "amazon") + "&on=" + (next ? "1" : "0"))
        .then(function () { schedulePreview(); renderStores(); })
        .catch(function (error) { toast(error.message || "Não salvei a marcação."); });
    });
    return button;
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
    $("cap-az").style.width = (clocks.length ? Math.round(amazonCount / clocks.length * 100) : 0) + "%";
    $("cap-ml").style.width = (clocks.length ? Math.round(mlCount / clocks.length * 100) : 0) + "%";
    $("cap-az-label").textContent = "Amazon " + amazonCount + "/" + clocks.length;
    $("cap-ml-label").textContent = "Mercado Livre " + mlCount + "/" + clocks.length;
    var blocked = $("blocked");
    var nomes = (plan.bloqueados || []).map(function (item) { return item.title; });
    blocked.hidden = !nomes.length;
    blocked.textContent = nomes.length
      ? nomes.length + " marcados ficaram fora porque já saíram hoje: " + nomes.join(", ")
      : "";
    slots.forEach(function (slot, index) {
      var row = document.createElement("div");
      row.className = "slot-row";
      var warn = ((slot.amazon && slot.amazon.avisos) || []).concat((slot.ml && slot.ml.avisos) || []);
      if (warn.length) row.classList.add("warn");
      var clock = document.createElement("div");
      clock.className = "clock";
      clock.textContent = slot.clock;
      row.append(clock, half(slot, "amazon", index), half(slot, "ml", index));
      list.append(row);
    });
    var sobras = $("sobras");
    var items = plan.amanha || [];
    sobras.hidden = !items.length;
    sobras.querySelector("summary").textContent = items.length + " não cabem hoje · vão para a reserva de amanhã";
    var ul = sobras.querySelector("ul");
    ul.textContent = "";
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.textContent = (item.store === "ml" ? "Mercado Livre" : "Amazon") + " · " + item.title + (item.discount ? " · −" + item.discount + "%" : "");
      ul.append(li);
    });
    renderBar();
  }
  function half(slot, side, index) {
    var item = slot[side];
    var cell = document.createElement("div");
    cell.className = "half " + side;
    if (!item) {
      cell.classList.add("empty");
      cell.textContent = side === "ml" ? "vazio · marque no Mercado Livre" : "vazio · marque na Amazon";
      return cell;
    }
    if (item.image || true) {
      var img = document.createElement("img");
      img.alt = "";
      var source = bookById(item.asin);
      img.src = source && source.image ? source.image : "";
      cell.append(img);
    }
    var text = document.createElement("div");
    var name = document.createElement("p");
    name.textContent = item.title;
    var price = document.createElement("span");
    price.innerHTML = escapeText(money(item.price_cents));
    if (item.discount) price.innerHTML += " <b>−" + item.discount + "%</b>";
    text.append(name, price);
    (item.avisos || []).forEach(function (aviso) { text.append(chip(aviso, "wait")); });
    cell.append(text);
    if (data.ordem === "mine" || true) {
      var tools = document.createElement("div");
      tools.className = "tools";
      if (data.ordem === "mine") {
        tools.append(move(item, -1, index > 0), move(item, 1, true));
      }
      tools.append(drop(item));
      cell.append(tools);
    }
    return cell;
  }
  function bookById(asin) {
    return data.amazon.concat(data.ml).filter(function (book) { return book.asin === asin; })[0] || null;
  }
  function move(item, step, enabled) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = step < 0 ? "↑" : "↓";
    button.disabled = !enabled;
    button.setAttribute("aria-label", (step < 0 ? "Subir " : "Descer ") + item.title);
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      post("/curadoria/ordem", "asin=" + encodeURIComponent(item.asin) + "&loja=" + encodeURIComponent(item.store) + "&passo=" + step)
        .then(loadPreview)
        .catch(function () { toast("Não troquei a ordem."); });
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
    var both = slots.filter(function (slot) { return slot.amazon && slot.ml; }).length;
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
    url.searchParams.set("loja", loja === "ml" ? "mercadolivre" : "amazon");
    history.replaceState(null, "", url);
    renderStores();
    renderCards();
  }
  function openReview() {
    loadPreview().then(function () {
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
    });
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
      data.amazon.concat(data.ml).forEach(function (book) {
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
    post("/curadoria/fila", "previa_id=" + encodeURIComponent(plan.previa_id) + "&resposta=json")
      .then(function (payload) {
        $("review").close();
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
        window.location = "/curadoria?loja=" + encodeURIComponent(state.loja === "ml" ? "mercadolivre" : "amazon");
      }).catch(function () { toast("Não consegui ler esse arquivo."); });
    });
  }
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
) -> str:
    del marked, amazon_marked, ml_marked
    loja = "ml" if store == "ml" else "amazon"
    amazon = amazon_books if amazon_books is not None else (books if loja == "amazon" else [])
    mercado = ml_books if ml_books is not None else (books if loja == "ml" else [])
    photos = covers or {}
    payload = {
        "loja": loja,
        "ordem": ordem if ordem in {"mine", "desc", "mix"} else "mine",
        "agora": agora,
        "plan": plan if isinstance(plan, dict) else {"slots": [], "bloqueados": [], "amanha": [], "clocks": clocks or [], "avisos": 0},
        "enviados": {
            item["id"]: item.get("clocks") or []
            for item in ((plan or {}).get("bloqueados") if isinstance(plan, dict) else []) or []
        },
        "amazon": [_public(book, "amazon", photos, photos_ready, (peers or {}).get(book.asin, "")) for book in amazon],
        "ml": [_public(book, "ml", photos, photos_ready, (peers or {}).get(book.asin, "")) for book in mercado],
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
    body = f"""
    <header class="curation-head">
      <div>
        <h1>Montar a fila de hoje</h1>
        <p class="context">Agora {escape(agora_label)} · {len(grade)} horários livres de {escape(faixa)} · a cada {int(interval)} min · <a href="/hoje#regras">Mudar em Regras</a></p>
      </div>
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
      </details>
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
    <div id="toast" role="status" hidden></div>
    <script type="application/json" id="curation-data">{raw}</script>
    """
    return _page("Curadoria", f"<main>{body}</main>", nav=True, body_class="wide", extra_style=_STYLE, extra_script=_SCRIPT)


def _public(book: CatalogBook, store: str, covers: dict[str, str], photos_ready: bool, peer: str = "") -> dict:
    remote = covers.get(book.asin, "")
    if store == "ml" and book.image_url:
        image = book.image_url
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


def discount_percent(book: CatalogBook) -> int:
    if book.price_cents is None or not book.list_cents or book.list_cents <= book.price_cents:
        return 0
    return round((book.list_cents - book.price_cents) * 100 / book.list_cents)


def _savings_cents(book: CatalogBook) -> int:
    if book.price_cents is None or not book.list_cents or book.list_cents <= book.price_cents:
        return 0
    return book.list_cents - book.price_cents
