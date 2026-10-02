"""Refaz links de afiliado só em posts que ainda não foram para nenhum grupo."""
from __future__ import annotations

import logging

from promo_livros.amz_links import AmzLinkClient, apply_affiliate_links, needs_affiliate_link
from promo_livros.board_store import BoardStore

logger = logging.getLogger("promo_livros.refresh_links")


def has_pending_links(store: BoardStore) -> bool:
    return any(
        needs_affiliate_link(book.url)
        for post in store.unsent_posts()
        for book in post.books
    )


def refresh_unsent_links(store: BoardStore, client: AmzLinkClient, tag: str) -> int:
    """Atualiza legenda e URL. Post enviado, em envio ou cancelado não entra."""
    if not tag.strip():
        return 0
    posts = store.unsent_posts()
    flat: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for post in posts:
        urls = [book.url for book in post.books]
        flat.extend(urls)
        spans.append((post.id, cursor, cursor + len(urls)))
        cursor += len(urls)
    if not any(needs_affiliate_link(url) for url in flat):
        return 0
    rewritten = apply_affiliate_links(flat, client, tag)
    originals = {post.id: [book.url for book in post.books] for post in posts}
    clocks = {post.id: (post.day, post.clock) for post in posts}
    changed = 0
    for post_id, start, end in spans:
        urls = rewritten[start:end]
        if urls == originals[post_id]:
            continue
        # Reconfere dentro da transação: um envio que começou agora fica intocado.
        if store.replace_urls_if_unsent(post_id, urls):
            day, clock = clocks[post_id]
            logger.info("Post %s %s teve o link refeito antes do envio.", day, clock)
            changed += 1
    return changed
