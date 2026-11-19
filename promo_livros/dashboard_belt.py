"""Página /hoje. Só apresentação: a fila e o envio continuam nos módulos de sempre."""
from __future__ import annotations

import re
from datetime import datetime
from html import escape

from promo_livros.dashboard_grid import GRID_DIALOGS, render_grid
from promo_livros.formatter import format_brl
from promo_livros.lojas import STORE_ORDER, store_of
from promo_livros.send_schedule import slot_clocks, upcoming_clocks

_STORE_NAMES = {"amazon": "Amazon", "ml": "Mercado Livre", "shopee": "Shopee", "magalu": "Magazine Luiza"}

_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_ABAS = (
    ("todas", "Todos"),
    ("fila", "Fila"),
    ("enviadas", "Enviados"),
    ("falha", "Falhas"),
    ("substituidos", "Substituídos"),
)
_STAR = re.compile(r"\*([^*\n]+)\*")
_ITALIC = re.compile(r"_([^_\n]+)_")
_BOLD = re.compile(r"\*([^*\n]+)\*")
_TOOLTIP = (
    "Salvar não muda o horário dos posts que já estão na fila. "
    "Reorganizar põe os que ainda não saíram nos horários da grade que ainda não passaram "
    "e tira o que já foi enviado hoje. O que não cabe antes do fim vai para a reserva."
)


def fragments(
    day: str,
    posts: list,
    *,
    sending: bool,
    schedule,
    groups: tuple[str, ...] = (),
    aba: str = "todas",
    now: datetime | None = None,
    whatsapp: str = "unknown",
    paused_until: str = "",
    members=None,
    repeat_days: int = 1,
    arquivo: list | None = None,
    invites: str = "",
) -> dict[str, str]:
    pieces = _pieces(
        day,
        posts,
        sending=sending,
        schedule=schedule,
        groups=groups,
        aba=aba,
        now=now,
        whatsapp=whatsapp,
        paused_until=paused_until,
        members=members,
        repeat_days=repeat_days,
        arquivo=arquivo,
    )
    return {**pieces, "invites": invites}


def page_body(
    day: str,
    posts: list,
    *,
    notice: str | None,
    sending: bool,
    schedule,
    groups: tuple[str, ...] = (),
    aba: str = "todas",
    now: datetime | None = None,
    whatsapp: str = "unknown",
    paused_until: str = "",
    members=None,
    repeat_days: int = 1,
    arquivo: list | None = None,
    invites: str = "",
) -> str:
    data = _pieces(
        day,
        posts,
        sending=sending,
        schedule=schedule,
        groups=groups,
        aba=aba,
        now=now,
        whatsapp=whatsapp,
        paused_until=paused_until,
        members=members,
        repeat_days=repeat_days,
        arquivo=arquivo,
    )
    alert = f'<p class="alert" role="alert">{escape(notice)}</p>' if notice else ""
    suggested = escape(_suggested(posts, schedule, now))
    return f"""
<div class="shell belt">
  <div class="progress"></div>
  <header class="top">
    <div>
      <h1>Promo Livros</h1>
      <p class="sub">Programação do dia · {escape(_day_title(day))}</p>
    </div>
    <div class="top-actions">
      <div class="status-pills" id="pills">{data["pills"]}</div>
      <div id="toggle">{data["toggle"]}</div>
      <details class="menu">
        <summary>Pausar até…</summary>
        <form method="post" action="/hoje/pausar">
          <button class="ghost" name="minutos" value="30" type="submit">30 min</button>
          <button class="ghost" name="minutos" value="60" type="submit">1 h</button>
          <button class="ghost" name="minutos" value="amanha" type="submit">até amanhã</button>
        </form>
      </details>
      <button class="primary" type="button" id="open-composer">+ Programar post</button>
      <button class="ghost theme" type="button" id="theme-toggle" aria-label="Alternar tema">◐</button>
      <details class="menu">
        <summary aria-label="Mais opções">···</summary>
        <form method="post" action="/logout"><button class="ghost" type="submit">Sair</button></form>
      </details>
    </div>
  </header>
  <nav class="segments" aria-label="Seções">
    <a href="/hoje" aria-current="page">Hoje</a>
    <a href="/enviados">Enviados</a>
    <a href="/whatsapp">WhatsApp</a>
    <a href="/enquetes">Enquetes</a>
    <a href="/grupos">Grupos</a>
    <a href="/assinaturas">Assinaturas</a>
    <a href="/campanhas">Campanhas</a>
    <a href="/configuracoes">Configurações</a>
    <a href="/curadoria">Curadoria</a>
  </nav>
  {alert}
  <div id="funnel">{data["funnel"]}</div>
  <div id="members">{data["members"]}</div>
  <div id="dayline">{data["dayline"]}</div>
  <div id="warn">{data["warn"]}</div>
  <div class="layout">
    <section>
      <label class="search">
        <span class="sr">Buscar por título</span>
        <input id="q" type="search" placeholder="Buscar por título" autocomplete="off">
      </label>
      <div class="view-switch" role="group" aria-label="Como ver a fila">
        <button type="button" data-view="lista" aria-pressed="true">Lista</button>
        <button type="button" data-view="grade" aria-pressed="false">Grade</button>
      </div>
      <nav class="filters" id="tabs" aria-label="Filtro da fila">{data["tabs"]}</nav>
      <div id="rows">{data["rows"]}</div>
      <div class="grid-picking-bar" id="grid-picking" role="status" hidden>
        <span id="grid-picking-text"></span>
        <button type="button" class="ghost mini" id="grid-picking-cancel">Cancelar</button>
      </div>
      <div id="grid" hidden>{data["grid"]}</div>
      <noscript>
        <details class="manual" open>
          <summary>Programar um post</summary>
          <form method="post" action="/hoje/manual">
            {_composer_fields(suggested, required_cover=True, with_ids=False)}
            <button type="submit">Programar</button>
          </form>
        </details>
      </noscript>
    </section>
    <aside class="side">
      <div id="invites">{invites}</div>
      {_rules_html(schedule, repeat_days)}
      <section class="panel-card">
        <h2>Envios por hora</h2>
        <div id="hours">{data["hours"]}</div>
      </section>
      <section class="panel-card">
        <h2>Por faixa de desconto hoje</h2>
        <div id="bands">{data["bands"]}</div>
      </section>
      <section class="panel-card">
        <h2>Grupos</h2>
        <div id="groups">{data["groups"]}</div>
      </section>
    </aside>
  </div>
  <dialog class="drawer" id="composer">
    <div class="drawer-body">
      <div class="drawer-head">
        <h2 id="composer-title">Programar um post</h2>
        <button class="ghost" type="button" id="close-composer">Fechar</button>
      </div>
      <form method="post" action="/hoje/manual" id="composer-form">
        <input type="hidden" name="id" id="composer-id" value="">
        <div class="composer-grid">
          <div>
            {_composer_fields(suggested, required_cover=True)}
            <button class="primary" type="submit" id="composer-submit">Programar</button>
          </div>
          <div>
            <p class="eyebrow">Prévia no WhatsApp</p>
            <div class="preview" id="preview" aria-live="polite"></div>
          </div>
        </div>
      </form>
    </div>
  </dialog>
  <dialog class="light" id="lightbox">
    <button class="ghost" type="button" id="close-light">Fechar</button>
    <img alt="" id="light-img">
  </dialog>
  {GRID_DIALOGS}
  <div id="toast" role="status" hidden></div>
</div>
"""


def _pieces(
    day: str,
    posts: list,
    *,
    sending: bool,
    schedule,
    groups: tuple[str, ...],
    aba: str,
    now: datetime | None,
    whatsapp: str,
    paused_until: str,
    members=None,
    repeat_days: int = 1,
    arquivo: list | None = None,
) -> dict[str, str]:
    chosen = aba if aba in {key for key, _label in _ABAS} or aba == "descartadas" else "todas"
    now_clock = _clock_text(now)
    visible = [post for post in posts if _aba_keeps(chosen, post, now_clock)]
    return {
        "pills": _pills(sending, whatsapp, _future_pause(paused_until, now)),
        "toggle": _toggle(sending),
        "funnel": _funnel(posts),
        "dayline": _dayline(posts, schedule, now_clock),
        "warn": _warn(posts, schedule, now_clock, whatsapp),
        "tabs": _tabs(posts, chosen, now_clock, arquivo),
        "rows": _rows(visible, posts, chosen, groups, now_clock, whatsapp, arquivo),
        "hours": _hours(posts, schedule),
        "bands": _bands(posts),
        "members": _members(members),
        "groups": _groups(posts, groups),
        "grid": render_grid(posts, schedule, now_clock, day),
    }


