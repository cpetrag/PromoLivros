from __future__ import annotations

from html import escape

from promo_livros.day_view import NO_BOOK, DayView
from promo_livros.groups_file import GroupChoice

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
_OK = {"enviada", "publicado", "pronto"}
_BAD = {"falhou", "expirada", "pulado"}
_WAIT = {"enviando", "na fila"}

def _nav(current: str) -> str:
    links = []
    for label, href in (
        ("Hoje", "/hoje"),
        ("Enviados", "/enviados"),
        ("WhatsApp", "/whatsapp"),
        ("Grupos", "/grupos"),
        ("Assinaturas", "/assinaturas"),
        ("Configurações", "/configuracoes"),
        ("Curadoria", "/curadoria"),
    ):
        current_attr = ' aria-current="page"' if label == current else ""
        links.append(f'<a href="{href}"{current_attr}>{label}</a>')
    return f"""
<header class="top">
  <a class="brand" href="/hoje">Promo Livros</a>
  <nav>
    {''.join(links)}
  </nav>
  <button class="ghost theme" type="button" id="theme-toggle" aria-label="Alternar tema">◐</button>
  <form method="post" action="/logout"><button class="ghost" type="submit">Sair</button></form>
</header>
"""


def login_page(*, failed: bool) -> str:
    message = '<p class="alert" role="alert">Usuário ou senha incorretos.</p>' if failed else ""
    return _page(
        "Entrar",
        f"""
        <main class="gate">
          <h1>Promo Livros</h1>
          <p class="lede">Fila, sessão e grupos.</p>
          {message}
          <form method="post" action="/login">
            <label>Usuário <input name="username" autocomplete="username" required></label>
            <label>Senha <input name="password" type="password" autocomplete="current-password" required></label>
            <button type="submit">Entrar</button>
          </form>
        </main>
        """,
        nav=False,
    )


def render_today(*, day: str, view: DayView | None, error: str | None) -> str:
    if error:
        body = f'<p class="alert" role="alert">{escape(error)}</p>'
    elif view is None:
        body = """
        <section class="empty">
          <h1>Hoje</h1>
          <p>A fila de hoje ainda não existe.</p>
          <p class="muted">Ela entra quando você marca os livros em Curadoria.</p>
        </section>
        """
    else:
        blocks = []
        for book in view.books:
            if book.book_status == NO_BOOK:
                blocks.append(
                    f"""
                    <article class="slot empty">
                      <time>{escape(book.clock)}</time>
                      <div>
                        <p class="meta">{escape(book.niche_label)}</p>
                        <p>sem livro</p>
                      </div>
                    </article>
                    """
                )
                continue
            clock = f"<time>{escape(book.clock)}</time>" if book.clock else "<time>Reserva</time>"
            groups = "".join(
                f"<li><span>{escape(group.name)}</span> {_pill(group.status_label)}</li>"
                for group in book.groups
            )
            caption = ""
            if book.caption:
                caption = f"<details><summary>Mensagem</summary><pre>{escape(book.caption)}</pre></details>"
            blocks.append(
                f"""
                <article class="slot{' reserve' if book.reserve else ''}">
                  {clock}
                  <div>
                    <p class="meta">{escape(book.niche_label)} {_pill(book.book_status)}</p>
                    <h2>{escape(book.title)}</h2>
                    <p class="price">{escape(book.price_label)}</p>
                    <ul class="groups">{groups}</ul>
                    {caption}
                  </div>
                </article>
                """
            )
        body = f"<h1>{escape(_day_title(day))}</h1><div class=\"slots\">{''.join(blocks)}</div>"
    return _page("Hoje", f"<main>{body}</main>", nav=True)



