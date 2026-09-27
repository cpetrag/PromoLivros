# -*- coding: utf-8 -*-
"""One-off builder for the static curation page."""
from pathlib import Path

TAG = "souleitor-20"
BOOKS = [
    ("8506087163", "Rita, não grita!", "Muniz, Flávia", 2461, 1898, 4.7, 3207, "81QpGCWeECL.jpg"),
    ("6556172766", "Amiguinhos Recortados II: Pintinho", "Mammoth World", 365, 283, 4.8, 1669, "51-Hbf6TFaL.jpg"),
    ("6550974119", "Memórias do subsolo", "Dostoiévski, Fiódor", 1720, 1112, 4.6, 1322, "71+9comic0L.jpg"),
    ("6561260643", "Bluey Maletinha Divertida", "On Line Editora", 2532, 1979, 4.8, 431, "61FqicKCnIL.jpg"),
    ("6556177059", "Agite e Rodopie! Um Livro com alça: Olá, Safari", "Todolivro", 573, 451, 4.7, 269, "61Ef2mtnWPL.jpg"),
    ("6526107249", "365 cruzadas diretas", "Ciranda Cultural", 1656, 980, 4.7, 2633, "71ek2W1d6zL.jpg"),
    ("8537645362", "Meu Livro Para Tocar e Sentir: Selva", "Brijbasi Art Press Ltd", 1883, 1021, 4.7, 244, "61SfDrMjddL.jpg"),
    ("6556172758", "Amiguinhos Recortados II: Gatinho", "Mammoth World", 380, 243, 4.8, 393, "51UjN1eGBEL.jpg"),
    ("8584395970", "Todas as mentiras", "Abby, S. T.", 3439, 2732, 4.8, 558, "81E-zm-vk3L.jpg"),
    ("6558887592", "Manual de Epicteto", "Epicteto", 1685, 822, 4.7, 268, "81my0y+r-UL.jpg"),
    ("6559576582", "Criaturas impossíveis, vol. 1", "Rundell, Katherine", 3035, 2099, 4.6, 441, "81UdXtczovL.jpg"),
    ("6554481133", "O Eternauta (edição definitiva)", "Oesterheld, Héctor", 17439, 13100, 4.9, 876, "91CcGtXOUmL.jpg"),
    ("652593026X", "Gokurakugai 02", "Sano, Yuuto", 2480, 1596, 4.8, 243, "61Sx8b8ZjbL.jpg"),
    ("6558384434", "Deixe ir", "Carpinejar", 3504, 2176, 4.7, 725, "61XnnPZvQeL.jpg"),
    ("6555478357", "Bluey: Vovozinhas", "On Line Editora", 1715, 1281, 4.7, 288, "71wlr+YHQ+L.jpg"),
    ("8573892900", "Ressurreição de Jesus", "Marques, Cristina", 193, 147, 4.9, 303, "61u37T-QX7L.jpg"),
    ("6525930286", "Dragon Ball Super, vol. 23", "Toriyama, Akira", 2997, 1894, 4.9, 248, "71NbtM8b+6L.jpg"),
    ("8573988169", "Bíblia ilustrada da família", "Hicks, J Emmerson", 7082, 5526, 4.9, 512, "61LdbS7pPGL.jpg"),
    ("8542224620", "A filha da rainha sereia", "Levenseller, Tricia", 3968, 2395, 4.7, 376, "81+MrQAUgSL.jpg"),
    ("8545716532", "Cavaleiros do Zodíaco, vol. 08", "Kurumada, Masami", 4562, 3589, 5.0, 119, "91VdouS5UrL.jpg"),
    ("8543223490", "Patrulha Canina: prancheta para colorir", "On Line Editora", 1627, 1258, 4.7, 591, "91TSOrxj3fL.jpg"),
    ("6554482318", "Tartarugas Ninja, vol. 2", "Waltz, Tom", 14138, 10963, 4.9, 222, "71vj4PGHGNL.jpg"),
    ("6558022672", "Por que a esquerda morreu?", "Souza, Jessé", 3404, 2572, 4.8, 122, "81827YLsR+L.jpg"),
    ("6583127628", "Belo veneno", "Kent, Rina", 4788, 3759, 4.6, 144, "91qCRqPVFzL.jpg"),
    ("8537659819", "333 atividades… meninos", "Little Pearl Books", 1350, 939, 4.8, 503, "61sG0X0uU1L.jpg"),
    ("6559817458", "Sea Spinner, vol. 2 (com brindes)", "Johnson, Julia", 11556, 8208, 4.7, 202, "61klIUsuU0L.jpg"),
    ("6559817342", "Sea Spinner, vol. 2", "Johnson, Julie", 7454, 5550, 4.7, 202, "91M02mm1bQL.jpg"),
    ("656102186X", "Clássicos Disney: Os miseráveis", "Culturama", 1827, 1424, 4.7, 115, "61Q8tOebX1L.jpg"),
    ("6558384221", "Irmandade mortal", "Robb, J. D.", 7271, 5689, 4.8, 351, "715Wblpa7VL.jpg"),
    ("8573989149", "Aprenda em casa: adição", "Todolivro", 379, 269, 4.7, 702, "61+Hp7aAtCL.jpg"),
    ("6559579239", "O livro de ouro das copas 2026", "Vellozo Ribas, Lycio", 5758, 3389, 4.8, 110, "81Xm2wcLyBL.jpg"),
    ("6553100195", "Como fazer amigos e influenciar pessoas", "Carnegie, Dale", 3619, 2730, 4.7, 292, "61TQzcLmgHL.jpg"),
    ("6556700665", "Cezar", "Greco, Alessandro", 5048, 3952, 4.6, 116, "81x5I-qqKtL.jpg"),
    ("6556890731", "A abolição do homem", "C. S. Lewis", 3721, 2299, 4.8, 5656, "61JjDRbV8XL.jpg"),
]


