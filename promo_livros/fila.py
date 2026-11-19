"""Montagem da fila do dia. Curadoria, prévia e reorganizar usam esta função."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_PREFIXOS = re.compile(
    r"^(book charm|cole[cç][aã]o especial|box|kit \d+ livros?)\s*[-–:]?\s*",
    re.IGNORECASE,
)
_STOP = re.compile(
    r"\b(box|kit|edicao|de luxo|luxo|capa dura|capa mole|almofadada|livro|livros|volume|vol|chaveiro|com \d+)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ASIN_URL = re.compile(r"(?:/dp/|/gp/product/|/gp/aw/d/|[?&]asin=)([A-Z0-9]{10})", re.IGNORECASE)
_MLB_URL = re.compile(r"MLB-?(\d{6,14})", re.IGNORECASE)
_MAX_SLOTS = 60
_MIX_WINDOW = 4


@dataclass(frozen=True)
class ItemFila:
    id: str
    title: str
    store: str
    price_cents: int | None = None
    discount: int = 0
    category: str = ""
    reserva: bool = False
    # Só serve para abrir a loja na curadoria; o mesmo livro com outro link continua igual.
    url: str = field(default="", compare=False)


@dataclass(frozen=True)
class SlotFila:
    clock: str
    amazon: ItemFila | None
    ml: ItemFila | None
    amazon_avisos: tuple[str, ...] = ()
    ml_avisos: tuple[str, ...] = ()
    shopee: ItemFila | None = None
    shopee_avisos: tuple[str, ...] = ()
    # Segunda oferta da mesma loja. Fica vazio quando o post tem uma oferta, ou duas de lojas diferentes.
    extra: ItemFila | None = None
    extra_avisos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bloqueado:
    item: ItemFila
    clocks: tuple[str, ...]


@dataclass(frozen=True)
class FilaMontada:
    slots: tuple[SlotFila, ...]
    bloqueados: tuple[Bloqueado, ...]
    sobras: tuple[ItemFila, ...]
    clocks: tuple[str, ...]


@dataclass(frozen=True)
class OpcoesFila:
    agora: str
    inicio: str
    fim: str
    intervalo: int
    enviados: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ordem: str = "mine"
    obras_enviadas: tuple[tuple[str, str], ...] = ()
    horarios: tuple[str, ...] | None = None
    # Ordem que a pessoa arrumou na grade da curadoria: ids da Amazon e da segunda loja.
    ordem_manual: tuple[tuple[str, ...], tuple[str, ...]] | None = None


def montar_fila(
    amazon: list[ItemFila],
    mercado: list[ItemFila],
    opcoes: OpcoesFila,
    shopee: list[ItemFila] | None = None,
) -> FilaMontada:
    """Uma fila para o que ainda cabe hoje. Enviado na janela não entra. Sobra não some: volta em `sobras`.

    O post leva no máximo duas lojas, então Shopee divide a segunda metade com o Mercado Livre.
    """
    clocks = list(opcoes.horarios) if opcoes.horarios is not None else horarios_livres(
        opcoes.inicio, opcoes.fim, opcoes.intervalo, opcoes.agora
    )
    az_ok, az_block = _separar(amazon, opcoes.enviados)
    ml_ok, ml_block = _separar([*mercado, *(shopee or [])], opcoes.enviados)
    az = _preparar(az_ok, opcoes.ordem)
    ml = _preparar(ml_ok, opcoes.ordem)
    if opcoes.ordem_manual is not None:
        az = com_ordem_manual(az, opcoes.ordem_manual[0])
        ml = com_ordem_manual(ml, opcoes.ordem_manual[1])
    usados = min(len(clocks), max(len(az), len(ml)))
    slots = tuple(
        SlotFila(
            clocks[index],
            az[index] if index < len(az) else None,
            _da_loja(ml, index, "ml"),
            shopee=_da_loja(ml, index, "shopee"),
        )
        for index in range(usados)
    )
    slots = _avisos(slots, opcoes.obras_enviadas)
    sobras = tuple([*az[usados:], *ml[usados:]])
    return FilaMontada(slots, tuple([*az_block, *ml_block]), sobras, tuple(clocks))


def horarios_livres(inicio: str, fim: str, intervalo: int, agora: str) -> list[str]:
    """Horários da grade que começam depois de agora e terminam antes do limite."""
    start = _minutes(inicio)
    end = _minutes(fim)
    now = _minutes(agora)
    step = int(intervalo)
    if step <= 0 or end <= start:
        return []
    minute = start
    clocks: list[str] = []
    while minute + step <= end and len(clocks) < _MAX_SLOTS:
        if minute > now:
            clocks.append(_format(minute))
        minute += step
    return clocks


def chave_obra(titulo: str) -> str:
    """Chave curta para comparar a mesma obra em lojas e edições diferentes."""
    text = _fold(titulo)
    text = _PREFIXOS.sub("", text)
    text = re.split(r"\s[-–|]\s?|\(", text, maxsplit=1)[0]
    text = _STOP.sub(" ", text)
    text = _YEAR.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(text.split()[:4])


def obras_batem(esquerda: str, direita: str) -> bool:
    """A mesma obra. Três termos iguais, ou a chave mais curta abre a mais longa."""
    a = (esquerda or "").split()
    b = (direita or "").split()
    if not a or not b:
        return False
    if len(a) >= 3 and len(b) >= 3:
        return a[:3] == b[:3]
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and long[: len(short)] == short


def serie_de(titulo: str) -> str:
    """O que vem antes de ':' é a série, quando o título tem esse corte."""
    raw = titulo or ""
    if ":" not in raw:
        return ""
    head = _fold(raw.split(":", 1)[0])
    if len(head.split()) < 2:
        return ""
    return head


def produto_de_url(url: str) -> str:
    """ASIN ou MLB que ainda dá para ler no endereço. Link curto sem id devolve vazio."""
    match = _MLB_URL.search(url or "")
    if match:
        return "MLB" + match.group(1)
    match = _ASIN_URL.search(url or "")
    if match:
        return match.group(1).upper()
    return ""


def item_de_livro(book) -> ItemFila:
    discount = 0
    price = getattr(book, "price_cents", None)
    listed = getattr(book, "list_cents", None)
    if listed is None:
        listed = getattr(book, "list_price_cents", None)
    if price and listed and listed > price:
        discount = round((listed - price) * 100 / listed)
    state = getattr(book, "pick_state", "") or ""
    raw_store = getattr(book, "store", "amazon") or "amazon"
    store = raw_store if raw_store in {"amazon", "ml", "shopee"} else "amazon"
    return ItemFila(
        id=str(book.asin),
        title=str(book.title),
        store=store,
        price_cents=price,
        discount=int(getattr(book, "discount", discount) or discount),
        category=str(getattr(book, "category", "") or ""),
        reserva=state == "reserva",
        url=str(getattr(book, "url", "") or ""),
    )


def pode_preencher(book, *, loja: str, enviados: set[str]) -> bool:
    """O preenchimento automático não pega enviado, infantil, papelaria nem, na Amazon, item sem menor preço."""
    if not getattr(book, "price_cents", None):
        return False
    if getattr(book, "kids", False) or getattr(book, "not_book", False):
        return False
    if str(book.asin).upper() in enviados:
        return False
    state = getattr(book, "pick_state", "") or ""
    if getattr(book, "picked", False) or state in {"marcado", "na_fila", "reserva", "enviado"}:
        return False
    if loja == "amazon" and not getattr(book, "low_365", False):
        return False
    return True


def _separar(items: list[ItemFila], enviados: dict[str, tuple[str, ...]]) -> tuple[list[ItemFila], list[Bloqueado]]:
    livres: list[ItemFila] = []
    bloqueados: list[Bloqueado] = []
    for item in items:
        clocks = enviados.get(item.id.upper()) or enviados.get(item.id)
        if clocks:
            bloqueados.append(Bloqueado(item, tuple(clocks)))
        elif item.price_cents:
            livres.append(item)
    return livres, bloqueados


def _da_loja(items: list[ItemFila], index: int, loja: str) -> ItemFila | None:
    if index >= len(items) or items[index].store != loja:
        return None
    return items[index]


def com_ordem_manual(items: list[ItemFila], ids: tuple[str, ...]) -> list[ItemFila]:
    """Quem está na lista segue a lista. Marcado depois da arrumação entra no fim, na ordem de antes."""
    place = {item_id.upper(): index for index, item_id in enumerate(ids)}
    listed = sorted((item for item in items if item.id.upper() in place), key=lambda item: place[item.id.upper()])
    rest = [item for item in items if item.id.upper() not in place]
    return [*listed, *rest]


def _preparar(items: list[ItemFila], ordem: str) -> list[ItemFila]:
    reservas = [item for item in items if item.reserva]
    resto = [item for item in items if not item.reserva]
    return [*reservas, *_ordenar(resto, ordem)]


def _ordenar(items: list[ItemFila], ordem: str) -> list[ItemFila]:
    if ordem == "desc":
        return sorted(items, key=lambda item: (-item.discount, item.title.casefold(), item.id))
    if ordem == "mix":
        return _intercalar(items)
    return list(items)


def _intercalar(items: list[ItemFila]) -> list[ItemFila]:
    pool = sorted(items, key=lambda item: (-item.discount, item.title.casefold(), item.id))
    chosen: list[ItemFila] = []
    while pool:
        pick = _primeiro(pool, chosen, obra=True, categoria=True)
        if pick is None:
            pick = _primeiro(pool, chosen, obra=True, categoria=False)
        if pick is None:
            pick = pool[0]
        pool.remove(pick)
        chosen.append(pick)
    return chosen


def _primeiro(pool: list[ItemFila], chosen: list[ItemFila], *, obra: bool, categoria: bool) -> ItemFila | None:
    recentes = chosen[-_MIX_WINDOW:]
    chaves = {chave_obra(item.title) for item in recentes} if obra else set()
    categorias = {
        item.category.casefold()
        for item in recentes
        if categoria and item.category and item.category.casefold() not in {"sem categoria", ""}
    }
    for candidate in pool:
        if obra and any(obras_batem(chave_obra(candidate.title), chave) for chave in chaves):
            continue
        if categoria and candidate.category and candidate.category.casefold() in categorias:
            continue
        return candidate
    return None


def _avisos(slots: tuple[SlotFila, ...], obras_enviadas: tuple[tuple[str, str], ...]) -> tuple[SlotFila, ...]:
    placed: list[tuple[int, str, ItemFila]] = []
    for index, slot in enumerate(slots):
        if slot.amazon is not None:
            placed.append((index, "amazon", slot.amazon))
        if slot.ml is not None:
            placed.append((index, "ml", slot.ml))
        if slot.shopee is not None:
            placed.append((index, "shopee", slot.shopee))
        if slot.extra is not None:
            placed.append((index, "extra", slot.extra))
    notes: dict[tuple[int, str], list[str]] = {}
    for index, store, item in placed:
        found: list[str] = []
        chave = chave_obra(item.title)
        saida = [
            clock
            for outra, clock in obras_enviadas
            if obras_batem(chave, outra)
        ]
        if saida:
            found.append("mesma obra saiu " + _juntar_horas(saida))
        outros = [
            (other_index, other)
            for other_index, _store, other in placed
            if other.id != item.id and obras_batem(chave, chave_obra(other.title))
        ]
        if outros:
            outros.sort(key=lambda pair: abs(pair[0] - index))
            found.append(f"aparece de novo às {slots[outros[0][0]].clock}")
        serie = serie_de(item.title)
        if serie and not outros:
            series = [
                other_index
                for other_index, _store, other in placed
                if other.id != item.id
                and serie_de(other.title) == serie
                and abs(other_index - index) < _MIX_WINDOW
                and not obras_batem(chave, chave_obra(other.title))
            ]
            if series:
                series.sort(key=lambda other_index: abs(other_index - index))
                found.append(f"mesma série às {slots[series[0]].clock}")
        if found:
            notes[(index, store)] = found
    marked: list[SlotFila] = []
    for index, slot in enumerate(slots):
        marked.append(
            SlotFila(
                slot.clock,
                slot.amazon,
                slot.ml,
                tuple(notes.get((index, "amazon"), ())),
                tuple(notes.get((index, "ml"), ())),
                slot.shopee,
                tuple(notes.get((index, "shopee"), ())),
                slot.extra,
                tuple(notes.get((index, "extra"), ())),
            )
        )
    return tuple(marked)


def _juntar_horas(clocks: list[str]) -> str:
    unique = list(dict.fromkeys(clocks))
    if len(unique) == 1:
        return unique[0]
    if len(unique) == 2:
        return f"{unique[0]} e {unique[1]}"
    return ", ".join(unique[:-1]) + f" e {unique[-1]}"


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return stripped.casefold()


def _minutes(value: str) -> int:
    match = _CLOCK.fullmatch((value or "").strip())
    if match is None:
        raise ValueError(f"Horário inválido: {value}")
    return int(match.group(1)) * 60 + int(match.group(2))


def _format(minute: int) -> str:
    hour, mins = divmod(minute, 60)
    return f"{hour:02d}:{mins:02d}"