def render_board(
    day: str,
    posts: list,
    *,
    notice: str | None,
    sending: bool,
    schedule,
    groups: tuple[str, ...] = (),
    aba: str = "todas",
    now=None,
    whatsapp: str = "unknown",
    paused_until: str = "",
    members=None,
) -> str:
    from promo_livros.dashboard_belt import BELT_CSS, BELT_JS, page_body

    body = page_body(
        day,
        posts,
        notice=notice,
        sending=sending,
        schedule=schedule,
        groups=groups,
        aba=aba,
        now=now,
        whatsapp=whatsapp,
        paused_until=paused_until,
        members=members,
    )
    return _page(
        "Hoje",
        body,
        nav=False,
        body_class="belt-page",
        extra_style=BELT_CSS,
        extra_script=BELT_JS,
    )


def _send_form(schedule) -> str:
    from promo_livros.send_schedule import slot_clocks

    slots = slot_clocks(schedule)
    span = f"{slots[0]} às {slots[-1]}" if slots else "nenhum horário"
    return f"""
    <details class="manual" open>
      <summary>Intervalos de envio</summary>
      <form method="post" action="/envio/regras">
        <label>Primeiro post <input name="start" required value="{escape(schedule.start)}" pattern="[0-2][0-9]:[0-5][0-9]"></label>
        <label>Parar antes de <input name="end" required value="{escape(schedule.end)}" pattern="[0-2][0-9]:[0-5][0-9]"></label>
        <label>Minutos entre posts <input name="interval" type="number" min="5" max="180" required value="{schedule.post_interval_minutes}"></label>
        <label>Segundos entre grupos <input name="gap" type="number" min="5" max="600" required value="{schedule.group_gap_seconds}"></label>
        <button type="submit">Salvar intervalos</button>
      </form>
      <p class="muted">Com estes números cabem {len(slots)} posts, de {escape(span)}. Entre um grupo e o próximo, {schedule.group_gap_seconds} segundos. Salvar não muda o horário dos posts que já estão na fila de hoje.</p>
      <form method="post" action="/hoje/reorganizar">
        <button class="ghost" type="submit">Reorganizar o que resta</button>
      </form>
      <p class="muted">Põe os posts que ainda não saíram nos horários da grade que ainda não passaram, na ordem atual. Os que não couberem antes do fim ficam depois dele.</p>
    </details>
    """


def render_sent(lines: list[tuple[str, str, str]]) -> str:
    if not lines:
        body = """
        <h1>Enviados</h1>
        <p>Nenhum post enviado ainda.</p>
        """
    else:
        items = "".join(
            f"<article class=\"slot\"><time>{escape(when)}</time><div><h2>{escape(title)}</h2><p class=\"muted\">{escape(detail)}</p></div></article>"
            for when, title, detail in lines
        )
        body = f"<h1>Enviados</h1><div class=\"slots\">{items}</div>"
    return _page("Enviados", f"<main>{body}</main>", nav=True)


def render_whatsapp(*, state: str, message: str | None, sending: bool = False, schedule=None) -> str:
    alert = f'<p class="alert" role="alert">{escape(message)}</p>' if message else ""
    refresh = None
    if state == "connected":
        panel = """
        <section class="panel">
          <p class="state ok">Conectado.</p>
          <p>Sessão promo-livros. Os grupos salvos continuam valendo.</p>
        </section>
        """
    elif state == "qr" and not message:
        refresh = 12
        panel = """
        <section class="panel">
          <p>Escaneie o QR no WhatsApp do celular: Aparelhos conectados, Conectar aparelho.</p>
          <div class="qr"><img alt="QR do WhatsApp" src="/whatsapp/qr"></div>
          <p class="muted">A página atualiza sozinha. Quando parear, aparece Conectado.</p>
        </section>
        """
    elif state == "qr":
        refresh = 4
        panel = """
        <section class="panel">
          <p class="muted">Tentando de novo.</p>
        </section>
        """
    elif state == "starting":
        refresh = 4
        panel = """
        <section class="panel">
          <p>Abrindo a sessão. O QR aparece em alguns segundos.</p>
        </section>
        """
    else:
        panel = """
        <section class="panel">
          <p class="state bad">Desconectado.</p>
          <p class="muted">A sessão promo-livros parou. Gerar o QR só abre o pareamento.</p>
          <form method="post" action="/whatsapp/parear">
            <button type="submit">Gerar QR</button>
          </form>
        </section>
        """
    send = "Envio da fila nova: ligado." if sending else "Envio da fila nova: desligado. Parear não publica."
    toggle = "0" if sending else "1"
    label = "Desligar envio" if sending else "Ligar envio"
    body = f"""
    {alert}
    {panel}
    {_send_form(schedule) if schedule is not None else ""}
    <section class="panel">
      <p>{escape(send)}</p>
      <form method="post" action="/whatsapp/envio">
        <input type="hidden" name="enabled" value="{toggle}">
        <button class="ghost" type="submit">{label}</button>
      </form>
    </section>
    """
    return _page("WhatsApp", f"<main><h1>WhatsApp</h1>{body}</main>", nav=True, refresh=refresh)