def _missed(post, now_clock: str | None) -> bool:
    """Horário já passou e nenhum grupo recebeu a mensagem."""
    if post.status != "scheduled" or not now_clock:
        return False
    if any(send.status == "sent" for send in post.sends):
        return False
    clock = _minutes(post.clock)
    current = _minutes(now_clock)
    if clock is None or current is None:
        return False
    return clock < current


def _aba_keeps(aba: str, post, now_clock: str | None = None) -> bool:
    missed = _missed(post, now_clock)
    failed = (
        missed
        or post.status == "failed"
        or post.link_state in {"broken", "unavailable"}
        or any(send.status not in {"sent", "sending"} for send in post.sends)
    )
    if aba == "fila":
        return post.status == "scheduled" and not missed and post.link_state not in {"broken", "unavailable"}
    if aba == "enviadas":
        return post.status == "sent"
    if aba == "falha":
        return failed
    if aba == "descartadas":
        return post.status == "cancelled"
    if aba == "substituidos":
        return post.status == "replaced"
    if aba == "todas":
        return post.status not in {"cancelled", "replaced", "sent"}
    return False


def _toggle(sending: bool) -> str:
    value = "0" if sending else "1"
    label = "Pausar envios" if sending else "Ligar envios"
    return (
        '<form method="post" action="/whatsapp/envio">'
        f'<input type="hidden" name="enabled" value="{value}">'
        '<input type="hidden" name="next" value="/hoje">'
        f'<button class="ghost" type="submit">{label}</button></form>'
    )


def _pills(sending: bool, whatsapp: str, paused_label: str) -> str:
    if paused_label:
        send = f'<span class="pill-dot wait"><i></i>Pausado até {escape(paused_label)}</span>'
    elif sending:
        send = '<span class="pill-dot ok"><i></i>Envio ligado</span>'
    else:
        send = '<span class="pill-dot bad"><i></i>Envio desligado</span>'
    if whatsapp == "connected":
        wa = '<span class="pill-dot ok"><i></i>WhatsApp conectado</span>'
    elif whatsapp in {"qr", "starting"}:
        wa = '<span class="pill-dot wait"><i></i>WhatsApp aguardando</span>'
    elif whatsapp == "unknown":
        wa = '<span class="pill-dot off"><i></i>WhatsApp</span>'
    else:
        wa = '<span class="pill-dot bad"><i></i>WhatsApp desconectado</span>'
    return wa + send


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _funnel(posts: list) -> str:
    programmed = sum(1 for post in posts if post.status not in {"cancelled", "replaced"})
    sent = sum(1 for post in posts if post.status == "sent")
    queued = sum(1 for post in posts if post.status == "scheduled")
    reached = sum(1 for post in posts for send in post.sends if send.status == "sent")
    steps = (
        (programmed, "blue", f"<b>{_plural(programmed, 'programado', 'programados')}</b> hoje"),
        (sent, "ink", f"<b>{_plural(sent, 'enviado', 'enviados')}</b> no dia"),
        (queued, "amber", "<b>na fila</b> agora"),
        (reached, "green", f"<b>{_plural(reached, 'grupo', 'grupos')}</b> {_plural(reached, 'alcançado', 'alcançados')}"),
    )
    parts = []
    for index, (number, tone, label) in enumerate(steps):
        if index:
            parts.append('<span class="arrow" aria-hidden="true">→</span>')
        parts.append(
            f'<p class="step {tone}"><strong class="num">{number}</strong><span>{label}</span></p>'
        )
    return f'<section class="funnel" aria-label="Resumo do dia">{"".join(parts)}</section>'


def _dayline(posts: list, schedule, now_clock: str | None) -> str:
    start = _minutes(schedule.start)
    end = _minutes(schedule.end)
    progress = 0.0
    if now_clock and start is not None and end is not None and end > start:
        current = _minutes(now_clock)
        if current is not None:
            progress = max(0.0, min(100.0, (current - start) * 100 / (end - start)))
    dots = []
    for post in posts:
        if post.status not in {"scheduled", "sent", "failed"} and post.link_state not in {"broken", "unavailable"}:
            continue
        left = _percent(post.clock, schedule.start, schedule.end)
        if left is None:
            continue
        kind = (
            "sent"
            if post.status == "sent"
            else "failed"
            if post.status == "failed" or _missed(post, now_clock)
            else "scheduled"
            if post.status == "scheduled"
            else "failed"
        )
        dots.append(
            f'<i class="dot {kind}" style="left:{left:.2f}%" title="{escape(post.clock)} {kind}"></i>'
        )
    now_mark = ""
    if now_clock:
        side = " flip" if progress > 68 else ""
        now_mark = (
            f'<i class="now-mark{side}" style="left:{progress:.2f}%">'
            f"<span>agora {escape(now_clock)}</span></i>"
        )
    waiting = sorted(post.clock for post in posts if post.status == "scheduled")
    sent_at = [
        send.at
        for post in posts
        for send in post.sends
        if send.status == "sent" and send.at
    ]
    if waiting:
        nxt = waiting[0]
        relative = _relative(now_clock, nxt)
        extra = f" ({relative})" if relative else ""
        head = f"Próximo post às {nxt}{extra}"
    else:
        head = "Nenhum post na fila"
    last = max(sent_at) if sent_at else "—"
    slots = slot_clocks(schedule)
    note = (
        f"{head} · Último enviado {last} · Cabem {len(slots)} posts na grade · "
        f"Entre grupos: {schedule.group_gap_seconds} s"
    )
    label = f"Grade de {schedule.start} a {schedule.end}"
    if now_clock:
        label += f", agora {now_clock}"
    return f"""
    <div class="track" role="img" aria-label="{escape(label)}" style="--progress:{progress:.2f}%">
      <i class="rail"></i>
      <i class="fill"></i>
      {now_mark}
      {''.join(dots)}
    </div>
    <div class="scale"><span>{escape(schedule.start)}</span><span>{escape(schedule.end)}</span></div>
    <p class="meta-line">{escape(note)}</p>
    """


def _warn(posts: list, schedule, now_clock: str | None = None, whatsapp: str = "unknown") -> str:
    notes = []
    missed = [post for post in posts if _missed(post, now_clock)]
    if missed:
        count = len(missed)
        sentence = (
            "1 post passou do horário e não saiu."
            if count == 1
            else f"{count} posts passaram do horário e não saíram."
        )
        reason = " O WhatsApp está desconectado." if whatsapp not in {"connected", "unknown"} else ""
        notes.append(f'<p class="warn" role="status">{sentence}{reason}</p>')
    end = _minutes(schedule.end)
    if end is not None:
        late = [
            post
            for post in posts
            if post.status == "scheduled" and (_minutes(post.clock) or -1) >= end
        ]
        if late:
            count = len(late)
            word = "post fica" if count == 1 else "posts ficam"
            actions = []
            for post in late:
                actions.append(
                    f'<form method="post" action="/hoje/amanha">'
                    f'<input type="hidden" name="id" value="{post.id}">'
                    f'<button class="mini ghost" type="submit">Mover para amanhã</button></form>'
                    f'<form method="post" action="/hoje/apagar">'
                    f'<input type="hidden" name="id" value="{post.id}">'
                    f'<button class="mini ghost" type="submit">Descartar</button></form>'
                )
            notes.append(
                f'<p class="warn" role="status">{count} {word} depois das {escape(schedule.end)}.</p>'
                f'<div class="late-actions">{"".join(actions)}</div>'
            )
    return "".join(notes)


def _tabs(posts: list, chosen: str, now_clock: str | None = None, arquivo: list | None = None) -> str:
    links = []
    for key, label in _ABAS:
        if key == "enviadas" and arquivo is not None:
            count = len(arquivo)
        else:
            count = sum(1 for post in posts if _aba_keeps(key, post, now_clock))
        current = ' aria-current="page"' if key == chosen else ""
        links.append(f'<a href="/hoje?aba={key}"{current}>{escape(label)} {count}</a>')
    return "".join(links)


