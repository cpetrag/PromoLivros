from __future__ import annotations

from html import escape

from promo_livros.day_view import NO_BOOK, DayView
from promo_livros.groups_file import GroupChoice

_NAV = """
<nav>
  <a href="/hoje">Hoje</a>
  <a href="/whatsapp">WhatsApp</a>
  <a href="/grupos">Grupos</a>
  <form method="post" action="/logout"><button type="submit">Sair</button></form>
</nav>
"""


def login_page(*, failed: bool) -> str:
    message = "<p>Usuário ou senha incorretos.</p>" if failed else ""
    return _page(
        "Entrar",
        f"""
        <h1>Promo Livros</h1>
        {message}
        <form method="post" action="/login">
          <label>Usuário <input name="username" autocomplete="username"></label>
          <label>Senha <input name="password" type="password" autocomplete="current-password"></label>
          <button type="submit">Entrar</button>
        </form>
        """,
        nav=False,
    )


def render_today(*, day: str, view: DayView | None, error: str | None) -> str:
    if error:
        body = f"<p>{escape(error)}</p>"
    elif view is None:
        body = "<p>A fila de hoje ainda não existe.</p>"
    else:
        blocks = []
        for book in view.books:
            if book.book_status == NO_BOOK:
                blocks.append(f"<section><h2>{escape(book.clock)} {escape(book.niche_label)}</h2><p>sem livro</p></section>")
                continue
            reserve = " · reserva" if book.reserve else ""
            clock = f"{escape(book.clock)} " if book.clock else ""
            groups = "".join(
                f"<li>{escape(group.name)} · {escape(group.status_label)}</li>"
                for group in book.groups
            )
            blocks.append(
                f"""
                <section>
                  <h2>{clock}{escape(book.niche_label)}{reserve}</h2>
                  <p>{escape(book.title)} · {escape(book.price_label)} · {escape(book.book_status)}</p>
                  <ul>{groups}</ul>
                  <pre>{escape(book.caption)}</pre>
                </section>
                """
            )
        body = f"<h1>{escape(day)}</h1>" + "".join(blocks)
    return _page("Hoje", body, nav=True)


def render_whatsapp(*, state: str, message: str | None) -> str:
    if message:
        body = f"<p>{escape(message)}</p>"
    elif state == "connected":
        body = "<p>Conectado.</p><p>Sessão promo-livros.</p>"
    elif state == "qr":
        body = '<p>Escaneie o QR para parear.</p><img alt="QR do WhatsApp" src="/whatsapp/qr">'
    else:
        body = "<p>Desconectado.</p>"
    return _page("WhatsApp", "<h1>WhatsApp</h1>" + body, nav=True)


def render_groups(choices: list[GroupChoice], *, connected: bool, notice: str | None) -> str:
    note = f"<p>{escape(notice)}</p>" if notice else ""
    if not connected:
        saved = "".join(f"<li>{escape(choice.name)}</li>" for choice in choices if choice.checked)
        body = note + "<p>Conecte o WhatsApp para ver a lista.</p><ul>" + saved + "</ul>"
        return _page("Grupos", "<h1>Grupos</h1>" + body, nav=True)
    rows = []
    for choice in choices:
        checked = " checked" if choice.checked else ""
        missing = " · fora da sessão" if choice.missing else ""
        rows.append(
            f"""
            <label>
              <input type="checkbox" name="chat_id" value="{escape(choice.chat_id)}"{checked}>
              {escape(choice.name)}{missing}
            </label>
            """
        )
    body = note + f"""
      <form method="post" action="/grupos">
        {''.join(rows)}
        <button type="submit">Salvar</button>
      </form>
      <p>O relógio do bot só lê a lista nova quando o processo subir de novo.</p>
    """
    return _page("Grupos", "<h1>Grupos</h1>" + body, nav=True)


def _page(title: str, body: str, *, nav: bool) -> str:
    navigation = _NAV if nav else ""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>{escape(title)}</title></head>
<body>
{navigation}
{body}
</body>
</html>
"""
