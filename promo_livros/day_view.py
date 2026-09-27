from __future__ import annotations

from dataclasses import dataclass

from promo_livros.formatter import format_brl
from promo_livros.models import Dispatch, NicheConfig, PublishSlot, QueuedPost, WhatsAppGroup

BOOK_LABELS = {
    "ready": "pronto",
    "queued": "na fila",
    "posted": "publicado",
    "skipped": "pulado",
}
DISPATCH_LABELS = {
    "na_fila": "na fila",
    "enviando": "enviando",
    "enviada": "enviada",
    "falhou": "falhou",
    "expirada": "expirada",
}
NOT_QUEUED = "ainda não entrou na fila"


@dataclass(frozen=True)
class GroupLine:
    name: str
    chat_id: str
    status_label: str


@dataclass(frozen=True)
class BookLine:
    clock: str
    niche_label: str
    title: str
    price_label: str
    book_status: str
    caption: str
    groups: tuple[GroupLine, ...]
    reserve: bool


@dataclass(frozen=True)
class DayView:
    day: str
    books: tuple[BookLine, ...]


def build_day_view(
    *,
    day: str,
    slots: tuple[PublishSlot, ...],
    niches: tuple[NicheConfig, ...],
    per_niche: int,
    queue: tuple[QueuedPost, ...],
    dispatches: tuple[Dispatch, ...],
    saved_groups: tuple[WhatsAppGroup, ...],
    captions: dict[tuple[str, int], str],
) -> DayView | None:
    if not queue:
        return None
    labels = {niche.key: niche.label for niche in niches}
    books: list[BookLine] = []
    for slot in slots:
        row = next(
            (item for item in queue if item.niche_key == slot.niche_key and item.position == slot.rank),
            None,
        )
        clock = f"{slot.hour:02d}:{slot.minute:02d}"
        niche_label = labels.get(slot.niche_key, slot.niche_key)
        if row is None:
            books.append(BookLine(clock, niche_label, "", "", "sem livro", "", (), False))
            continue
        books.append(_book_line(clock, niche_label, row, False, dispatches, saved_groups, captions))
    for row in queue:
        if row.position < per_niche:
            continue
        books.append(
            _book_line("", row.niche_label, row, True, dispatches, saved_groups, captions)
        )
    return DayView(day=day, books=tuple(books))


def _book_line(
    clock: str,
    niche_label: str,
    row: QueuedPost,
    reserve: bool,
    dispatches: tuple[Dispatch, ...],
    saved_groups: tuple[WhatsAppGroup, ...],
    captions: dict[tuple[str, int], str],
) -> BookLine:
    groups: list[GroupLine] = []
    for group in saved_groups:
        match = next(
            (
                item
                for item in dispatches
                if item.niche_key == row.niche_key
                and item.position == row.position
                and item.chat_id == group.chat_id
            ),
            None,
        )
        label = NOT_QUEUED if match is None else DISPATCH_LABELS.get(match.status, match.status)
        groups.append(GroupLine(group.name, group.chat_id, label))
    return BookLine(
        clock=clock,
        niche_label=niche_label,
        title=row.title,
        price_label=format_brl(row.price_cents),
        book_status=BOOK_LABELS.get(row.status, row.status),
        caption=captions.get((row.niche_key, row.position), ""),
        groups=tuple(groups),
        reserve=reserve,
    )