def _rows(
    visible: list,
    posts: list,
    chosen: str,
    groups: tuple[str, ...],
    now_clock: str | None,
    whatsapp: str = "unknown",
    arquivo: list | None = None,
) -> str:
    if chosen == "enviadas" and arquivo is not None:
        if not arquivo:
            return '<p class="empty-state">Nenhum post enviado ainda.</p>'
        return "".join(_row(post, groups, [], now_clock, whatsapp) for post in arquivo)
    if not visible:
        if chosen in {"todas", "fila"} and not any(post.status == "scheduled" for post in posts):
            return '<p class="empty-state">Nenhum post na fila — programe o primeiro.</p>'
        return '<p class="empty-state">Nenhum post nesta aba.</p>'
    sent = [post for post in visible if post.status == "sent"]
    rest = [post for post in visible if post.status != "sent"]
    sent.sort(key=lambda post: post.clock)
    rest.sort(key=lambda post: (post.status != "scheduled", post.clock))
    scheduled = [post for post in rest if post.status == "scheduled"]
    others = [post for post in rest if post.status != "scheduled"]
    scheduled_ids = [post.id for post in scheduled]
    blocks = []
    if chosen in {"todas", "fila"}:
        blocks.append(_stores_summary([post for post in posts if _aba_keeps("fila", post, now_clock)]))
    blocks.extend(_row(post, groups, scheduled_ids, now_clock, whatsapp) for post in sent)
    if sent and rest:
        stamp = f" {escape(now_clock)}" if now_clock else ""
        blocks.append(f'<div class="now-line" role="separator"><span>agora{stamp}</span></div>')
    blocks.append('<div id="queue">')
    blocks.extend(_row(post, groups, scheduled_ids, now_clock, whatsapp) for post in scheduled)
    blocks.append("</div>")
    blocks.extend(_row(post, groups, scheduled_ids, now_clock, whatsapp) for post in others)
    return "".join(blocks)


def _row(
    post,
    groups: tuple[str, ...],
    scheduled_ids: list[int],
    now_clock: str | None = None,
    whatsapp: str = "unknown",
) -> str:
    title = _star_title(post.caption, post.title)
    blurb = (post.blurb or _italic(post.caption)).strip()
    synopsis = f'<p class="synopsis">{escape(blurb)}</p>' if blurb else ""
    price = format_brl(post.price_cents) if post.price_cents else ""
    chips = _price_chips(post)
    link = _link_row(post)
    extra = _alert_chips(post)
    message = ""
    if post.caption:
        message = (
            '<details class="message"><summary>Ver mensagem</summary>'
            f'<div class="bubble">{_whatsapp_html(post.caption)}</div></details>'
        )
    dim = " sent" if post.status == "sent" else ""
    drag = ' draggable="false"'
    return f"""
    <article class="post{dim}" data-id="{post.id}" data-status="{escape(post.status)}" data-title="{escape(title)}"{drag}>
      <div class="when">
        {_grip(post)}
        <time>{escape(_when_label(post))}</time>
        <span>{escape(_clock_status(post, now_clock, whatsapp))}</span>
      </div>
      <div class="media">
        <button type="button" class="thumb-btn js-light" data-src="/cards/{post.id}.jpg" aria-label="Ampliar capa de {escape(title)}">
          <img class="thumb" alt="" width="64" height="90" src="/cards/{post.id}.jpg">
        </button>
        {_store_logos(post)}
      </div>
      <div class="copy">
        <h2>{escape(title)}</h2>
        {synopsis}
        <p class="price-line">{escape(price)} {chips}</p>
        {link}
        <div class="chips">{_send_chips(post, groups)}{extra}</div>
        {message}
        <div class="actions">{_actions(post, scheduled_ids)}</div>
      </div>
      {_steps(post)}
    </article>
    """


def _post_stores(post) -> list[str]:
    books = getattr(post, "shelf", ()) or (post,)
    found = {store_of(book) for book in books}
    return sorted(found, key=lambda store: STORE_ORDER.get(store, 9))


def _store_logo(store: str, css: str) -> str:
    label = _STORE_NAMES.get(store, store)
    return f'<img class="{css}" src="/lojas/{escape(store)}.png" alt="{escape(label)}" title="{escape(label)}" loading="lazy">'


def _store_logos(post) -> str:
    marks = "".join(_store_logo(store, "store-logo") for store in _post_stores(post))
    return f'<div class="store-logos">{marks}</div>' if marks else ""


def _stores_summary(posts: list) -> str:
    """Quantos posts que ainda vão sair levam cada loja. Post com duas lojas conta nas duas."""
    counts: dict[str, int] = {}
    for post in posts:
        for store in _post_stores(post):
            counts[store] = counts.get(store, 0) + 1
    if not counts:
        return ""
    items = "".join(
        f'<li>{_store_logo(store, "store-logo")}<b>{count}</b></li>'
        for store, count in sorted(counts.items(), key=lambda item: STORE_ORDER.get(item[0], 9))
    )
    total = len(posts)
    return (
        '<section class="stores-summary" aria-label="Posts na fila por loja">'
        f'<span>{total} {_plural(total, "post ainda vai sair", "posts ainda vão sair")}:</span>'
        f"<ul>{items}</ul></section>"
    )


def _when_label(post) -> str:
    stamp = getattr(post, "day", "") or ""
    if len(stamp) == 10 and stamp[4] == "-" and stamp[7] == "-":
        return f"{stamp[8:10]}/{stamp[5:7]} {post.clock}"
    return post.clock


def _grip(post) -> str:
    if post.status != "scheduled":
        return ""
    return '<span class="grip" draggable="true" aria-label="Arrastar para reordenar" title="Arrastar para reordenar">⠿</span>'


def _actions(post, scheduled_ids: list[int]) -> str:
    duplicate = (
        f'<form method="post" action="/hoje/duplicar">'
        f'<input type="hidden" name="id" value="{post.id}">'
        f'<button class="mini ghost" type="submit">Duplicar</button></form>'
    )
    if post.status != "scheduled":
        return duplicate
    index = scheduled_ids.index(post.id) if post.id in scheduled_ids else -1
    up_disabled = " disabled" if index <= 0 else ""
    down_disabled = " disabled" if index < 0 or index >= len(scheduled_ids) - 1 else ""
    edit = (
        f'<button type="button" class="mini ghost js-edit" '
        f'data-id="{post.id}" data-clock="{escape(post.clock)}" '
        f'data-title="{escape(_star_title(post.caption, post.title))}" '
        f'data-blurb="{escape((post.blurb or "").replace(chr(10), " "))}" '
        f'data-price="{escape(_input_price(post.price_cents))}" '
        f'data-list="{escape(_input_price(post.list_price_cents or 0))}" '
        f'data-url="{escape(post.url)}">Editar</button>'
    )
    return (
        _move(post.id, -1, "↑ Subir", up_disabled)
        + _move(post.id, 1, "↓ Descer", down_disabled)
        + edit
        + _mini_form("/hoje/agora", post.id, "Enviar agora")
        + _mini_form("/hoje/pular", post.id, "Pular")
        + duplicate
        + (
            f'<form method="post" action="/hoje/apagar" onsubmit="return confirm(\'Tirar este post da fila?\')">'
            f'<input type="hidden" name="id" value="{post.id}">'
            f'<button class="mini ghost danger js-undo-delete" type="submit">Apagar</button></form>'
        )
    )


def _move(post_id: int, direction: int, label: str, disabled: str) -> str:
    return (
        f'<form method="post" action="/hoje/mover">'
        f'<input type="hidden" name="id" value="{post_id}">'
        f'<input type="hidden" name="direcao" value="{direction}">'
        f'<button class="mini ghost" type="submit"{disabled}>{label}</button></form>'
    )


def _mini_form(action: str, post_id: int, label: str) -> str:
    return (
        f'<form method="post" action="{action}">'
        f'<input type="hidden" name="id" value="{post_id}">'
        f'<button class="mini ghost" type="submit">{label}</button></form>'
    )


def _price_chips(post) -> str:
    chips = []
    if post.discount_pct:
        percent = int(round(post.discount_pct))
        tone = "go" if percent >= 30 else "hot"
        chips.append(f'<span class="chip {tone}">-{percent}%</span>')
    label = (post.lowest_label or "").strip().rstrip(".")
    if label:
        chips.append(f'<span class="chip wait">{escape(label)}</span>')
    return " ".join(chips)