def render_signatures(block: str, *, saved: bool, count: int) -> str:
    notice = ""
    if saved and count:
        word = "assinatura pronta" if count == 1 else "assinaturas prontas"
        notice = f'<p class="lede" role="status">{count} {word}. O próximo envio usa a seguinte da lista.</p>'
    elif saved:
        notice = '<p class="lede" role="status">Lista vazia. O envio volta às assinaturas padrão.</p>'
    body = f"""
    <h1>Assinaturas</h1>
    <p class="lede">Um bloco só. Separe cada assinatura com |. Na hora de enviar, o post usa a próxima da lista. Os grupos daquele post recebem o mesmo texto.</p>
    {notice}
    <form method="post" action="/assinaturas">
      <label>Textos
        <textarea name="bloco" rows="12" placeholder="Livros com até 60% off: https://link.amazon/... | Kindle Unlimited com 3 meses grátis: https://link.amazon/...">{escape(block)}</textarea>
      </label>
      <button type="submit">Salvar</button>
    </form>
    """
    return _page("Assinaturas", f"<main class=\"panel\">{body}</main>", nav=True)


def render_settings(cookies: str, tag: str, *, saved: bool, ready: bool, notice: str | None) -> str:
    status = ""
    if notice:
        status = f'<p class="alert" role="status">{escape(notice)}</p>'
    elif saved and ready:
        status = '<p class="lede" role="status">Cookies salvos. A sessão do Mercado Livre está pronta.</p>'
    elif saved:
        status = '<p class="alert" role="status">Salvei, mas não achei o cookie _csrf. Exporte de novo, logado no Mercado Livre.</p>'
    elif cookies and ready:
        status = '<p class="lede">Sessão do Mercado Livre pronta.</p>'
    elif cookies:
        status = '<p class="alert" role="status">Esse texto não tem o cookie _csrf.</p>'
    body = f"""
    <h1>Configurações</h1>
    <p class="lede">A conversão de link do Mercado Livre usa a sessão do navegador. No Cookie-Editor, exporte os cookies do Mercado Livre em JSON ou como Header String e cole abaixo.</p>
    {status}
    <form method="post" action="/configuracoes">
      <label>Cookies do Mercado Livre
        <textarea name="cookies" rows="12" spellcheck="false" autocomplete="off" placeholder="[{{&quot;name&quot;:&quot;_csrf&quot;,&quot;value&quot;:&quot;...&quot;,&quot;domain&quot;:&quot;.mercadolivre.com.br&quot;}}]">{escape(cookies)}</textarea>
      </label>
      <label>Tag de afiliado
        <input name="tag" value="{escape(tag)}" autocomplete="off" spellcheck="false">
      </label>
      <button type="submit">Salvar</button>
    </form>
    """
    return _page("Configurações", f"<main class=\"panel\">{body}</main>", nav=True)


