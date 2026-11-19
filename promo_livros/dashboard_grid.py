"""Grade da /hoje: uma linha por horário, com até duas ofertas."""
from __future__ import annotations

from html import escape

from promo_livros.formatter import format_brl
from promo_livros.lojas import store_of
from promo_livros.send_schedule import upcoming_clocks

_STORE_LABEL = {"amazon": "Amazon", "ml": "Mercado Livre", "shopee": "Shopee", "magalu": "Magazine Luiza"}


def render_grid(posts: list, schedule, now_clock: str | None, day: str = "") -> str:
    posts = [post for post in posts if not day or not getattr(post, "day", "") or post.day == day]
    scheduled = sorted((post for post in posts if post.status == "scheduled"), key=lambda post: (post.clock, post.id))
    done = sorted((post for post in posts if post.status != "scheduled"), key=lambda post: (post.clock, post.id))
    taken = {post.clock for post in scheduled}
    try:
        free = [clock for clock in upcoming_clocks(schedule, now_clock or "00:00") if clock not in taken]
    except ValueError:
        free = []
    head = (
        '<div class="grid-head" aria-hidden="true">'
        "<span></span><span>Horário</span><span></span><span>Oferta</span><span>Segunda oferta</span><span></span>"
        "</div>"
    )
    body = "".join(_row(post, movable=True) for post in scheduled)
    if not scheduled:
        body = '<p class="empty-state">Nenhum post na fila.</p>'
    past = ""
    if done:
        word = "post saiu ou ficou de fora" if len(done) == 1 else "posts saíram ou ficaram de fora"
        past = (
            f'<details class="grid-done"><summary>{len(done)} {word}</summary>'
            f'{"".join(_row(post, movable=False) for post in done)}</details>'
        )
    return (
        f'<div class="grid-view" data-free="{escape(",".join(free))}" '
        f'data-interval="{int(schedule.post_interval_minutes)}" data-end="{escape(schedule.end)}">'
        f'{past}{head}<div id="grid-queue">{body}</div></div>'
    )


def _row(post, *, movable: bool) -> str:
    shelf = getattr(post, "shelf", ()) or ()
    first, second = _pair(shelf)
    title = (first or second).title if (first or second) else post.title
    grip = (
        '<span class="grid-grip" draggable="true" title="Arrastar para mudar de lugar" aria-hidden="true">⠿</span>'
        if movable
        else "<span></span>"
    )
    menu = (
        f'<button type="button" class="mini ghost js-grid-menu" aria-label="Opções do post das {escape(post.clock)}">⋯</button>'
        if movable
        else "<span></span>"
    )
    status = "" if movable else f' data-status="{escape(post.status)}"'
    return (
        f'<div class="grid-row{"" if movable else " is-done"}" data-id="{post.id}" '
        f'data-clock="{escape(post.clock)}" data-title="{escape(title)}"{status}>'
        f"{grip}<time>{escape(post.clock)}</time>"
        f'<img class="grid-card" alt="" loading="lazy" src="/cards/{post.id}.jpg">'
        f"{_cell(first, 'amazon', movable)}{_cell(second, 'second', movable)}{menu}</div>"
    )


def _pair(shelf) -> tuple:
    """Amazon fica à esquerda quando a outra oferta é de outra loja. Duas da mesma loja seguem a ordem do post."""
    books = list(shelf)
    if len(books) <= 1:
        return (books[0] if books else None, None)
    amazon = next((book for book in books if store_of(book) == "amazon"), None)
    other = next((book for book in books if store_of(book) != "amazon"), None)
    if amazon is not None and other is not None:
        return amazon, other
    return books[0], books[1]


def _cell(book, side: str, movable: bool) -> str:
    lado = "amazon" if side == "amazon" else "segunda"
    if book is None:
        if not movable:
            return f'<div class="grid-cell {side} is-empty">—</div>'
        return (
            f'<button type="button" class="grid-cell {side} is-empty js-grid-book" data-lado="{lado}" '
            f'aria-label="Lado vazio">—</button>'
        )
    store = store_of(book)
    tag = f'<span class="grid-tag {store}">{_STORE_LABEL[store]}</span>'
    price = format_brl(book.price_cents) if book.price_cents else ""
    off = f" <b>−{round(book.discount_pct)}%</b>" if book.discount_pct else ""
    inner = (
        f'{tag}<strong title="{escape(book.title)}">{escape(book.title)}</strong>'
        f'<span class="grid-price">{escape(price)}{off}</span>'
    )
    if not movable:
        return f'<div class="grid-cell {side}">{inner}</div>'
    return (
        f'<button type="button" class="grid-cell {side} js-grid-book" data-lado="{lado}" '
        f'data-book="{escape(book.title)}" title="Trocar este livro com outro post">{inner}</button>'
    )