def _alert_chips(post) -> str:
    if post.link_state == "price" and post.live_price_cents:
        value = format_brl(int(post.live_price_cents))
        return (
            f'<span class="chip hot">preço mudou: {escape(value)}</span>'
            f'<form method="post" action="/hoje/preco">'
            f'<input type="hidden" name="id" value="{post.id}">'
            f'<button class="mini ghost" type="submit">Atualizar</button></form>'
        )
    if post.link_state == "broken":
        return '<span class="chip hot">link quebrado</span>'
    if post.link_state == "unavailable":
        return '<span class="chip hot">indisponível</span>'
    return ""


def _link_row(post) -> str:
    if not post.url:
        return ""
    shown = post.url.replace("https://", "").replace("http://", "")
    return (
        f'<p class="amz">Link: <a href="{escape(post.url)}">{escape(shown)}</a> '
        f'<button type="button" class="mini ghost js-copy" data-url="{escape(post.url)}">Copiar</button></p>'
    )


def _send_chips(post, groups: tuple[str, ...]) -> str:
    names: list[str] = []
    if post.status == "scheduled":
        names.extend(groups)
    for send in post.sends:
        if send.group_name not in names:
            names.append(send.group_name)
    by_name = {send.group_name: send for send in post.sends}
    chips = []
    for name in names:
        send = by_name.get(name)
        status = send.status if send else "queued"
        if status == "sent":
            tone, word = "go", "enviado"
        elif status == "sending":
            tone, word = "wait", "enviando"
        elif status == "queued":
            tone, word = "wait", "na fila"
        else:
            tone, word = "hot", "falhou"
        chips.append(f'<span class="chip {tone}">{escape(name)} {word}</span>')
    return "".join(chips)


def _steps(post) -> str:
    sending = any(send.status == "sending" for send in post.sends)
    sent = post.status == "sent" or any(send.status == "sent" for send in post.sends)
    send_at = next((send.at for send in post.sends if send.status == "sending" and send.at), "")
    done_at = [send.at for send in post.sends if send.status == "sent" and send.at]
    done = max(done_at) if done_at else ""
    rows = (
        ("on", "programado", post.clock),
        ("on go" if sending or sent else "", "enviando", send_at or (done if sent else "")),
        ("on sent" if post.status == "sent" else "", "enviado", done if post.status == "sent" else ""),
    )
    items = []
    for klass, label, stamp in rows:
        items.append(
            f'<li class="{klass}"><i></i><span>{label}</span><time>{escape(stamp)}</time></li>'
        )
    return f'<ol class="steps">{"".join(items)}</ol>'


def _clock_status(post, now_clock: str | None = None, whatsapp: str = "unknown") -> str:
    if any(send.status == "sending" for send in post.sends):
        return "enviando"
    if _missed(post, now_clock):
        if whatsapp not in {"connected", "unknown"}:
            return "não saiu · WhatsApp desconectado"
        return "não saiu"
    if post.status == "sent":
        times = [send.at for send in post.sends if send.status == "sent" and send.at]
        if times:
            return f"enviado {max(times)}"
        return "enviado"
    if post.status == "failed" or post.link_state in {"broken", "unavailable"}:
        return "falhou"
    if post.status == "skipped":
        return "pulado"
    if post.status == "cancelled":
        return "descartado"
    if post.status == "replaced":
        return "substituído"
    return "programado"


def _hours(posts: list, schedule) -> str:
    planned = [0] * 24
    done = [0] * 24
    for post in posts:
        hour = _hour(post.clock)
        if hour is None or post.status in {"cancelled", "replaced"}:
            continue
        if post.status == "sent":
            done[hour] += 1
        elif post.status == "scheduled":
            planned[hour] += 1
    peak = max(planned[hour] + done[hour] for hour in range(24)) or 1
    start = _minutes(schedule.start) or 0
    end = _minutes(schedule.end) or 0
    cols = []
    for hour in range(24):
        inside = (hour + 1) * 60 > start and hour * 60 < end
        total = planned[hour] + done[hour]
        if total == 0:
            kind = "quiet" if not inside else "idle"
            cols.append(f'<span class="col" title="{hour}h · 0"><i class="{kind}"></i></span>')
            continue
        sent_h = max(8, round(done[hour] / peak * 72)) if done[hour] else 0
        plan_h = max(8, round(planned[hour] / peak * 72)) if planned[hour] else 0
        bars = ""
        if planned[hour]:
            bars += f'<i class="plan" style="height:{plan_h}px"></i>'
        if done[hour]:
            bars += f'<i class="sent" style="height:{sent_h}px"></i>'
        cols.append(
            f'<span class="col" title="{hour}h · {done[hour]} enviados · {planned[hour]} programados">'
            f"{bars}</span>"
        )
    return (
        f'<div class="chart" role="img" aria-label="Envios por hora, da 0h às 23h">{"".join(cols)}</div>'
        '<div class="scale"><span>0h</span><span>12h</span><span>23h</span></div>'
        f'<p class="muted">Cinza fora da grade {escape(schedule.start)}–{escape(schedule.end)}. '
        "Azul programado, verde enviado.</p>"
    )


def _bands(posts: list) -> str:
    counts = {"até 30%": 0, "30–50%": 0, "50%+": 0}
    for post in posts:
        if post.status in {"cancelled", "replaced"}:
            continue
        discount = post.discount_pct or 0
        if discount >= 50:
            counts["50%+"] += 1
        elif discount >= 30:
            counts["30–50%"] += 1
        else:
            counts["até 30%"] += 1
    peak = max(counts.values()) or 1
    rows = []
    for label, count in counts.items():
        width = 0 if count == 0 else max(8, round(count / peak * 100))
        rows.append(
            f'<div class="band"><div class="band-top"><span>{label}</span><strong>{count}</strong></div>'
            f'<div class="hbar"><i style="width:{width}%"></i></div></div>'
        )
    return "".join(rows)


def _members(view) -> str:
    if view is None or not view.available:
        return '<p class="muted">Não consegui ler os membros agora.</p>'
    cards = (
        ("Membros líquidos", str(view.liquid)),
        ("Entradas do dia", str(view.joined)),
        ("Saídas", str(view.left)),
        ("Líquido do dia", _signed(view.net)),
    )
    grid = "".join(
        f'<p class="stat"><strong class="num">{escape(value)}</strong><span>{escape(label)}</span></p>'
        for label, value in cards
    )
    lines = []
    for group in view.groups:
        lines.append(
            "<li>"
            f"<span>{escape(group.name)}</span>"
            f"<strong>{group.liquid} · hoje {_signed(group.net)}</strong>"
            "</li>"
        )
    detail = f'<ul class="member-lines">{"".join(lines)}</ul>' if lines else ""
    return f'<section class="members" aria-label="Membros dos grupos">{grid}{detail}</section>'