def render_groups(choices: list[GroupChoice], *, connected: bool, notice: str | None) -> str:
    note = f'<p class="alert" role="status">{escape(notice)}</p>' if notice else ""
    if not connected:
        saved = "".join(f"<li>{escape(choice.name)}</li>" for choice in choices if choice.checked)
        saved_block = f"<ul class=\"saved\">{saved}</ul>" if saved else ""
        body = note + "<p>Conecte o WhatsApp para ver a lista.</p>" + saved_block
        return _page("Grupos", f"<main><h1>Grupos</h1>{body}</main>", nav=True)
    rows = []
    for choice in choices:
        checked = " checked" if choice.checked else ""
        missing = '<span class="pill neutral">fora da sessão</span>' if choice.missing else ""
        rows.append(
            f"""
            <label class="choice">
              <input type="checkbox" name="chat_id" value="{escape(choice.chat_id)}"{checked}>
              <span>{escape(choice.name)}</span>
              {missing}
            </label>
            """
        )
    body = note + f"""
      <form method="post" action="/grupos">
        <div class="choices">{''.join(rows)}</div>
        <button type="submit">Salvar</button>
      </form>
      <p class="muted">O relógio do bot só lê a lista nova quando o processo subir de novo.</p>
    """
    return _page("Grupos", f"<main><h1>Grupos</h1>{body}</main>", nav=True)


def _day_title(day: str) -> str:
    parts = day.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return day
    year, month, number = (int(part) for part in parts)
    if not 1 <= month <= 12:
        return day
    return f"{number} de {_MONTHS[month - 1]} de {year}"


def _pill(label: str) -> str:
    if label in _OK:
        kind = "ok"
    elif label in _BAD:
        kind = "bad"
    elif label in _WAIT:
        kind = "wait"
    else:
        kind = "neutral"
    return f'<span class="pill {kind}">{escape(label)}</span>'


def _page(
    title: str,
    body: str,
    *,
    nav: bool,
    refresh: int | None = None,
    body_class: str = "",
    extra_style: str = "",
    extra_script: str = "",
) -> str:
    navigation = _nav(title) if nav else ""
    current = escape(title)
    refresh_tag = f'<meta http-equiv="refresh" content="{int(refresh)}">' if refresh else ""
    klass = f' class="{escape(body_class)}"' if body_class else ""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{refresh_tag}