def discount(avg90: int, price: int) -> float:
    return round(((avg90 - price) * 1000) / avg90) / 10


def brl(cents: int) -> str:
    whole, frac = divmod(cents, 100)
    grouped = f"{whole:,}".replace(",", ".")
    return f"R$ {grouped},{frac:02d}"


def pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "%"


def cover_url(filename: str) -> str:
    return "https://m.media-amazon.com/images/I/" + filename.replace("+", "%2B")


def amazon_url(asin: str) -> str:
    return f"https://www.amazon.com.br/dp/{asin}?tag={TAG}"


# Ordem do log: a busca da Amazon veio ordenada pelo ranking de vendas.
# Menor ranking = a Amazon vende mais. O corte extra é mais de 2000 avaliações.
ranked = [book for book in BOOKS if book[6] > 2000]
medio = round(sum(discount(book[3], book[4]) for book in ranked) / len(ranked), 1)

cards = []
for index, (asin, title, author, avg90, price, rating, reviews, image) in enumerate(ranked):
    cut = discount(avg90, price)
    search = f"{title} {author}".lower()
    badge = '<p class="badge">A Amazon vende mais este</p>' if index == 0 else ""
    cards.append(
        f"""<article class="book" data-book data-discount="{cut}" data-rating="{rating}" data-search="{search}">
        <a class="cover" href="{amazon_url(asin)}"><img src="{cover_url(image)}" alt="Capa de {title}" width="160" height="240"></a>
        <div>
          <h3><a href="{amazon_url(asin)}">{title}</a></h3>
          <p class="author">{author}</p>
          <p class="price"><s>{brl(avg90)}</s> <strong>{brl(price)}</strong> <span class="off">{pct(cut)}</span></p>
          <p class="meta">Nota {str(rating).replace('.', ',')} · {reviews:,} avaliações</p>
        </div>
      </article>""".replace(",", ".")
        if False
        else f"""<article class="book" data-book data-discount="{cut}" data-rating="{rating}" data-search="{search}">
        <a class="cover" href="{amazon_url(asin)}"><img src="{cover_url(image)}" alt="Capa de {title}" width="160" height="240"></a>
        <div>
          {badge}
          <h3><a href="{amazon_url(asin)}">{title}</a></h3>
          <p class="author">{author}</p>
          <p class="price"><s>{brl(avg90)}</s> <strong>{brl(price)}</strong> <span class="off">{pct(cut)}</span></p>
          <p class="meta">Nota {str(rating).replace('.', ',')} · {f'{reviews:,}'.replace(',', '.')} avaliações</p>
        </div>
      </article>"""
    )