GRID_CSS = """
.view-switch { display: inline-flex; gap: 4px; padding: 4px; margin: 0 0 10px; background: var(--card); border: 1px solid var(--line); border-radius: 999px; }
.view-switch button { min-height: 36px; border-radius: 999px; padding: 0 14px; background: transparent; color: var(--muted); border: 0; font-weight: 600; }
.view-switch button[aria-pressed="true"] { background: var(--pill); color: var(--pill-ink); }
.grid-view { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 6px 10px; }
.grid-head, .grid-row {
  display: grid; grid-template-columns: 18px 3.4rem 56px minmax(0, 1fr) minmax(0, 1fr) 44px;
  gap: 10px; align-items: center;
}
.grid-head { color: var(--muted); font-size: 0.78rem; font-weight: 600; padding: 6px 0; border-bottom: 1px solid var(--line); }
.grid-row { padding: 6px 0; border-bottom: 1px solid var(--line); }
.grid-row:last-child { border-bottom: 0; }
.grid-row time { font-weight: 700; font-variant-numeric: tabular-nums; }
.grid-row.is-done { opacity: 0.6; }
.grid-row.is-dragging { opacity: 0.4; }
.grid-row.is-busy { opacity: 0.55; pointer-events: none; }
.grid-grip { cursor: grab; color: var(--muted); user-select: none; }
.grid-card { width: 56px; height: 42px; object-fit: cover; border-radius: 6px; background: #f3f1ea; display: block; }
.grid-cell { display: flex; flex-direction: column; gap: 2px; min-width: 0; font-size: 0.88rem; }
button.grid-cell {
  font: inherit; color: inherit; text-align: left; background: transparent; border: 1px solid transparent;
  border-radius: 10px; padding: 4px 6px; min-height: 40px; cursor: pointer; align-items: stretch;
}
button.grid-cell:hover { border-color: var(--line); }
button.grid-cell:focus-visible { outline: 2px solid var(--blue); outline-offset: 1px; }
.grid-view.is-picking button.grid-cell.is-target { border-color: var(--blue); border-style: dashed; }
.grid-view.is-picking button.grid-cell:not(.is-target):not(.is-picked) { opacity: 0.35; pointer-events: none; }
button.grid-cell.is-picked { border-color: var(--ink); background: color-mix(in srgb, var(--blue) 8%, transparent); }
.grid-picking-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px;
  padding: 8px 10px; margin: 4px 0 8px; border-radius: 10px; background: color-mix(in srgb, var(--blue) 10%, var(--card)); }
.grid-picking-bar { position: sticky; top: 8px; z-index: 5; }
.grid-picking-bar[hidden] { display: none; }
.grid-cell strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.grid-cell.is-empty { color: var(--muted); }
.grid-price { color: var(--muted); font-variant-numeric: tabular-nums; }
.grid-price b { color: var(--chip-green-ink); }
.grid-tag { align-self: flex-start; font-size: 0.7rem; font-weight: 700; border-radius: 999px; padding: 0 6px; background: var(--line); }
.grid-tag.amazon { background: #EEF3F8; color: #1F3A5F; }
.grid-tag.shopee { background: #FDE8E1; color: #A53A16; }
.grid-tag.ml { background: #FFF6CC; color: #6B5600; }
.grid-tag.magalu { background: #E6F0FF; color: #0046BE; }
.grid-done summary { cursor: pointer; color: var(--muted); padding: 6px 0; font-weight: 600; }
dialog.grid-dialog { border: 0; border-radius: 14px; background: var(--card); color: var(--ink); width: min(26rem, calc(100% - 1.5rem)); padding: 16px 18px; }
dialog.grid-dialog::backdrop { background: rgba(20, 24, 28, 0.35); }
.grid-dialog h2 { font-size: 1rem; margin: 0 0 4px; }
.grid-dialog p { margin: 0 0 10px; color: var(--muted); }
.grid-dialog .grid-actions { display: grid; gap: 8px; margin: 10px 0; }
.grid-dialog .grid-inline { display: flex; gap: 8px; align-items: center; }
.grid-dialog .grid-inline input, .grid-dialog select { font: inherit; min-height: 40px; border-radius: 10px; border: 1px solid var(--line); background: var(--card); color: var(--ink); padding: 0 10px; }
.grid-dialog .grid-inline input { width: 6rem; }
.grid-dialog button { min-height: 40px; }
.grid-dialog .grid-close { margin-top: 6px; }
@media (max-width: 720px) {
  .grid-head { display: none; }
  .grid-row { grid-template-columns: 18px 3.2rem minmax(0, 1fr) 44px; }
  .grid-row .grid-card { display: none; }
  .grid-row .grid-cell.second { grid-column: 3; }
}
"""

