"""Página em que a fila do dia é a marcação do CSV."""
from __future__ import annotations

import json
from html import escape

from promo_livros.catalog import CatalogBook, cover_url
from promo_livros.dashboard_pages import _page
from promo_livros.formatter import format_brl

_STYLE = """
body.wide > main { width: min(72rem, calc(100% - 2rem)); }
.curation-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem;
  align-items: center;
  position: sticky;
  top: 0;
  z-index: 2;
  background: color-mix(in srgb, var(--bg) 92%, transparent);
  padding: 0.7rem 0;
}
.curation-bar .count { font-weight: 700; }
.books {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
  gap: 0.7rem;
  margin: 0.4rem 0 2rem;
}
.book {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
}
.book label {
  display: grid;
  grid-template-columns: auto 4.5rem 1fr;
  gap: 0.7rem;
  align-items: center;
  padding: 0.7rem;
  cursor: pointer;
}
.book img {
  width: 4.5rem;
  height: 6.6rem;
  object-fit: cover;
  background: var(--line);
  border-radius: 6px;
}
.book strong { display: block; font-size: 0.95rem; }
.book em { display: block; color: var(--muted); font-style: normal; font-size: 0.85rem; margin-top: 0.2rem; }
.book .badge {
  display: inline-block;
  margin-top: 0.35rem;
  background: var(--chip-green);
  color: var(--chip-green-ink);
  border-radius: 999px;
  padding: 0.1rem 0.45rem;
  font-size: 0.75rem;
  font-weight: 700;
}
.book .price { display: block; margin-top: 0.35rem; font-weight: 700; }
.book .price b { color: var(--chip-green-ink); }
.book .when { display: block; min-height: 1.15em; margin-top: 0.2rem; color: var(--blue); font-weight: 700; font-size: 0.85rem; }
.captured { font-weight: 700; color: var(--blue); }
.views { display: flex; gap: 0.3rem; }
.views button[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }
.store-tabs { display: flex; gap: 0.3rem; }
.store-tabs a {
  display: inline-block;
  padding: 0.35rem 0.7rem;
  border-radius: 999px;
  text-decoration: none;
  color: inherit;
}
.store-tabs a[aria-current="page"] { background: var(--accent); color: var(--accent-ink); }
.store-tabs span { font-weight: 700; }
.plan {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.85rem 1rem;
  margin: 0.2rem 0 0.8rem;
}
.plan h2 { margin: 0; font-size: 1rem; }
.plan p { margin: 0.35rem 0 0.5rem; }
.plan-head, .plan-row {
  display: grid;
  grid-template-columns: 4rem minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.5rem;
  align-items: center;
}
.plan-head {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
  padding-bottom: 0.3rem;
}
.plan-list { list-style: none; margin: 0; padding: 0; max-height: 22rem; overflow: auto; }
.plan-row { border-top: 1px solid var(--line); padding: 0.4rem 0; }
.plan-row .clock { font-weight: 700; color: var(--blue); }
.plan-row .clock.late { color: var(--muted); font-weight: 500; font-size: 0.8rem; }
.slot {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
  background: var(--bg);
  border-radius: 10px;
  padding: 0.3rem 0.4rem;
}
.slot.empty {
  background: transparent;
  border: 1px dashed var(--line);
  color: var(--muted);
  font-size: 0.8rem;
  justify-content: center;
}
.slot .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.slot .cash { font-weight: 700; color: var(--chip-green-ink); white-space: nowrap; }
.slot .tools { margin-left: auto; display: flex; gap: 0.1rem; }
.slot .tools button { padding: 0.1rem 0.4rem; border-radius: 8px; font-size: 0.8rem; line-height: 1.3; }
.book .peer { display: inline-block; margin-top: 0.35rem; color: var(--blue); font-size: 0.75rem; font-weight: 700; }
.book .product { display: inline-block; margin: 0.35rem 0 0 1.8rem; font-size: 0.8rem; font-weight: 700; }
.books.as-list .product { margin-left: 0.6rem; }
.books.as-list { grid-template-columns: 1fr; }
.books.as-list .book label { grid-template-columns: auto 3.2rem minmax(0, 1fr); }
.books.as-list .book img { width: 3.2rem; height: 4.6rem; }
.books.as-list strong, .books.as-list em, .books.as-list .price, .books.as-list .when { display: inline; }
.books.as-list em::before { content: " · "; }
.books.as-list .price { margin-left: 0.8rem; }
.books.as-list .when { margin-left: 0.6rem; }
#interval { width: 4.5rem; }
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.6rem 1rem;
  align-items: end;
  margin: 0.2rem 0 0.4rem;
}
.filters label { display: grid; gap: 0.2rem; font-size: 0.85rem; color: var(--muted); }
.filters label.inline { display: flex; align-items: center; gap: 0.35rem; color: inherit; }
.filters select, .filters input[type="number"] { min-width: 7rem; }
#max-price { width: 6.5rem; }
#shown { color: var(--muted); font-size: 0.85rem; }
"""