html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Promo Livros — curadoria</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,560;9..144,680&family=Hanken+Grotesk:wght@420;560;680&display=swap" rel="stylesheet">
  <style>
    :root {{
      --paper: #f3ecdf;
      --ink: #1c1712;
      --muted: #6d6256;
      --line: #e2d5c3;
      --card: #fffaf3;
      --sale: #9f2d1f;
      --ok: #1f6b45;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--paper);
      font-family: "Hanken Grotesk", sans-serif;
      font-size: 16px;
      line-height: 1.45;
    }}
    main {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 72px; }}
    header {{ display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 28px; }}
    .mark {{ font-size: 13px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--sale); font-weight: 680; }}
    h1 {{ font-family: Fraunces, serif; font-weight: 560; font-size: clamp(40px, 6vw, 68px); line-height: 0.92; margin: 8px 0 0; letter-spacing: -0.03em; }}
    h2 {{ font-family: Fraunces, serif; font-size: 28px; font-weight: 560; margin: 0 0 16px; }}
    .lede {{ max-width: 36ch; color: var(--muted); margin: 0; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 32px; }}
    .stat {{ background: var(--card); border: 1px solid var(--line); padding: 16px 18px; }}
    .stat b {{ display: block; font-family: Fraunces, serif; font-size: 34px; font-weight: 560; letter-spacing: -0.03em; }}
    .stat span {{ color: var(--muted); font-size: 13px; }}
    .tools {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 16px; }}
    button, input {{ font: inherit; }}
    button {{ border: 1px solid var(--line); background: transparent; padding: 8px 12px; cursor: pointer; color: var(--ink); }}
    button[aria-pressed="true"] {{ background: var(--ink); color: var(--paper); border-color: var(--ink); }}
    input {{ border: 1px solid var(--line); background: var(--card); padding: 8px 12px; min-width: 220px; }}
    .books {{ display: grid; gap: 12px; }}
    .book {{
      display: grid;
      grid-template-columns: 84px 1fr;
      gap: 16px;
      background: var(--card);
      border: 1px solid var(--line);
      padding: 12px;
    }}
    .book[hidden] {{ display: none; }}
    .cover img {{ width: 84px; height: 126px; object-fit: cover; display: block; background: #efe6d6; }}
    h3 {{ font-family: Fraunces, serif; font-size: 22px; font-weight: 560; margin: 0 0 4px; }}
    h3 a, .cover {{ color: inherit; text-decoration: none; }}
    h3 a:hover {{ color: var(--sale); }}
    .author, .meta {{ margin: 0; color: var(--muted); }}
    .price {{ margin: 8px 0; }}
    .price s {{ color: var(--muted); }}
    .off {{ color: var(--ok); font-weight: 680; margin-left: 6px; }}
    .badge {{ display: inline-block; margin: 0 0 8px; padding: 4px 8px; background: var(--sale); color: var(--paper); font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase; }}
    .note {{ color: var(--muted); font-size: 13px; }}
    @media (max-width: 720px) {{
      header, .stats {{ display: block; }}
      .stat {{ margin-bottom: 12px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <div class="mark">Promo Livros</div>
        <h1>Livros selecionados</h1>
      </div>
      <p class="lede">Corte extra: mais de 2.000 avaliações. A ordem é a da Amazon, do que ela mais vende para o que vende menos. Rodada de 25 set 2026, 19:07.</p>
    </header>
    <section class="stats">
      <article class="stat"><b>{len(ranked)}</b><span>Livros com mais de 2.000 avaliações</span></article>
      <article class="stat"><b>{pct(medio)}</b><span>Desconto médio sobre 90 dias</span></article>
      <article class="stat"><b>31</b><span>Ficaram de fora neste corte</span></article>
      <article class="stat"><b>1º</b><span>Rita, não grita! vende mais na Amazon</span></article>
    </section>
    <h2>A lista</h2>
    <div class="tools">
      <button type="button" data-filter="todos" aria-pressed="true">Todos</button>
      <button type="button" data-filter="desconto30" aria-pressed="false">30% ou mais</button>
      <button type="button" data-filter="nota48" aria-pressed="false">Nota 4,8+</button>
      <input id="busca" type="search" placeholder="Título ou autor" aria-label="Buscar título ou autor">
    </div>
    <p class="note" id="count">{len(ranked)} livros com mais de 2.000 avaliações, do que a Amazon mais vende para o que vende menos.</p>
    <div class="books">
      {''.join(cards)}
    </div>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""

out = Path(__file__).with_name("index.html")
out.write_text(html, encoding="utf-8")
print(f"books={len(ranked)} bytes={out.stat().st_size}")