GRID_DIALOGS = """
<dialog class="grid-dialog" id="grid-menu" aria-labelledby="grid-menu-title">
  <h2 id="grid-menu-title"></h2>
  <p id="grid-menu-sub"></p>
  <div class="grid-actions">
    <label class="grid-inline">Mover para <select id="grid-target"></select></label>
    <div class="grid-inline" id="grid-taken" hidden>
      <button type="button" class="ghost" id="grid-swap"></button>
      <button type="button" class="ghost" id="grid-before"></button>
    </div>
    <button type="button" class="ghost" id="grid-move" hidden>Mover</button>
    <div class="grid-inline">
      <input type="number" id="grid-minutes" min="-60" max="180" step="5" value="20" aria-label="Minutos">
      <button type="button" class="ghost" id="grid-push">Empurrar daqui em diante</button>
    </div>
    <button type="button" class="ghost" id="grid-open">Abrir um horário aqui</button>
    <div class="grid-inline">
      <input type="number" id="grid-interval" min="5" max="180" step="5" aria-label="Intervalo em minutos">
      <button type="button" class="ghost" id="grid-respace">Reespaçar daqui em diante</button>
    </div>
  </div>
  <button type="button" class="ghost grid-close" id="grid-menu-close">Fechar</button>
</dialog>
<dialog class="grid-dialog" id="grid-fora" aria-labelledby="grid-fora-title">
  <h2 id="grid-fora-title">Passa do horário de envio</h2>
  <p id="grid-fora-text"></p>
  <div class="grid-actions">
    <button type="button" class="primary" id="grid-fit" hidden></button>
    <button type="button" class="ghost danger" id="grid-overtime"></button>
    <button type="button" class="ghost" id="grid-fora-cancel">Cancelar</button>
  </div>
</dialog>
"""