_SCRIPT = """
(function () {
  var only = document.getElementById("only-low");
  var query = document.getElementById("q");
  var count = document.getElementById("count");
  var sortBy = document.getElementById("sort-by");
  var minDiscount = document.getElementById("min-discount");
  var maxPrice = document.getElementById("max-price");
  var category = document.getElementById("category");
  var onlyPicked = document.getElementById("only-picked");
  var hideKids = document.getElementById("hide-kids");
  var shown = document.getElementById("shown");
  var clocks = [];
  try {
    clocks = JSON.parse(document.getElementById("curation-clocks").textContent || "[]");
  } catch (e) {}
  function cards() {
    return Array.prototype.slice.call(document.querySelectorAll(".book"));
  }
  function num(card, name) {
    var raw = card.getAttribute(name);
    return raw === null || raw === "" ? null : Number(raw);
  }
  var plan = [];
  try {
    plan = JSON.parse(document.getElementById("curation-plan").textContent || "[]");
    if (!Array.isArray(plan)) plan = [];
  } catch (e) { plan = []; }
  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body: body
    }).then(function (response) { return response.json(); }).then(function (data) {
      if (data.error) throw new Error(data.error);
      if (Array.isArray(data.plan)) plan = data.plan;
      if (Array.isArray(data.clocks)) clocks = data.clocks;
      if (count && typeof data.picked === "number") count.textContent = String(data.picked);
      paintTimes();
      return data;
    });
  }
  function slotNode(slot, store, place, total) {
    var cell = document.createElement("div");
    cell.className = "slot";
    if (!slot) {
      cell.className = "slot empty";
      cell.textContent = store === "ml" ? "sem oferta do Mercado Livre" : "sem oferta da Amazon";
      return cell;
    }
    var name = document.createElement("span");
    name.className = "name";
    name.textContent = slot.title;
    var cash = document.createElement("span");
    cash.className = "cash";
    cash.textContent = slot.price;
    var tools = document.createElement("span");
    tools.className = "tools";
    tools.append(
      moveButton(slot, -1, "Subir", place > 0),
      moveButton(slot, 1, "Descer", place < total - 1),
      dropButton(slot)
    );
    cell.append(name, cash, tools);
    return cell;
  }
  function moveButton(slot, way, label, enabled) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = way < 0 ? "↑" : "↓";
    button.disabled = !enabled;
    button.setAttribute("aria-label", label + " " + slot.title);
    button.addEventListener("click", function () {
      post("/curadoria/ordem", "asin=" + encodeURIComponent(slot.asin) +
        "&loja=" + encodeURIComponent(slot.store) + "&passo=" + way).catch(function () {});
    });
    return button;
  }
  function dropButton(slot) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "ghost";
    button.textContent = "✕";
    button.setAttribute("aria-label", "Tirar " + slot.title + " da fila");
    button.addEventListener("click", function () { dropPick(slot); });
    return button;
  }
  function dropPick(slot) {
    var box = null;
    cards().some(function (card) {
      var found = card.querySelector(".pick");
      if (found && found.value === slot.asin) box = found;
      return box;
    });
    if (box && box.checked) {
      box.checked = false;
      box.dispatchEvent(new Event("change"));
      return;
    }
    post("/curadoria/marcar", "asin=" + encodeURIComponent(slot.asin) +
      "&loja=" + encodeURIComponent(slot.store) + "&on=0").catch(function () {});
  }
  function paintPlan() {
    var list = document.getElementById("queue-list");
    var note = document.getElementById("queue-note");
    var mix = document.getElementById("mix");
    var amazonCount = plan.filter(function (row) { return row.amazon; }).length;
    var mlCount = plan.filter(function (row) { return row.ml; }).length;
    var both = plan.filter(function (row) { return row.amazon && row.ml; }).length;
    var amazonTab = document.getElementById("count-amazon");
    var mlTab = document.getElementById("count-ml");
    if (amazonTab) amazonTab.textContent = String(amazonCount);
    if (mlTab) mlTab.textContent = String(mlCount);
    if (mix) mix.textContent = plan.length + (plan.length === 1 ? " post" : " posts");
    if (note) {
      if (!plan.length) {
        note.textContent = "Marque um livro na Amazon e um no Mercado Livre. Os dois saem juntos no mesmo post.";
      } else if (both === plan.length) {
        note.textContent = "Todos os posts levam as duas lojas.";
      } else {
        note.textContent = both + " de " + plan.length + " posts levam as duas lojas. Os outros saem com uma só. As setas trocam quem fica com quem.";
      }
    }
    if (!list) return;
    list.replaceChildren();
    plan.forEach(function (row, index) {
      var item = document.createElement("li");
      item.className = "plan-row";
      var time = document.createElement("span");
      time.className = row.clock ? "clock" : "clock late";
      time.textContent = row.clock || "não cabe";
      item.append(
        time,
        slotNode(row.amazon, "amazon", index, amazonCount),
        slotNode(row.ml, "ml", index, mlCount)
      );
      list.appendChild(item);
    });
  }
  function paintTimes() {
    var place = {};
    plan.forEach(function (row) {
      ["amazon", "ml"].forEach(function (store) {
        if (!row[store]) return;
        var mate = row[store === "amazon" ? "ml" : "amazon"];
        place[row[store].asin] = { clock: row.clock, mate: mate ? mate.title : "" };
      });
    });
    cards().forEach(function (card) {
      var when = card.querySelector(".when");
      var box = card.querySelector(".pick");
      if (!when) return;
      var found = box && box.checked ? place[box.value] : null;
      if (!found) {
        when.textContent = "";
        return;
      }
      if (!found.clock) {
        when.textContent = "Não cabe hoje";
        return;
      }
      when.textContent = found.mate
        ? found.clock + " · com " + found.mate
        : found.clock + " · sozinho no post";
    });
    paintPlan();
  }
  var orders = {
    csv: function (a, b) { return num(a, "data-pos") - num(b, "data-pos"); },
    discount: function (a, b) {
      return (num(b, "data-discount") || 0) - (num(a, "data-discount") || 0) || orders.csv(a, b);
    },
    "price-asc": function (a, b) { return priceOf(a, 1e12) - priceOf(b, 1e12) || orders.csv(a, b); },
    "price-desc": function (a, b) { return priceOf(b, -1) - priceOf(a, -1) || orders.csv(a, b); },
    savings: function (a, b) { return (num(b, "data-savings") || 0) - (num(a, "data-savings") || 0) || orders.csv(a, b); },
    title: function (a, b) {
      return (a.getAttribute("data-title") || "").localeCompare(b.getAttribute("data-title") || "", "pt-BR");
    }
  };
  function priceOf(card, missing) {
    var value = num(card, "data-price");
    return value === null ? missing : value;
  }
  function sortCards() {
    var box = document.querySelector(".books");
    if (!box) return;
    var key = sortBy && orders[sortBy.value] ? sortBy.value : "csv";
    cards().sort(orders[key]).forEach(function (card) { box.appendChild(card); });
  }
  function apply() {
    var low = only && only.checked;
    var text = (query && query.value || "").trim().toLowerCase();
    var least = minDiscount ? Number(minDiscount.value || 0) : 0;
    var ceiling = maxPrice && maxPrice.value !== "" ? Math.round(Number(maxPrice.value) * 100) : null;
    var wanted = category ? category.value : "";
    var pickedOnly = onlyPicked && onlyPicked.checked;
    var skipKids = hideKids && hideKids.checked;
    var visible = 0;
    cards().forEach(function (card) {
      var box = card.querySelector(".pick");
      var ok = !low || card.getAttribute("data-low") === "1";
      var hay = card.getAttribute("data-text") || "";
      if (text && hay.indexOf(text) < 0) ok = false;
      if (least > 0 && (num(card, "data-discount") || 0) < least) ok = false;
      if (ceiling !== null && !isNaN(ceiling)) {
        var price = num(card, "data-price");
        if (price === null || price > ceiling) ok = false;
      }
      if (wanted && card.getAttribute("data-category") !== wanted) ok = false;
      if (pickedOnly && !(box && box.checked)) ok = false;
      if (skipKids && card.getAttribute("data-kids") === "1") ok = false;
      card.hidden = !ok;
      if (ok) visible += 1;
    });
    if (shown) shown.textContent = visible + " na tela";
    remember();
  }
  var shelf = document.querySelector(".books");
  var storageKey = "curation-filters-" + ((shelf && shelf.getAttribute("data-loja")) || "amazon");
  function remember() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({
        sort: sortBy ? sortBy.value : "csv",
        discount: minDiscount ? minDiscount.value : "0",
        price: maxPrice ? maxPrice.value : "",
        category: category ? category.value : "",
        low: !!(only && only.checked),
        picked: !!(onlyPicked && onlyPicked.checked),
        kids: !!(hideKids && hideKids.checked)
      }));
    } catch (e) {}
  }
  function restore() {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(storageKey) || "null"); } catch (e) {}
    if (!saved) return;
    if (sortBy && orders[saved.sort]) sortBy.value = saved.sort;
    if (minDiscount && saved.discount) minDiscount.value = saved.discount;
    if (maxPrice && typeof saved.price === "string") maxPrice.value = saved.price;
    if (category && saved.category) {
      var exists = Array.prototype.some.call(category.options, function (option) { return option.value === saved.category; });
      if (exists) category.value = saved.category;
    }
    if (only) only.checked = !!saved.low;
    if (onlyPicked) onlyPicked.checked = !!saved.picked;
    if (hideKids) hideKids.checked = !!saved.kids;
  }
  var reset = document.getElementById("clear-filters");
  if (reset) {
    reset.addEventListener("click", function () {
      if (sortBy) sortBy.value = "csv";
      if (minDiscount) minDiscount.value = "0";
      if (maxPrice) maxPrice.value = "";
      if (category) category.value = "";
      if (only) only.checked = false;
      if (onlyPicked) onlyPicked.checked = false;
      if (hideKids) hideKids.checked = false;
      if (query) query.value = "";
      sortCards();
      apply();
    });
  }
  if (only) only.addEventListener("change", apply);
  if (query) query.addEventListener("input", apply);
  if (sortBy) sortBy.addEventListener("change", function () { sortCards(); apply(); });
  [minDiscount, category, onlyPicked, hideKids].forEach(function (field) {
    if (field) field.addEventListener("change", apply);
  });
  if (maxPrice) maxPrice.addEventListener("input", apply);
  document.querySelectorAll(".pick").forEach(function (box) {
    box.addEventListener("change", function () {
      if (onlyPicked && onlyPicked.checked) apply();
      var loja = box.getAttribute("data-loja") || "amazon";
      post("/curadoria/marcar", "asin=" + encodeURIComponent(box.value) +
        "&loja=" + encodeURIComponent(loja) + "&on=" + (box.checked ? "1" : "0")
      ).catch(function () {
        box.checked = !box.checked;
        paintTimes();
      });
    });
  });
  var file = document.getElementById("csv-file");
  if (file) {
    file.addEventListener("change", function () {
      var chosen = file.files && file.files[0];
      if (!chosen) return;
      fetch("/curadoria/csv", {method: "POST", headers: {"Content-Type": "text/csv; charset=utf-8"}, body: chosen})
        .then(function (response) {
          if (!response.ok) throw new Error("falhou");
          var loja = (booksEl && booksEl.getAttribute("data-loja")) || "amazon";
          window.location = "/curadoria?loja=" + encodeURIComponent(loja) + "&ok=1";
        })
        .catch(function () {
          var note = document.getElementById("upload-error");
          if (note) note.hidden = false;
        });
    });
  }
  var booksEl = document.querySelector(".books");
  var gridBtn = document.getElementById("view-grid");
  var listBtn = document.getElementById("view-list");
  function setView(list) {
    if (!booksEl) return;
    booksEl.classList.toggle("as-list", list);
    if (gridBtn) gridBtn.setAttribute("aria-pressed", list ? "false" : "true");
    if (listBtn) listBtn.setAttribute("aria-pressed", list ? "true" : "false");
    try { localStorage.setItem("curation-view", list ? "list" : "grid"); } catch (e) {}
  }
  if (gridBtn) gridBtn.addEventListener("click", function () { setView(false); });
  if (listBtn) listBtn.addEventListener("click", function () { setView(true); });
  try { if (localStorage.getItem("curation-view") === "list") setView(true); } catch (e) {}
  var interval = document.getElementById("interval");
  var intervalError = document.getElementById("interval-error");
  var intervalTimer;
  if (interval) {
    interval.addEventListener("change", saveInterval);
    interval.addEventListener("input", function () {
      clearTimeout(intervalTimer);
      intervalTimer = setTimeout(saveInterval, 400);
    });
  }
  function saveInterval() {
    if (!interval) return;
    post("/curadoria/intervalo", "interval=" + encodeURIComponent(interval.value))
      .then(function () {
        if (intervalError) intervalError.hidden = true;
      })
      .catch(function (error) {
        if (intervalError) {
          intervalError.hidden = false;
          intervalError.textContent = error.message || "Não salvei o intervalo.";
        }
      });
  }
  restore();
  sortCards();
  apply();
  paintTimes();
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
    plan: list[dict] | None = None,
) -> str:
    picked = marked if marked is not None else sum(1 for book in books if book.picked)
    low = sum(1 for book in books if book.low_365)
    note = f'<p class="alert" role="status">{escape(notice)}</p>' if notice else ""
    folder = ""
    if folder_file:
        folder = f'<p class="muted">Na pasta: {escape(folder_file)}</p>'
    captured_label = f'<span class="captured">Capturado em {escape(captured)}</span>' if captured else ""
    labels = peers or {}
    photos = covers or {}
    cards = "".join(
        _card(book, labels.get(book.asin, ""), store, photos.get(book.asin, ""), photos_ready)
        for book in books
    )
    empty = "" if books else "<p>Nenhum CSV carregado ainda.</p>"
    amazon_current = ' aria-current="page"' if store != "ml" else ""
    ml_current = ' aria-current="page"' if store == "ml" else ""
    checked_here = sum(1 for book in books if book.picked)
    if store == "ml":
        ml_total = checked_here if ml_marked is None else ml_marked
        az_total = 0 if amazon_marked is None else amazon_marked
    else:
        az_total = checked_here if amazon_marked is None else amazon_marked
        ml_total = 0 if ml_marked is None else ml_marked
    rows = json.dumps(plan or [], ensure_ascii=False).replace("<", "\\u003c")
    body = f"""
    <h1>Curadoria</h1>
    <p class="lede">Marque o livro na loja em que ele está em oferta. Cada post sai com uma oferta da Amazon e uma do Mercado Livre. A fila abaixo mostra quem vai com quem, e as setas trocam os pares. Definir a fila troca o que ainda não foi enviado hoje.</p>
    {note}
    {_photo_note(store, photos_ready or any(book.image_url for book in books))}
    <nav class="store-tabs" aria-label="Onde marcar">
      <a href="/curadoria?loja=amazon"{amazon_current}>Amazon · <span id="count-amazon">{az_total}</span></a>
      <a href="/curadoria?loja=mercadolivre"{ml_current}>Mercado Livre · <span id="count-ml">{ml_total}</span></a>
    </nav>
    <section class="plan" aria-label="Fila prevista">
      <h2>Fila prevista</h2>
      <p id="queue-note" class="muted">Marque um livro na Amazon e um no Mercado Livre. Os dois saem juntos no mesmo post.</p>
      <div class="plan-head" aria-hidden="true">
        <span>Hora</span>
        <span>Amazon</span>
        <span>Mercado Livre</span>
      </div>
      <ol id="queue-list" class="plan-list"></ol>
    </section>
    <form method="post" action="/curadoria/pasta">
      <button type="submit">Importar os CSVs da pasta</button>
    </form>
    <label class="muted">Ou carregar do computador
      <input id="csv-file" type="file" accept=".csv,text/csv">
    </label>
    <p id="upload-error" class="alert" hidden>Não consegui ler esse arquivo.</p>
    {folder}
    <p class="muted">{escape(source) if source else "Nenhum arquivo importado."} · {len(books)} livros · {low} com menor preço em 365 dias</p>
    <div class="filters" role="group" aria-label="Ordenar e filtrar">
      <label>Ordenar por
        <select id="sort-by">
          <option value="csv">Ordem do CSV</option>
          <option value="discount">Maior desconto</option>
          <option value="price-asc">Menor preço</option>
          <option value="price-desc">Maior preço</option>
          <option value="savings">Maior economia em R$</option>
          <option value="title">Título (A–Z)</option>
        </select>
      </label>
      <label>Desconto mínimo
        <select id="min-discount">
          <option value="0">Qualquer</option>
          <option value="20">20% ou mais</option>
          <option value="30">30% ou mais</option>
          <option value="40">40% ou mais</option>
          <option value="50">50% ou mais</option>
          <option value="60">60% ou mais</option>
          <option value="70">70% ou mais</option>
        </select>
      </label>
      <label>Preço até (R$)
        <input id="max-price" type="number" min="0" step="1" inputmode="decimal" placeholder="Sem limite">
      </label>
      <label>Categoria
        <select id="category">
          <option value="">Todas</option>
          {_category_options(books)}
        </select>
      </label>
      <label class="inline"><input id="only-picked" type="checkbox"> Só marcados</label>
      <label class="inline"><input id="hide-kids" type="checkbox"> Ocultar infantis</label>
      <button type="button" id="clear-filters" class="ghost">Limpar filtros</button>
      <span id="shown" aria-live="polite"></span>
    </div>
    <div class="curation-bar">
      {captured_label}
      <label><input id="only-low" type="checkbox"> Só menor preço em 365 dias</label>
      <label class="search">Buscar <input id="q" type="search" placeholder="Título ou categoria"></label>
      <div class="views" role="group" aria-label="Formato">
        <button type="button" id="view-grid" class="ghost" aria-pressed="true">Cards</button>
        <button type="button" id="view-list" class="ghost" aria-pressed="false">Lista</button>
      </div>
      <label>Minutos entre posts <input id="interval" type="number" min="5" max="180" value="{int(interval)}"></label>
      <span id="mix" class="muted">{len(plan or [])} posts</span>
      <span class="count"><span id="count">{picked}</span> marcados</span>
      <form method="post" action="/curadoria/fila" onsubmit="return confirm('A fila de hoje passa a ser a fila prevista. O que ainda não foi enviado é substituído.');">
        <button type="submit">Definir a fila</button>
      </form>
    </div>
    <p id="interval-error" class="alert" hidden></p>
    <div class="books" data-loja="{"mercadolivre" if store == "ml" else "amazon"}">{cards}</div>
    {empty}
    <script type="application/json" id="curation-clocks">{json.dumps(clocks or [])}</script>
    <script type="application/json" id="curation-plan">{rows}</script>
    """
    return _page(
        "Curadoria",
        f"<main>{body}</main>",
        nav=True,
        body_class="wide",
        extra_style=_STYLE,
        extra_script=_SCRIPT,
    )


def _offer(book: CatalogBook) -> str:
    if book.price_cents is None:
        return ""
    price = format_brl(book.price_cents)
    percent = discount_percent(book)
    if percent:
        return f'<span class="price">{escape(price)} <b>−{percent}%</b></span>'
    return f'<span class="price">{escape(price)}</span>'


def discount_percent(book: CatalogBook) -> int:
    if book.price_cents is None or not book.list_cents or book.list_cents <= book.price_cents:
        return 0
    return round((book.list_cents - book.price_cents) * 100 / book.list_cents)


def _savings_cents(book: CatalogBook) -> int:
    if book.price_cents is None or not book.list_cents or book.list_cents <= book.price_cents:
        return 0
    return book.list_cents - book.price_cents


def _category_options(books: list[CatalogBook]) -> str:
    counts: dict[str, int] = {}
    for book in books:
        name = (book.category or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return "".join(
        f'<option value="{escape(name)}">{escape(name)} ({total})</option>' for name, total in ordered
    )


def _product_link(book: CatalogBook) -> str:
    url = (book.url or "").strip()
    if not url.startswith("https://"):
        return ""
    return (
        f'<a class="product" href="{escape(url)}" target="_blank" rel="noopener noreferrer">Ver produto</a>'
    )


def _photo_note(store: str, photos_ready: bool) -> str:
    if store != "ml" or photos_ready:
        return ""
    return (
        '<p class="muted">Livro que também está na Amazon mostra a capa de lá. '
        "A foto do anúncio entra depois que os cookies do Mercado Livre estão em Configurações.</p>"
    )


def _card(book: CatalogBook, peer: str, store: str, remote: str = "", photos_ready: bool = False) -> str:
    checked = " checked" if book.picked else ""
    badge = '<span class="badge">Menor preço em 365 dias</span>' if book.low_365 else ""
    also = f'<span class="peer">{escape(peer)}</span>' if peer else ""
    text = escape(f"{book.title} {book.category}".casefold())
    loja = "ml" if store == "ml" else "amazon"
    image = _image(book, loja, remote, photos_ready)
    price = "" if book.price_cents is None else str(int(book.price_cents))
    return f"""
    <article class="book" data-low="{1 if book.low_365 else 0}" data-text="{text}"
      data-pos="{int(book.position)}" data-price="{price}" data-discount="{discount_percent(book)}"
      data-savings="{_savings_cents(book)}" data-title="{escape(book.title.casefold())}"
      data-category="{escape((book.category or '').strip())}" data-kids="{1 if book.kids else 0}">
      <label>
        <input class="pick" type="checkbox" data-loja="{loja}" value="{escape(book.asin)}"{checked}>
        {image}
        <span>
          <strong>{escape(book.title)}</strong>
          <em>{escape(book.category)}</em>
          {_offer(book)}
          <span class="when"></span>
          {badge}
          {also}
        </span>
      </label>
      {_product_link(book)}
    </article>
    """


def _image(book: CatalogBook, loja: str, remote: str = "", photos_ready: bool = False) -> str:
    local = f"/curadoria/capa/{escape(book.asin)}.jpg"
    if loja == "ml" and book.image_url:
        src, fallback = book.image_url, remote
    elif loja == "ml" and photos_ready:
        src, fallback = local, remote
    elif remote:
        src, fallback = remote, ""
    elif loja == "ml":
        return '<img alt="" width="72" height="106">'
    else:
        src, fallback = cover_url(book.asin), local
    if not fallback:
        return (
            f'<img src="{escape(src)}" alt="" width="72" height="106" loading="lazy" '
            'referrerpolicy="no-referrer">'
        )
    return (
        f'<img src="{escape(src)}" data-fallback="{escape(fallback)}" alt="" '
        'width="72" height="106" loading="lazy" referrerpolicy="no-referrer" '
        "onerror=\"if(!this.dataset.tried){this.dataset.tried='1';this.src=this.dataset.fallback}\">"
    )
