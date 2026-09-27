from __future__ import annotations

import logging
import re
from typing import Protocol

import requests

logger = logging.getLogger("promo_livros")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(?:\s|$)")


class BlurbWriter(Protocol):
    def summarize(self, *, title: str, author: str, niche_label: str, rating: int, review_count: int, synopsis: str) -> str | None:
        """Uma frase sobre o livro, ou None se não houver texto ou a API falhar."""


class OpenAIBlurb:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_chars: int,
        session: requests.Session | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._model = model
        self._max_chars = max_chars
        self._session = session or requests.Session()

    def summarize(
        self,
        *,
        title: str,
        author: str,
        niche_label: str,
        rating: int,
        review_count: int,
        synopsis: str,
    ) -> str | None:
        cleaned = synopsis.strip()
        if not self._api_key or not cleaned:
            return None
        payload = {
            "model": self._model,
            "temperature": 0.2,
            "max_tokens": 120,
            "messages": [
                {"role": "system", "content": _system_prompt(self._max_chars)},
                {
                    "role": "user",
                    "content": (
                        f"Nicho: {niche_label}\n"
                        f"Título: {title}\n"
                        f"Autor: {author}\n"
                        f"Nota: {rating / 10:.1f} de 5, com {review_count} avaliações\n"
                        f"Sinopse:\n{cleaned}"
                    ),
                },
            ],
        }
        try:
            response = self._session.post(
                _OPENAI_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=30,
            )
        except requests.RequestException:
            logger.warning("A OpenAI não respondeu. A mensagem sai sem a frase do livro.")
            return None
        if response.status_code >= 400:
            logger.warning("A OpenAI recusou o resumo (HTTP %s). A mensagem sai sem a frase.", response.status_code)
            return None
        try:
            body = response.json()
        except ValueError:
            logger.warning("A OpenAI devolveu um corpo inválido. A mensagem sai sem a frase.")
            return None
        return one_sentence(_message_text(body), self._max_chars)


def one_sentence(text: str, max_chars: int) -> str | None:
    compact = " ".join(text.replace("*", "").replace("_", " ").split())
    if not compact:
        return None
    match = _SENTENCE_RE.match(compact)
    if match:
        compact = match.group(1).strip()
    if len(compact) <= max_chars:
        return compact
    trimmed = compact[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:")
    if not trimmed:
        trimmed = compact[:max_chars].rstrip(".,;:")
    return f"{trimmed}."


def _system_prompt(max_chars: int) -> str:
    return (
        "Você escreve uma única frase, em português do Brasil, dizendo do que o livro trata. "
        "Use somente o título, o autor, o nicho e a sinopse recebidos. "
        "Não invente prêmio, crítica, nota ou fato que não esteja na sinopse. "
        "Não mencione preço, desconto nem quantidade de avaliações. "
        "Não use aspas, emoji nem quebra de linha. "
        f"No máximo {max_chars} caracteres."
    )


def _message_text(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return " ".join(parts)
    return ""