GRID_JS = r"""
(function () {
  var grid = document.getElementById("grid");
  var list = document.getElementById("rows");
  if (!grid || !list) return;
  var tabs = document.getElementById("tabs");
  var search = document.querySelector(".belt label.search");
  var menu = document.getElementById("grid-menu");
  var fora = document.getElementById("grid-fora");
  var current = null;
  var pending = null;
  var dragged = null;

  function $(id) { return document.getElementById(id); }
  function toast(message, undo) {
    if (window.hojeToast) window.hojeToast(message, undo);
  }
  function view() {
    try { return localStorage.getItem("hoje_view") === "grade" ? "grade" : "lista"; } catch (error) { return "lista"; }
  }
  function applyView() {
    var showGrid = view() === "grade";
    grid.hidden = !showGrid;
    list.hidden = showGrid;
    if (tabs) tabs.hidden = showGrid;
    if (search) search.hidden = showGrid;
    document.querySelectorAll(".view-switch button").forEach(function (button) {
      button.setAttribute("aria-pressed", button.dataset.view === view() ? "true" : "false");
    });
  }
  document.querySelectorAll(".view-switch button").forEach(function (button) {
    button.addEventListener("click", function () {
      try { localStorage.setItem("hoje_view", button.dataset.view); } catch (error) {}
      applyView();
    });
  });
  applyView();

  function gridData() { return grid.querySelector(".grid-view") || grid; }
  function rows() { return Array.prototype.slice.call(grid.querySelectorAll("#grid-queue .grid-row")); }
  function reload() {
    if (document.activeElement && grid.contains(document.activeElement)) document.activeElement.blur();
    if (window.hojeRefresh) window.hojeRefresh(true);
  }
  function send(path, params, undoAction) {
    var body = new URLSearchParams();
    Object.keys(params).forEach(function (key) {
      if (params[key] !== undefined && params[key] !== null && params[key] !== "") body.set(key, params[key]);
    });
    var row = grid.querySelector('.grid-row[data-id="' + params.id + '"]');
    if (row) row.classList.add("is-busy");
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json" },
      body: body.toString()
    })
      .then(function (response) {
        var type = response.headers.get("Content-Type") || "";
        if (type.indexOf("application/json") < 0) { location.reload(); return null; }
        return response.json();
      })
      .then(function (data) {
        if (!data) return;
        if (data.fora) { openFora(path, params, data.fora); if (row) row.classList.remove("is-busy"); return; }
        if (!data.ok) { toast(data.error || "Não mudei os horários."); reload(); return; }
        toast(data.message || "Pronto.", data.undo ? (undoAction || undo) : null);
        reload();
      })
      .catch(function () {
        toast("Não consegui falar com o painel. Tente de novo.");
        if (row) row.classList.remove("is-busy");
      });
  }
  function undo() {
    fetch("/hoje/horarios/desfazer", { method: "POST", headers: { "Accept": "application/json" }, body: "" })
      .then(function (response) { return response.json(); })
      .then(function (data) { toast(data.ok ? data.message : (data.error || "Não desfiz.")); reload(); })
      .catch(function () { toast("Não desfiz."); });
  }

  function openMenu(row) {
    current = row;
    $("grid-menu-title").textContent = row.dataset.clock + " · " + row.dataset.title;
    $("grid-menu-sub").textContent = "Escolha um horário ou mexa nos horários daqui em diante.";
    var select = $("grid-target");
    select.textContent = "";
    var placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Escolha…";
    select.append(placeholder);
    var free = (gridData().dataset.free || "").split(",").filter(Boolean);
    var options = [];
    free.forEach(function (clock) { options.push({ clock: clock, id: "" }); });
    rows().forEach(function (other) {
      if (other !== row) options.push({ clock: other.dataset.clock, id: other.dataset.id, title: other.dataset.title });
    });
    options.sort(function (a, b) { return a.clock < b.clock ? -1 : a.clock > b.clock ? 1 : 0; });
    options.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.clock;
      option.dataset.id = item.id;
      option.textContent = item.id ? item.clock + " · ocupado · " + item.title.slice(0, 40) : item.clock + " · livre";
      select.append(option);
    });
    $("grid-taken").hidden = true;
    $("grid-move").hidden = true;
    $("grid-interval").value = gridData().dataset.interval || "40";
    $("grid-open").textContent = "Abrir um horário aqui (+" + (gridData().dataset.interval || "40") + " min)";
    if (typeof menu.showModal === "function") menu.showModal(); else menu.setAttribute("open", "");
  }
  function closeMenu() { if (menu.open) menu.close(); }
  $("grid-target").addEventListener("change", function () {
    var option = this.selectedOptions[0];
    var taken = option && option.dataset.id;
    $("grid-taken").hidden = !taken;
    $("grid-move").hidden = !option || !option.value || !!taken;
    if (taken) {
      $("grid-swap").textContent = "Trocar com o post das " + option.value;
      $("grid-before").textContent = "Entrar antes dele";
    }
  });
  $("grid-move").addEventListener("click", function () {
    var clock = $("grid-target").value;
    closeMenu();
    send("/hoje/horario", { id: current.dataset.id, clock: clock });
  });
  $("grid-swap").addEventListener("click", function () {
    var other = $("grid-target").selectedOptions[0].dataset.id;
    closeMenu();
    send("/hoje/trocar", { id: current.dataset.id, com: other });
  });
  $("grid-before").addEventListener("click", function () {
    var other = $("grid-target").selectedOptions[0].dataset.id;
    closeMenu();
    send("/hoje/antes", { id: current.dataset.id, de: other });
  });
  $("grid-push").addEventListener("click", function () {
    var minutes = parseInt($("grid-minutes").value, 10);
    if (!minutes) return;
    closeMenu();
    send("/hoje/empurrar", { id: current.dataset.id, minutos: minutes });
  });
  $("grid-open").addEventListener("click", function () {
    closeMenu();
    send("/hoje/empurrar", { id: current.dataset.id, minutos: gridData().dataset.interval || "40" });
  });
  $("grid-respace").addEventListener("click", function () {
    var interval = parseInt($("grid-interval").value, 10);
    if (!interval) return;
    closeMenu();
    send("/hoje/reespacar", { id: current.dataset.id, intervalo: interval });
  });
  $("grid-menu-close").addEventListener("click", closeMenu);

  function openFora(path, params, info) {
    pending = { path: path, params: params, info: info };
    var many = info.count === 1 ? "1 post passaria" : info.count + " posts passariam";
    $("grid-fora-text").textContent = many + " do fim do envio (" + (gridData().dataset.end || "") + "). O último ficaria às " + info.last + ".";
    var fit = $("grid-fit");
    fit.hidden = !info.fit_interval || path === "/hoje/horario";
    if (info.fit_interval) fit.textContent = "Encaixar com intervalo de " + info.fit_interval + " min";
    $("grid-overtime").textContent = "Passar do horário de envio até " + info.last;
    if (typeof fora.showModal === "function") fora.showModal(); else fora.setAttribute("open", "");
  }
  $("grid-fit").addEventListener("click", function () {
    if (!pending) return;
    var params = Object.assign({}, pending.params, { intervalo: pending.info.fit_interval });
    fora.close();
    send(pending.path, params);
  });
  $("grid-overtime").addEventListener("click", function () {
    if (!pending) return;
    if (!window.confirm("Os posts vão sair depois do fim do envio de hoje. Confirmar?")) return;
    var params = Object.assign({}, pending.params, { permitir_fora: "1" });
    fora.close();
    send(pending.path, params);
  });
  $("grid-fora-cancel").addEventListener("click", function () { fora.close(); reload(); });

  var picking = null;
  var pickingBar = $("grid-picking");
  function startPick(cell) {
    var row = cell.closest(".grid-row");
    var lado = cell.dataset.lado;
    picking = { id: row.dataset.id, lado: lado, cell: cell };
    document.body.dataset.busy = "1";
    gridData().classList.add("is-picking");
    cell.classList.add("is-picked");
    grid.querySelectorAll('#grid-queue .js-grid-book[data-lado="' + lado + '"]').forEach(function (other) {
      if (other.closest(".grid-row") !== row) other.classList.add("is-target");
    });
    $("grid-picking-text").textContent = cell.dataset.book
      ? "Escolha o post que vai receber “" + cell.dataset.book.slice(0, 50) + "”. Os dois livros trocam de lugar."
      : "Escolha de qual post vem o livro para este horário.";
    if (pickingBar) pickingBar.hidden = false;
  }
  function stopPick() {
    picking = null;
    delete document.body.dataset.busy;
    gridData().classList.remove("is-picking");
    grid.querySelectorAll(".is-target, .is-picked").forEach(function (cell) {
      cell.classList.remove("is-target", "is-picked");
    });
    if (pickingBar) pickingBar.hidden = true;
  }
  function swapBook(params) {
    send("/hoje/trocar-livro", params, function () { swapBook(params); });
  }
  if ($("grid-picking-cancel")) $("grid-picking-cancel").addEventListener("click", stopPick);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && picking) stopPick();
  });

  grid.addEventListener("click", function (event) {
    var button = event.target.closest(".js-grid-menu");
    if (button) { if (picking) stopPick(); openMenu(button.closest(".grid-row")); return; }
    var cell = event.target.closest(".js-grid-book");
    if (!cell) return;
    if (!picking) { startPick(cell); return; }
    if (cell === picking.cell) { stopPick(); return; }
    if (!cell.classList.contains("is-target")) return;
    var params = { id: picking.id, com: cell.closest(".grid-row").dataset.id, lado: picking.lado };
    stopPick();
    swapBook(params);
  });

  grid.addEventListener("dragstart", function (event) {
    var handle = event.target.closest(".grid-grip");
    if (!handle) return;
    dragged = handle.closest(".grid-row");
    dragged.classList.add("is-dragging");
    document.body.dataset.busy = "1";
    event.dataTransfer.effectAllowed = "move";
  });
  grid.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var row = event.target.closest("#grid-queue .grid-row");
    if (!row || row === dragged) return;
    event.preventDefault();
    var box = row.getBoundingClientRect();
    if (event.clientY > box.top + box.height / 2) row.after(dragged); else row.before(dragged);
  });
  grid.addEventListener("drop", function (event) { if (dragged) event.preventDefault(); });
  grid.addEventListener("dragend", function () {
    if (!dragged) return;
    dragged.classList.remove("is-dragging");
    dragged = null;
    delete document.body.dataset.busy;
    var body = new URLSearchParams();
    rows().forEach(function (row) { body.append("id", row.dataset.id); });
    fetch("/hoje/reordenar", { method: "POST", body: body, redirect: "manual" })
      .then(function () { toast("Fila reordenada."); reload(); })
      .catch(function () { toast("A ordem não foi salva."); reload(); });
  });
})();
"""