<title>{current}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<script>
try {{
  if (localStorage.getItem("promo-theme") === "dark") document.documentElement.setAttribute("data-theme", "dark");
}} catch (e) {{}}
</script>
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
  color-scheme: light;
  --bg: #EEF1F4;
  --surface: #FFFFFF;
  --card: #FFFFFF;
  --ink: #1B1F24;
  --muted: #6B7480;
  --line: #E3E7EC;
  --accent: #1B1F24;
  --accent-ink: #FFFFFF;
  --ok: #1F8A5B;
  --wait: #C98A12;
  --bad: #C0392B;
  --blue: #2F6FDB;
  --green: #1F8A5B;
  --amber: #C98A12;
  --red: #C0392B;
  --focus: #2F6FDB;
  --pill: #1B1F24;
  --pill-ink: #FFFFFF;
  --chip-green: #E3F3EA;
  --chip-green-ink: #14643F;
  font-family: Inter, "Segoe UI", sans-serif;
}}
html[data-theme="dark"] {{
  color-scheme: dark;
  --bg: #12161b;
  --surface: #1b2129;
  --card: #1b2129;
  --ink: #f3f5f7;
  --muted: #a3acb8;
  --line: #2d3540;
  --accent: #f3f5f7;
  --accent-ink: #12161b;
  --ok: #3dbe7a;
  --wait: #e0b15a;
  --bad: #f07167;
  --blue: #7eabf5;
  --green: #3dbe7a;
  --amber: #e0b15a;
  --red: #f07167;
  --focus: #7eabf5;
  --pill: #f3f5f7;
  --pill-ink: #12161b;
  --chip-green: #173528;
  --chip-green-ink: #8fd4ae;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  line-height: 1.45;
}}
body > header, body > main {{
  width: min(46rem, calc(100% - 2rem));
  margin-inline: auto;
}}
.top {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem 1rem;
  padding: 1.1rem 0 0.4rem;
}}
.brand {{
  color: var(--ink);
  font-weight: 700;
  font-size: 1.15rem;
  text-decoration: none;
}}
nav {{ display: flex; flex-wrap: wrap; gap: 0.25rem; }}
nav a {{
  color: var(--muted);
  text-decoration: none;
  font-weight: 600;
  padding: 0.4rem 0.75rem;
  border-radius: 999px;
}}
nav a:hover {{ color: var(--ink); background: var(--surface); }}
nav a[aria-current="page"] {{ color: var(--accent-ink); background: var(--accent); }}
.top form {{ margin-left: auto; }}
h1 {{
  font-size: 1.75rem;
  line-height: 1.2;
  font-weight: 700;
  margin: 1.25rem 0 1rem;
  text-wrap: balance;
}}
h2 {{
  font-size: 1.2rem;
  line-height: 1.3;
  font-weight: 600;
  margin: 0.15rem 0 0.2rem;
  text-wrap: balance;
}}
p {{ margin: 0.35rem 0; }}
.lede, .muted {{ color: var(--muted); }}
.alert {{
  background: #FDECEA;
  color: #7d241c;
  border: 1px solid #f3c7c2;
  border-radius: 10px;
  padding: 0.75rem 0.9rem;
  margin: 0.75rem 0;
}}
html[data-theme="dark"] .alert {{
  background: #3a2220;
  color: #f6d2ce;
  border-color: #6b3330;
}}
button, .ghost {{
  font: inherit;
  font-weight: 600;
  min-height: 2.75rem;
  padding: 0.45rem 1rem;
  border-radius: 999px;
  cursor: pointer;
}}
button {{
  background: var(--accent);
  color: var(--accent-ink);
  border: 0;
}}
button:hover {{ filter: brightness(1.06); }}
.ghost {{
  background: transparent;
  color: var(--ink);
  border: 1px solid var(--line);
}}
button.theme {{
  font-family: "Segoe UI Symbol", "Segoe UI", sans-serif;
  width: 40px;
  min-width: 40px;
  padding: 0;
  font-size: 1.15rem;
  line-height: 1;
}}
button:focus-visible, a:focus-visible, input:focus-visible, summary:focus-visible {{
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}}
label {{ display: grid; gap: 0.35rem; font-weight: 600; margin-bottom: 0.85rem; }}
textarea {{
  font: inherit;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  min-height: 12rem;
  padding: 0.75rem;
  width: 100%;
  resize: vertical;
}}
input[type="text"], input:not([type]), input[type="password"] {{
  font: inherit;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  min-height: 2.75rem;
  padding: 0.45rem 0.75rem;
  width: 100%;
}}
.gate {{
  width: min(24rem, calc(100% - 2rem));
  margin: 12vh auto 2rem;
}}
.gate form {{ margin-top: 1.25rem; }}
.gate button {{ width: 100%; }}
.slots {{ display: grid; gap: 0.65rem; }}
.slot {{
  display: grid;
  grid-template-columns: 4.5rem 1fr;
  gap: 0.85rem;
  background: var(--surface);
  border-radius: 12px;
  padding: 0.9rem 1rem;
}}
.slot.empty {{ color: var(--muted); }}
time {{
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  font-size: 1.05rem;
  padding-top: 0.1rem;
}}
.meta {{ display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; color: var(--muted); margin: 0; }}
.price {{ font-weight: 600; }}
.pill {{
  display: inline-block;
  font-size: 0.82rem;
  font-weight: 600;
  line-height: 1.2;
  padding: 0.15rem 0.45rem;
  border-radius: 999px;
  background: oklch(0.32 0.02 250);
  color: var(--ink);
}}
.pill.ok {{ background: oklch(0.32 0.06 155); color: var(--ok); }}
.pill.wait {{ background: oklch(0.38 0.08 85); color: oklch(0.94 0.08 95); }}
.pill.bad {{ background: oklch(0.32 0.06 25); color: var(--bad); }}
.groups {{ list-style: none; padding: 0; margin: 0.55rem 0 0; display: grid; gap: 0.35rem; }}
.groups li {{ display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }}
details {{ margin-top: 0.65rem; }}
summary {{ cursor: pointer; font-weight: 600; color: var(--muted); }}
pre {{
  white-space: pre-wrap;
  font: inherit;
  background: var(--bg);
  border-radius: 10px;
  padding: 0.75rem;
  margin: 0.45rem 0 0;
}}
.panel {{ max-width: 28rem; }}
.state {{ font-size: 1.35rem; font-weight: 700; margin: 0 0 0.25rem; }}
.state.ok {{ color: var(--ok); }}
.state.bad {{ color: var(--bad); }}
.qr {{
  display: inline-block;
  background: white;
  padding: 0.75rem;
  border-radius: 12px;
  margin-top: 0.75rem;
}}
.qr img {{ display: block; width: min(16rem, 100%); height: auto; }}
.choices {{ display: grid; gap: 0.45rem; margin-bottom: 1rem; }}
.choice {{
  display: flex;
  align-items: center;
  gap: 0.65rem;
  background: var(--surface);
  border-radius: 12px;
  min-height: 3rem;
  padding: 0.55rem 0.8rem;
  margin: 0;
}}
.choice input {{ width: 1.15rem; height: 1.15rem; accent-color: var(--accent); }}
.saved {{ padding-left: 1.1rem; }}
.card {{
  display: block;
  width: min(28rem, 100%);
  height: auto;
  border-radius: 12px;
  margin: 0.35rem 0 0.65rem;
  background: var(--bg);
}}
.actions {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.65rem; }}
.actions form {{ margin: 0; }}
.actions button {{ min-height: 2.4rem; }}
.manual {{
  background: var(--surface);
  border-radius: 12px;
  padding: 0.85rem 1rem;
  margin-bottom: 0.9rem;
}}
.manual form {{ margin-top: 0.8rem; }}
fieldset {{
  border: 1px solid var(--line);
  border-radius: 12px;
  margin: 0 0 0.8rem;
  padding: 0.7rem 0.8rem 0.2rem;
}}
legend {{ font-weight: 700; padding: 0 0.3rem; }}
.empty p:first-of-type {{ font-size: 1.05rem; }}
@media (max-width: 640px) {{
  .slot {{ grid-template-columns: 1fr; gap: 0.2rem; }}
  .top form {{ margin-left: 0; }}
}}
body.belt-page > .shell {{
  width: min(1180px, calc(100% - 32px));
  margin-inline: auto;
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ scroll-behavior: auto; }}
  button:hover {{ filter: none; }}
}}
{extra_style}
</style>
</head>
<body{klass}>
{navigation}
{body}
<script>
(function () {{
  var button = document.getElementById("theme-toggle");
  if (!button) return;
  button.addEventListener("click", function () {{
    var dark = document.documentElement.getAttribute("data-theme") === "dark";
    if (dark) {{
      document.documentElement.removeAttribute("data-theme");
      try {{ localStorage.setItem("promo-theme", "light"); }} catch (e) {{}}
    }} else {{
      document.documentElement.setAttribute("data-theme", "dark");
      try {{ localStorage.setItem("promo-theme", "dark"); }} catch (e) {{}}
    }}
  }});
}})();
</script>
<script>
{extra_script}
</script>
</body>
</html>

"""