def _signed(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def _groups(posts: list, groups: tuple[str, ...]) -> str:
    names = list(groups) or sorted({send.group_name for post in posts for send in post.sends})
    if not names:
        return '<p class="muted">Nenhum grupo salvo.</p>'
    items = []
    for name in names:
        sent = sum(
            1
            for post in posts
            for send in post.sends
            if send.group_name == name and send.status == "sent"
        )
        items.append(
            f"<li><span>{escape(name)}</span><strong>{sent} {_plural(sent, 'enviado', 'enviados')}</strong></li>"
        )
    return f'<ul class="group-list">{"".join(items)}</ul>'


def _rules_html(schedule, repeat_days: int = 1) -> str:
    slots = slot_clocks(schedule)
    if slots:
        summary = f"Cabem {len(slots)} posts, de {slots[0]} às {slots[-1]}"
    else:
        summary = "A grade não tem horários."
    return f"""
    <section class="panel-card" id="regras">
      <h2>Regras de envio</h2>
      <form method="post" action="/envio/regras">
        <label class="inline">Primeiro post <input name="start" required value="{escape(schedule.start)}" pattern="[0-2][0-9]:[0-5][0-9]"></label>
        <label class="inline">Parar antes de <input name="end" required value="{escape(schedule.end)}" pattern="[0-2][0-9]:[0-5][0-9]"></label>
        <label class="inline">Minutos entre posts <input name="interval" type="number" min="5" max="180" required value="{schedule.post_interval_minutes}"></label>
        <label class="inline">Segundos entre grupos <input name="gap" type="number" min="5" max="600" required value="{schedule.group_gap_seconds}"></label>
        <label class="inline">Dias sem repetir o mesmo livro <input name="repeat" type="number" min="1" max="30" required value="{int(repeat_days)}"></label>
        <p class="fit">{escape(summary)}</p>
        <div class="rule-actions">
          <button type="submit">Salvar</button>
          <span class="tip">
            <button type="button" class="ghost icon" aria-describedby="tip-reorg" aria-expanded="false" aria-label="Como salvar e reorganizar funcionam">ⓘ</button>
            <span id="tip-reorg" role="tooltip">{escape(_TOOLTIP)}</span>
          </span>
        </div>
      </form>
      <form method="post" action="/hoje/reorganizar">
        <button class="ghost" type="submit">Reorganizar o que resta</button>
      </form>
      <form method="post" action="/hoje/limpar" onsubmit="return confirm('Tirar da fila o que ainda não foi enviado?')">
        <button class="ghost" type="submit">Limpar a fila</button>
      </form>
    </section>
    """


def _composer_fields(suggested: str, *, required_cover: bool, with_ids: bool = True) -> str:
    def tag(name: str) -> str:
        return f' id="{name}"' if with_ids else ""

    return f"""
    <label>Horário <input name="clock"{tag("field-clock")} required value="{suggested}" placeholder="21:00" pattern="[0-2][0-9]:[0-5][0-9]"></label>
    {_offer_fields("", "Primeira oferta", required=True, required_cover=required_cover, tag=tag, pull=with_ids)}
    {_offer_fields("2", "Segunda oferta", required=False, required_cover=False, tag=tag, pull=with_ids)}
    """


def _offer_fields(
    suffix: str,
    legend: str,
    *,
    required: bool,
    required_cover: bool,
    tag,
    pull: bool,
) -> str:
    """Um bloco por loja. O link preenche o resto; os campos continuam editáveis."""
    need = " required" if required else ""
    cover = " required" if required_cover else ""
    # O nome do campo é o que o formulário envia; o id é o que o botão de puxar dados usa.
    mark = "-2" if suffix else "-1"
    first_hint = (
        "Cole o link da Amazon ou do Mercado Livre e clique em Puxar dados."
        if pull
        else "Link da Amazon ou do Mercado Livre."
    )
    hint = first_hint if required else "Pode ser da mesma loja. Deixe vazio para o post sair com uma loja só."
    button = (
        f'<button type="button" class="ghost js-pull" data-alvo="{mark}">Puxar dados</button>'
        if pull
        else ""
    )
    return f"""
    <fieldset class="offer" id="offer{mark}">
      <legend>{legend} <span class="shop"{tag(f"shop{mark}")} hidden></span></legend>
      <p class="hint">{hint}</p>
      <div class="link-row">
        <input name="url{suffix}"{tag(f"field-url{mark}")}{need} placeholder="https://www.amazon.com.br/dp/..." inputmode="url">
        {button}
      </div>
      <p class="alert"{tag(f"link-error{mark}")} hidden></p>
      <label>Título <input name="title{suffix}"{tag(f"field-title{mark}")}{need}></label>
      <label>Texto <textarea name="blurb{suffix}"{tag(f"field-blurb{mark}")} rows="2"></textarea></label>
      <div class="money">
        <label>Preço <input name="price{suffix}"{tag(f"field-price{mark}")}{need} placeholder="39,90"></label>
        <label>Preço de <input name="list_price{suffix}"{tag(f"field-list{mark}")} placeholder="69,90"></label>
      </div>
      <label>Imagem <input name="cover{suffix}"{tag(f"field-cover{mark}")} placeholder="URL da capa"{cover}></label>
    </fieldset>
    """


def _whatsapp_html(caption: str) -> str:
    text = escape(caption or "")
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text.replace("\n", "<br>")


def _star_title(caption: str, fallback: str) -> str:
    match = _STAR.search(caption or "")
    if match:
        return match.group(1).strip()
    return fallback


def _italic(caption: str) -> str:
    match = _ITALIC.search(caption or "")
    return match.group(1).strip() if match else ""


def _input_price(cents: int) -> str:
    if not cents:
        return ""
    return format_brl(cents).replace("R$ ", "")


def _suggested(posts: list, schedule, now: datetime | None) -> str:
    used = {post.clock for post in posts if post.status == "scheduled"}
    now_clock = _clock_text(now)
    candidates = upcoming_clocks(schedule, now_clock) if now_clock else slot_clocks(schedule)
    for clock in candidates:
        if clock not in used:
            return clock
    return ""


def _future_pause(paused_until: str, now: datetime | None) -> str:
    if not paused_until or now is None:
        return ""
    try:
        moment = datetime.fromisoformat(paused_until)
    except ValueError:
        return ""
    current = now
    if moment.tzinfo is None and current.tzinfo is not None:
        moment = moment.replace(tzinfo=current.tzinfo)
    if moment.tzinfo is not None and current.tzinfo is None:
        return ""
    if current >= moment:
        return ""
    return moment.strftime("%H:%M")


def _clock_text(now: datetime | None) -> str | None:
    if now is None:
        return None
    return f"{now.hour:02d}:{now.minute:02d}"


def _minutes(value: str) -> int | None:
    if not value or ":" not in value:
        return None
    hour, _, minute = value.partition(":")
    if not (hour.isdigit() and minute.isdigit()):
        return None
    return int(hour) * 60 + int(minute)


def _hour(value: str) -> int | None:
    minutes = _minutes(value)
    if minutes is None:
        return None
    return minutes // 60


def _percent(clock: str, start: str, end: str) -> float | None:
    current = _minutes(clock)
    begin = _minutes(start)
    finish = _minutes(end)
    if current is None or begin is None or finish is None or finish <= begin:
        return None
    return max(0.0, min(100.0, (current - begin) * 100 / (finish - begin)))


def _relative(now_clock: str | None, target: str) -> str:
    if not now_clock:
        return ""
    now_m = _minutes(now_clock)
    target_m = _minutes(target)
    if now_m is None or target_m is None:
        return ""
    delta = target_m - now_m
    if delta == 0:
        return "agora"
    if delta < 0:
        return f"atrasado {-delta} min"
    if delta == 1:
        return "em 1 min"
    return f"em {delta} min"


def _day_title(day: str) -> str:
    parts = day.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return day
    year, month, number = (int(part) for part in parts)
    if not 1 <= month <= 12:
        return day
    return f"{number} de {_MONTHS[month - 1]} de {year}"


BELT_CSS = """
.belt { color: var(--ink); padding-bottom: 48px; }
.belt input[type="search"], .belt input[type="number"], .belt input[type="url"] {
  font: inherit; color: var(--ink); background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; min-height: 40px; padding: 0.45rem 0.75rem; width: 100%;
}
.belt label.inline input[type="number"] { width: 6.4rem; }
.belt h1 { font-size: 1.35rem; line-height: 1.15; margin: 0; letter-spacing: -0.03em; }
.belt h2 { font-size: 1rem; margin: 0 0 0.7rem; letter-spacing: -0.02em; }
.belt .sub, .belt .muted, .belt .meta-line, .belt .synopsis { color: var(--muted); }
.belt .top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding-top: 22px; }
.belt .top-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; }
.belt .status-pills { display: flex; flex-wrap: wrap; gap: 8px; }
.pill-dot {
  display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 12px;
  border-radius: 999px; font-weight: 600; font-size: 0.92rem;
}
.pill-dot i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; display: inline-block; }
.pill-dot.ok { background: var(--chip-green); color: var(--chip-green-ink); }
.pill-dot.bad { background: #FDECEA; color: #9d2c22; }
.pill-dot.wait { background: #FBF3E0; color: #7A5410; }
.pill-dot.off { background: #F1F3F5; color: var(--muted); }
.segments, .filters { display: flex; flex-wrap: wrap; gap: 4px; }
.segments {
  width: max-content; max-width: 100%; overflow-x: auto; flex-wrap: nowrap;
  margin: 14px 0 18px; padding: 4px;
  background: var(--card); border: 1px solid var(--line); border-radius: 999px;
}
.segments a, .filters a {
  min-height: 40px; display: inline-flex; align-items: center; padding: 0 14px;
  border-radius: 999px; text-decoration: none; font-weight: 600; color: var(--muted);
}
.segments a[aria-current="page"], .filters a[aria-current="page"] {
  background: var(--pill); color: var(--pill-ink);
}
.filters { margin-bottom: 12px; }
.funnel { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px 18px; margin: 8px 0 4px; }
.funnel .step { margin: 0; min-width: 7.5rem; }
.funnel .num {
  display: block; font-family: "Inter Tight", Inter, sans-serif; font-weight: 800;
  font-size: 72px; letter-spacing: -0.045em; line-height: 0.85;
  font-variant-numeric: tabular-nums;
}
.funnel .step span { display: block; margin-top: 4px; color: var(--muted); font-weight: 500; }
.funnel .step span b { color: var(--ink); font-weight: 700; }
.funnel .blue .num { color: var(--blue); }
.funnel .ink .num { color: var(--ink); }
.funnel .amber .num { color: var(--amber); }
.funnel .green .num { color: var(--green); }
.funnel .arrow { color: #C5CCD3; font-weight: 300; font-size: 1.6rem; padding-bottom: 1.5rem; }
.track { position: relative; height: 28px; margin: 18px 0 2px; }
.track .rail, .track .fill { position: absolute; left: 0; top: 16px; }
.track .rail { right: 0; border-top: 1px dashed #C5CCD3; }
.track .fill { width: var(--progress); border-top: 2px solid var(--ink); }
.track .now-mark { position: absolute; top: 4px; width: 1px; height: 22px; background: var(--ink); }
.track .now-mark span { position: absolute; top: -2px; left: 6px; font-size: 11px; color: var(--muted); white-space: nowrap; }
.track .now-mark.flip span { left: auto; right: 6px; }
.track .dot { position: absolute; top: 12px; width: 8px; height: 8px; border-radius: 50%; transform: translateX(-50%); }
.dot.scheduled { background: var(--blue); }
.dot.sent { background: var(--green); }
.dot.failed { background: var(--red); }
.scale { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.meta-line { margin: 8px 0 0; font-size: 0.92rem; }
.warn { color: #7A5410; background: #FBF3E0; border-radius: 10px; padding: 8px 12px; margin: 12px 0 0; }
.layout { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(240px, 0.8fr); gap: 16px; align-items: start; margin-top: 16px; }
.side { display: flex; flex-direction: column; gap: 12px; }
#invites:empty { display: none; }
.panel-card, .belt article.post {
  background: var(--card); border: 1px solid var(--line); border-radius: 14px;
  box-shadow: 0 1px 1px rgba(27, 31, 36, 0.04);
}
.panel-card { padding: 14px 16px; }
.belt label.search { display: block; margin: 0 0 10px; font-weight: 500; }
.belt label.search input { min-height: 40px; }
.belt article.post {
  display: grid; grid-template-columns: 76px 64px minmax(0, 1fr) 108px;
  gap: 12px 14px; padding: 12px 14px; margin-bottom: 10px;
}
.belt article.post.sent { opacity: 0.62; }
.belt .when { display: flex; flex-direction: column; gap: 2px; font-variant-numeric: tabular-nums; }
.belt .when time { font-weight: 700; font-size: 1.05rem; }
.belt .when span, .steps time { color: var(--muted); font-size: 0.82rem; }
.grip { cursor: grab; color: var(--muted); min-height: 24px; user-select: none; }
.thumb-btn {
  width: 64px; height: 90px; padding: 0; border: 0; border-radius: 8px; background: #f3f1ea;
  min-height: 40px; overflow: hidden;
}
.thumb { width: 64px; height: 90px; object-fit: cover; display: block; border-radius: 8px; }
.media { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.store-logos { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.store-logo { display: block; max-width: 56px; max-height: 18px; width: auto; height: auto; }
.stores-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin: 0 0 10px; padding: 8px 12px;
  background: var(--card); border: 1px solid var(--line); border-radius: 12px; color: var(--muted); font-size: 0.88rem; }
.stores-summary ul { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 0; padding: 0; list-style: none; }
.stores-summary li { display: flex; align-items: center; gap: 6px; }
.stores-summary b { color: var(--ink); font-variant-numeric: tabular-nums; font-size: 1rem; }
.belt .copy h2 { font-size: 1rem; margin: 0; }
.synopsis { margin: 2px 0 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.price-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-weight: 600; margin: 0 0 4px; }
.amz { margin: 0 0 6px; word-break: break-all; }
.amz a { color: var(--blue); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip {
  display: inline-flex; align-items: center; min-height: 26px; padding: 0 8px;
  border-radius: 999px; font-size: 0.82rem; font-weight: 600;
}
.chip.go { background: var(--chip-green); color: var(--chip-green-ink); }
.chip.wait { background: #FBF3E0; color: #7A5410; }
.chip.hot { background: #FDECEA; color: #9d2c22; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.actions form { margin: 0; }
button.mini, .belt .mini {
  min-height: 40px; padding: 0 10px; border-radius: 999px; font-size: 0.86rem;
}
button.danger { color: var(--red); }
.steps { list-style: none; margin: 0; padding: 0 0 0 4px; display: flex; flex-direction: column; gap: 8px; }
.steps li { display: grid; grid-template-columns: 12px 1fr; column-gap: 6px; position: relative; font-size: 0.75rem; }
.steps li span { grid-column: 2; }
.steps li time { grid-column: 2; }
.steps i { width: 8px; height: 8px; border-radius: 50%; border: 2px solid #D0D5DC; margin-top: 2px; }
.steps li.on i { background: var(--blue); border-color: var(--blue); }
.steps li.go.on i { background: var(--amber); border-color: var(--amber); }
.steps li.sent.on i { background: var(--green); border-color: var(--green); }
.steps li:not(:last-child) i::after {
  content: ""; position: absolute; left: 5px; top: 12px; width: 1px; height: 16px; background: #E3E7EC;
}
.message { margin-top: 8px; }
.bubble {
  margin-top: 8px; background: #E7F6D8; color: #14210f; border-radius: 12px; padding: 10px 12px;
  white-space: normal; line-height: 1.4;
}
.now-line { display: flex; align-items: center; gap: 10px; color: var(--muted); margin: 6px 0 12px; font-size: 0.85rem; }
.now-line::before, .now-line::after { content: ""; flex: 1; border-top: 1px dashed #C5CCD3; }
.empty-state { color: var(--muted); padding: 28px 8px; }
.chart { height: 84px; display: flex; align-items: flex-end; gap: 3px; }
.chart .col { flex: 1; height: 100%; display: flex; flex-direction: column; justify-content: flex-end; gap: 1px; }
.chart i { display: block; width: 100%; border-radius: 2px 2px 0 0; min-height: 3px; }
.chart .quiet { height: 6px; background: #D5DAE0; }
.chart .idle { height: 6px; background: #EEF1F4; }
.chart .plan { background: var(--blue); }
.chart .sent { background: var(--green); }
.band { margin-bottom: 8px; }
.band-top { display: flex; justify-content: space-between; font-size: 0.9rem; }
.hbar { height: 8px; background: #F1F3F5; border-radius: 999px; overflow: hidden; }
.hbar i { display: block; height: 100%; background: var(--blue); border-radius: 999px; }
.group-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.members { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px 28px; margin: 18px 0 6px; }
.members .stat { margin: 0; min-width: 8rem; }
.members .num {
  display: block; font-family: "Inter Tight", Inter, sans-serif; font-weight: 800;
  font-size: 40px; letter-spacing: -0.04em; line-height: 1; font-variant-numeric: tabular-nums;
}
.members .stat span { display: block; margin-top: 4px; color: var(--muted); font-weight: 500; }
.member-lines { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px 18px; width: 100%; }
.member-lines li { display: flex; justify-content: space-between; gap: 8px; font-size: 0.85rem; }
.member-lines strong { font-variant-numeric: tabular-nums; font-weight: 600; }
.group-list li {
  display: flex; justify-content: space-between; gap: 8px; align-items: center;
  background: var(--chip-green); color: var(--chip-green-ink); border-radius: 999px; padding: 8px 12px;
  min-height: 40px;
}
.belt label.inline {
  display: flex; justify-content: space-between; align-items: center; gap: 12px;
  font-weight: 500; margin: 0 0 8px;
}
.belt label.inline input { width: 6.4rem; min-height: 40px; text-align: right; }
.fit { color: var(--muted); margin: 4px 0 10px; }
.rule-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.tip { position: relative; }
.tip [role="tooltip"] {
  display: none; position: absolute; right: 0; z-index: 3; width: min(260px, 70vw);
  background: var(--pill); color: var(--pill-ink); border-radius: 10px; padding: 8px 10px; font-size: 0.85rem;
}
.tip:hover [role="tooltip"], .tip:focus-within [role="tooltip"], .tip button[aria-expanded="true"] + [role="tooltip"] { display: block; }
button.icon { min-width: 40px; padding: 0; }
details.menu { position: relative; }
details.menu > summary {
  list-style: none; min-height: 40px; display: inline-flex; align-items: center; padding: 0 12px;
  border: 1px solid var(--line); border-radius: 999px; background: var(--card); cursor: pointer; font-weight: 600;
}
details.menu > summary::-webkit-details-marker { display: none; }
details.menu > form { display: none; }
details.menu[open] > form {
  display: grid; position: absolute; right: 0; top: calc(100% + 6px); z-index: 4;
  background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 8px; gap: 6px; min-width: 160px;
}
dialog.drawer {
  margin: 0 0 0 auto; height: 100%; max-height: 100%; width: min(920px, 100%);
  border: 0; border-left: 1px solid var(--line); border-radius: 0; padding: 0;
  background: var(--card); color: var(--ink);
}
dialog.drawer::backdrop, dialog.light::backdrop { background: rgba(20, 24, 28, 0.35); }
.drawer-body { padding: 20px; overflow: auto; height: 100%; }
.drawer-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
.composer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; align-items: start; }
.composer-grid > div:last-child { position: sticky; top: 0; }
.eyebrow { color: var(--muted); font-size: 0.8rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
.preview { background: #E7F6D8; color: #14210f; border-radius: 12px; padding: 12px 14px; min-height: 180px; line-height: 1.4; }
.belt textarea {
  font: inherit; color: var(--ink); background: var(--card); border: 1px solid var(--line);
  border-radius: 10px; min-height: 76px; padding: 8px 10px; width: 100%;
}
dialog.light { border: 0; padding: 12px; background: transparent; max-width: calc(100vw - 32px); }
dialog.light img { max-width: min(420px, 86vw); max-height: 78vh; width: auto; height: auto; border-radius: 12px; display: block; background: #fff; }
#toast[hidden] { display: none; }
#toast:not([hidden]) {
  position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
  background: var(--pill); color: var(--pill-ink); border-radius: 999px;
  padding: 8px 8px 8px 16px; display: flex; align-items: center; gap: 8px; z-index: 7;
}
.progress { display: none; }
body.is-loading .progress { display: block; position: fixed; top: 0; left: 0; height: 3px; width: 42%; background: var(--blue); z-index: 8; }
.skeleton-row {
  height: 108px; border-radius: 14px; margin-bottom: 10px; border: 1px solid var(--line);
  background: linear-gradient(90deg, var(--card) 25%, #f3f5f7 37%, var(--card) 63%);
  background-size: 400% 100%; animation: shine 1.2s ease infinite;
}
@keyframes shine { 0% { background-position: 100% 0; } 100% { background-position: 0 0; } }
.sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); border: 0; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .funnel .num { font-size: 48px; }
  .members .num { font-size: 32px; }
  .belt article.post { grid-template-columns: 72px 64px minmax(0, 1fr); }
  .steps { grid-column: 1 / -1; flex-direction: row; gap: 14px; }
}
@media (max-width: 640px) {
  .composer-grid { grid-template-columns: 1fr; }
  dialog.drawer { width: 100%; }
  .belt .top { flex-direction: column; }
  .segments a { padding: 0 10px; }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton-row { animation: none; }
}
.offer {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px 12px;
  margin: 12px 0 0;
}
.offer legend { font-weight: 700; font-size: 0.9rem; padding: 0 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.offer .hint { color: var(--muted); font-size: 0.8rem; margin: 0 0 8px; }
.offer .alert { margin: 8px 0 0; }
.link-row { display: flex; gap: 8px; align-items: center; }
.link-row input { flex: 1 1 auto; min-width: 0; }
.link-row button { white-space: nowrap; }
.money { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.shop { font-size: 0.75rem; font-weight: 700; border-radius: 999px; padding: 2px 8px; }
.shop[hidden] { display: none; }
.shop-az { background: color-mix(in srgb, var(--blue) 16%, var(--card)); color: var(--blue); }
.shop-ml { background: color-mix(in srgb, var(--amber) 22%, var(--card)); color: var(--amber); }
html[data-theme="dark"] .pill-dot.bad { background: #3a2220; color: #f6d2ce; }
html[data-theme="dark"] .pill-dot.wait, html[data-theme="dark"] .chip.wait, html[data-theme="dark"] .warn { background: #3a311c; color: #f3ddb0; }
html[data-theme="dark"] .chip.hot { background: #3a2220; color: #f6d2ce; }
html[data-theme="dark"] .chart .quiet { background: #3a424c; }
html[data-theme="dark"] .chart .idle, html[data-theme="dark"] .hbar { background: #2a313a; }
html[data-theme="dark"] .funnel .arrow, html[data-theme="dark"] .track .rail { color: #4a5562; border-color: #4a5562; }
html[data-theme="dark"] .bubble, html[data-theme="dark"] .preview { color: #14210f; }
"""

BELT_JS = r"""
(function () {
  var rows = document.getElementById("rows");
  var dragged = null;
  var snapshot = "";
  var dropped = false;
  var toastTimer = 0;

  function esc(value) {
    return String(value || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function field(id) {
    var node = document.getElementById(id);
    return node ? node.value.trim() : "";
  }
  function setField(id, value) {
    var node = document.getElementById(id);
    if (node && value) node.value = value;
  }
  function storeOf(url) {
    if (/mercadoli(vre|bre)\.com|meli\.la/i.test(url)) return "ml";
    return /amazon\.com|amzn\.to|a\.co|link\.amazon/i.test(url) ? "amazon" : "";
  }
  function storeName(store) {
    return store === "ml" ? "Mercado Livre" : "Amazon";
  }
  function offerBlock(mark, labelled) {
    var title = field("field-title" + mark);
    var blurb = field("field-blurb" + mark);
    var price = field("field-price" + mark);
    var listed = field("field-list" + mark);
    var url = field("field-url" + mark);
    if (!title && !price && !url) return "";
    var html = "";
    if (title) html += "📖 <strong>" + esc(title) + "</strong><br>";
    if (blurb) html += "ℹ️ <em>" + esc(blurb) + "</em><br>";
    if (price) {
      html += "💲 R$ " + esc(price);
      if (listed) html += " <s>R$ " + esc(listed) + "</s>";
      html += "<br><br>";
    }
    if (url) {
      var store = storeOf(url);
      html += "🔗 " + (labelled && store ? esc(storeName(store)) + ": " : "") + esc(url);
    }
    return html;
  }
  function paint() {
    var preview = document.getElementById("preview");
    if (!preview) return;
    var first = offerBlock("-1", false);
    var second = offerBlock("-2", true);
    if (second) first = offerBlock("-1", true);
    var blocks = [first, second].filter(Boolean);
    preview.innerHTML = blocks.join("<br><br>") || "A prévia aparece aqui.";
  }
  function pullLink(mark) {
    var input = document.getElementById("field-url" + mark);
    var error = document.getElementById("link-error" + mark);
    var shop = document.getElementById("shop" + mark);
    var button = document.querySelector('.js-pull[data-alvo="' + mark + '"]');
    if (!input || !input.value.trim()) return;
    if (error) error.hidden = true;
    if (button) { button.disabled = true; button.textContent = "Lendo…"; }
    fetch("/hoje/link", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "url=" + encodeURIComponent(input.value.trim())
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (data.error) throw new Error(data.error);
        setField("field-title" + mark, data.title);
        setField("field-price" + mark, data.price);
        setField("field-list" + mark, data.list_price);
        setField("field-cover" + mark, data.cover);
        if (data.url) input.value = data.url;
        if (shop) {
          shop.hidden = !data.store;
          shop.textContent = storeName(data.store);
          shop.className = "shop " + (data.store === "ml" ? "shop-ml" : "shop-az");
        }
        paint();
      })
      .catch(function (failure) {
        if (error) {
          error.hidden = false;
          error.textContent = failure.message || "Não li esse link.";
        }
      })
      .then(function () {
        if (button) { button.disabled = false; button.textContent = "Puxar dados"; }
      });
  }
  function showToast(message, undo) {
    var toast = document.getElementById("toast");
    if (!toast) return;
    toast.replaceChildren();
    var text = document.createElement("span");
    text.textContent = message;
    toast.appendChild(text);
    if (undo) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "ghost";
      button.textContent = "Desfazer";
      button.addEventListener("click", function () {
        toast.hidden = true;
        undo();
      });
      toast.appendChild(button);
    }
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, undo ? 6000 : 2500);
  }
  function openComposer(mode) {
    var dialog = document.getElementById("composer");
    var form = document.getElementById("composer-form");
    if (!dialog || !form) return;
    document.getElementById("composer-title").textContent = mode === "edit" ? "Editar post" : "Programar um post";
    document.getElementById("composer-submit").textContent = mode === "edit" ? "Salvar" : "Programar";
    form.action = mode === "edit" ? "/hoje/editar" : "/hoje/manual";
    var cover = document.getElementById("field-cover-1");
    if (cover) cover.required = mode !== "edit";
    // Editar mexe no primeiro livro do post. O segundo bloco só existe ao programar.
    var second = document.getElementById("offer-2");
    if (second) second.hidden = mode === "edit";
    ["shop-1", "shop-2", "link-error-1", "link-error-2"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node) node.hidden = true;
    });
    paint();
    dialog.showModal();
  }
  var opener = document.getElementById("open-composer");
  if (opener) {
    opener.addEventListener("click", function () {
      var form = document.getElementById("composer-form");
      if (form) form.reset();
      var hidden = document.getElementById("composer-id");
      if (hidden) hidden.value = "";
      openComposer("new");
    });
  }
  var closer = document.getElementById("close-composer");
  if (closer) closer.addEventListener("click", function () {
    document.getElementById("composer").close();
  });
  var form = document.getElementById("composer-form");
  if (form) form.addEventListener("input", paint);
  var lightCloser = document.getElementById("close-light");
  if (lightCloser) lightCloser.addEventListener("click", function () {
    document.getElementById("lightbox").close();
  });

  document.addEventListener("click", function (event) {
    var pull = event.target.closest(".js-pull");
    if (pull) {
      pullLink(pull.getAttribute("data-alvo") || "-1");
      return;
    }
    var light = event.target.closest(".js-light");
    if (light) {
      var box = document.getElementById("lightbox");
      var image = document.getElementById("light-img");
      image.src = light.getAttribute("data-src");
      image.alt = light.getAttribute("aria-label") || "Capa";
      box.showModal();
      return;
    }
    var copy = event.target.closest(".js-copy");
    if (copy) {
      var url = copy.getAttribute("data-url") || "";
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () {
          showToast("Link copiado");
        }, function () { showToast("Não copiei o link"); });
      }
      return;
    }
    var edit = event.target.closest(".js-edit");
    if (edit) {
      document.getElementById("composer-id").value = edit.getAttribute("data-id") || "";
      document.getElementById("field-clock").value = edit.getAttribute("data-clock") || "";
      document.getElementById("field-title-1").value = edit.getAttribute("data-title") || "";
      document.getElementById("field-blurb-1").value = edit.getAttribute("data-blurb") || "";
      document.getElementById("field-price-1").value = edit.getAttribute("data-price") || "";
      document.getElementById("field-list-1").value = edit.getAttribute("data-list") || "";
      document.getElementById("field-url-1").value = edit.getAttribute("data-url") || "";
      document.getElementById("field-cover-1").value = "";
      openComposer("edit");
      return;
    }
    var remove = event.target.closest(".js-undo-delete");
    if (!remove) return;
    event.preventDefault();
    var parent = remove.closest("form");
    var article = remove.closest("article.post");
    var id = parent.querySelector("[name=id]").value;
    var body = new URLSearchParams(new FormData(parent));
    fetch(parent.action, {
      method: "POST",
      body: body,
      redirect: "manual"
    }).then(function (response) {
      if (!response || (response.status !== 303 && !response.ok)) {
        showToast("Não apaguei o post");
        return;
      }
      if (article) article.remove();
      showToast("Post apagado", function () {
        var back = new URLSearchParams();
        back.set("id", id);
        fetch("/hoje/desfazer", { method: "POST", body: back, redirect: "manual" }).then(function () {
          location.reload();
        });
      });
    });
  });

  document.addEventListener("dragstart", function (event) {
    var handle = event.target.closest(".grip");
    if (!handle) return;
    var row = handle.closest("article.post");
    var queue = document.getElementById("queue");
    if (!row || !queue) return;
    dragged = row;
    dropped = false;
    snapshot = queue.innerHTML;
    document.body.dataset.busy = "1";
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", row.getAttribute("data-id") || "");
  });
  document.addEventListener("dragover", function (event) {
    if (!dragged) return;
    var row = event.target.closest("#queue article.post");
    if (!row || row === dragged) return;
    event.preventDefault();
    var box = row.getBoundingClientRect();
    if (event.clientY > box.top + box.height / 2) row.after(dragged);
    else row.before(dragged);
  });
  document.addEventListener("drop", function (event) {
    if (!dragged) return;
    event.preventDefault();
    dropped = true;
  });
  document.addEventListener("dragend", function () {
    var queue = document.getElementById("queue");
    if (!dropped && queue && snapshot) queue.innerHTML = snapshot;
    var shouldSave = dropped;
    dragged = null;
    dropped = false;
    snapshot = "";
    if (!shouldSave) {
      delete document.body.dataset.busy;
      return;
    }
    var ids = Array.prototype.map.call(document.querySelectorAll("#queue article.post"), function (row) {
      return row.getAttribute("data-id");
    }).filter(Boolean);
    var body = new URLSearchParams();
    ids.forEach(function (id) { body.append("id", id); });
    fetch("/hoje/reordenar", { method: "POST", body: body, redirect: "manual" }).then(function () {
      location.reload();
    });
  });

  var tipButton = document.querySelector(".tip button");
  if (tipButton) tipButton.addEventListener("click", function () {
    var open = tipButton.getAttribute("aria-expanded") === "true";
    tipButton.setAttribute("aria-expanded", open ? "false" : "true");
  });

  var search = document.getElementById("q");
  function applySearch() {
    if (!search || !rows) return;
    var query = search.value.trim().toLocaleLowerCase("pt-BR");
    var found = 0;
    Array.prototype.forEach.call(rows.querySelectorAll("article.post"), function (row) {
      var title = (row.getAttribute("data-title") || "").toLocaleLowerCase("pt-BR");
      var hide = query && title.indexOf(query) === -1;
      row.hidden = hide;
      if (!hide) found += 1;
    });
    var note = document.getElementById("search-empty");
    if (query && found === 0) {
      if (!note) {
        note = document.createElement("p");
        note.id = "search-empty";
        note.className = "empty-state";
        note.textContent = "Nenhum post com esse título.";
        rows.appendChild(note);
      }
      note.hidden = false;
    } else if (note) {
      note.hidden = true;
    }
  }
  if (search) search.addEventListener("input", applySearch);

  function fill(id, html) {
    var node = document.getElementById(id);
    if (!node || node.contains(document.activeElement)) return;
    node.innerHTML = html;
  }
  function refresh() {
    if (document.body.dataset.busy === "1") return;
    var dialog = document.getElementById("composer");
    if (dialog && dialog.open) return;
    var aba = new URLSearchParams(location.search).get("aba") || "todas";
    document.body.classList.add("is-loading");
    if (rows && !rows.querySelector("article.post")) {
      rows.innerHTML = '<div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>';
    }
    fetch("/hoje/parcial?aba=" + encodeURIComponent(aba), { headers: { "Accept": "application/json" } })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) return;
        ["pills", "toggle", "funnel", "dayline", "warn", "tabs", "rows", "hours", "bands", "members", "groups", "grid", "invites"].forEach(function (id) {
          if (typeof data[id] === "string") fill(id, data[id]);
        });
        applySearch();
      })
      .catch(function () {})
      .then(function () { document.body.classList.remove("is-loading"); });
  }
  window.hojeRefresh = refresh;
  window.hojeToast = showToast;
  fetch("/hoje/checar", { method: "POST", body: "", redirect: "manual" }).catch(function () {});
  setTimeout(refresh, 6000);
  setInterval(refresh, 30000);
})();
"""
