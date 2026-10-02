"""Lista de assinaturas editada no painel. O envio escolhe a próxima na hora."""
from __future__ import annotations

from promo_livros.post_copy import signature_of


def parse_block(text: str) -> list[str]:
    """Trechos separados por |. Espaço nas pontas sai; trecho vazio não conta."""
    pieces = []
    for chunk in (text or "").split("|"):
        piece = chunk.strip()
        if piece:
            pieces.append(piece)
    return pieces


def apply_signature(caption: str, signature: str) -> str:
    """Troca a última linha de assinatura. Se não houver, acrescenta no fim."""
    current = signature_of(caption or "")
    if current:
        head, found, _tail = (caption or "").rpartition(current)
        if found:
            return head + signature
    body = (caption or "").rstrip()
    if not body:
        return signature
    return f"{body}\n\n{signature}"
