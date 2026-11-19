from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Protocol

import requests

from promo_livros.post_copy import MAX_BLURB_WORDS

logger = logging.getLogger("promo_livros")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_RESPONSES_URL = "https://api.openai.com/v1/responses"
_SENTENCE_RE = re.compile(r"^(.+?[.!?])(?:\s|$)")
_MAX_PITCH_WORDS = 12
_WORD_CAP = re.compile(r"(?:no\s+)?m[aá]ximo(?:\s+de)?\s+(\d+)\s+palavras", re.I)
_PRICE_WORDS = ("r$", "preço", "preco", "desconto")


class OpenAIAuthError(Exception):
    """A chave não foi aceita. A fila não deve apagar as frases que já tem."""


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
        self._owns_session = session is None

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def pitch(self, *, title: str, synopsis: str) -> str | None:
        """Uma frase curta com convite para ler este livro, ou None se não der."""
        source = " ".join((synopsis or "").split())
        name = " ".join((title or "").split())
        if not self._api_key or not name or not source:
            return None
        text = self._complete(
            _pitch_prompt(),
            f"Título: {name}\nSinopse:\n{source}",
            max_tokens=60,
        )
        line = promo_line(text or "")
        if line is not None:
            return line
        text = self._complete(
            _pitch_prompt(),
            (
                f"Título: {name}\nSinopse:\n{source}\n"
                "A frase anterior passou de 12 palavras. Escreva outra, com no máximo 12."
            ),
            max_tokens=60,
        )
        return promo_line(text or "")

    def research(self, *, title: str, author: str = "", prompt: str = "") -> str | None:
        """Uma frase de até 12 palavras, achada na internet, ou None se não der."""
        name = " ".join((title or "").split())
        writer = " ".join((author or "").split())
        if not self._api_key or not name:
            return None
        chosen = " ".join((prompt or "").split()) or research_prompt()
        limit = words_allowed(chosen)
        text = self._research(name, writer, prompt=chosen)
        line = promo_line(text or "", max_words=limit)
        if line is not None or not (text or "").strip():
            return line
        text = self._research(name, writer, shorter=True, prompt=chosen, limit=limit)
        return promo_line(text or "", max_words=limit)

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
        return one_sentence(self._complete(_system_prompt(self._max_chars), payload["messages"][1]["content"], 120) or "", self._max_chars)

    def _research(
        self,
        title: str,
        author: str,
        *,
        shorter: bool = False,
        prompt: str = "",
        limit: int = _MAX_PITCH_WORDS,
    ) -> str | None:
        who = f"Título: {title}"
        if author:
            who += f"\nAutor: {author}"
        if shorter:
            who += f"\nA frase anterior passou de {limit} palavras. Escreva outra, com no máximo {limit}."
        try:
            response = self._session.post(
                _RESPONSES_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "tools": [{"type": "web_search"}],
                    "input": [
                        {"role": "system", "content": prompt or research_prompt()},
                        {"role": "user", "content": who},
                    ],
                },
                timeout=45,
            )
        except requests.RequestException:
            logger.warning("A OpenAI não respondeu. A resenha fica de fora.")
            return self._research_from_pages(title, author, prompt)
        if response.status_code in {401, 403}:
            raise OpenAIAuthError("A chave da OpenAI foi recusada.")
        if response.status_code >= 400:
            logger.warning("A busca na web recusou (HTTP %s). Vou ler páginas públicas.", response.status_code)
            return self._research_from_pages(title, author, prompt)
        try:
            text = _response_text(response.json())
        except ValueError:
            return self._research_from_pages(title, author, prompt)
        return text or self._research_from_pages(title, author, prompt)

    def _research_from_pages(self, title: str, author: str, prompt: str = "") -> str | None:
        notes = self._public_notes(title)
        if not notes:
            return None
        who = f"Título: {title}"
        if author:
            who += f"\nAutor: {author}"
        return self._complete(
            (prompt or research_prompt()) + " Use somente os trechos abaixo, que vieram da internet.",
            f"{who}\nTrechos:\n{notes}",
            60,
        )

    def _public_notes(self, title: str) -> str:
        try:
            response = self._session.get(
                "https://pt.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{title} livro",
                    "srlimit": 2,
                    "utf8": 1,
                    "format": "json",
                },
                headers={"user-agent": "promo-livros"},
                timeout=12,
            )
        except requests.RequestException:
            return ""
        if getattr(response, "status_code", 500) >= 400:
            return ""
        try:
            payload = response.json()
        except ValueError:
            return ""
        hits = (payload.get("query") or {}).get("search") or []
        snippets = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            text = re.sub(r"<[^>]+>", "", " ".join(str(hit.get("snippet") or "").split()))
            if text:
                snippets.append(text)
        return "\n".join(snippets[:2])

    def _complete(self, system: str, user: str, max_tokens: int) -> str | None:
        try:
            response = self._session.post(
                _OPENAI_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "temperature": 0.4,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=30,
            )
        except requests.RequestException:
            logger.warning("A OpenAI não respondeu. A mensagem sai sem a frase do livro.")
            return None
        if response.status_code in {401, 403}:
            raise OpenAIAuthError("A chave da OpenAI foi recusada.")
        if response.status_code >= 400:
            logger.warning("A OpenAI recusou o resumo (HTTP %s). A mensagem sai sem a frase.", response.status_code)
            return None
        try:
            body = response.json()
        except ValueError:
            logger.warning("A OpenAI devolveu um corpo inválido. A mensagem sai sem a frase.")
            return None
        return _message_text(body)


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


def words_allowed(prompt: str) -> int:
    """O número de palavras que o prompt pediu. Sem isso, a resenha continua em 12."""
    found = _WORD_CAP.search(prompt or "")
    if found is None:
        return _MAX_PITCH_WORDS
    return min(MAX_BLURB_WORDS, max(4, int(found.group(1))))


def promo_line(text: str, max_words: int = _MAX_PITCH_WORDS) -> str | None:
    """Aceita uma frase curta, sem preço e sem marca de WhatsApp."""
    compact = " ".join(text.replace("*", " ").replace("_", " ").split())
    compact = compact.strip().strip('"').strip("'").strip()
    if not compact:
        return None
    words = compact.rstrip(".!?").split()
    if not 4 <= len(words) <= max_words:
        return None
    folded = compact.casefold()
    if any(token in folded for token in _PRICE_WORDS):
        return None
    if compact[-1] not in ".!?":
        compact = f"{compact}."
    return compact


def _pitch_prompt() -> str:
    return (
        "Você escreve uma única frase de no máximo 12 palavras, em português do Brasil, "
        "para a legenda de um livro no WhatsApp. "
        "A frase resume o assunto deste livro baseado em resenhas encontradas na internet "
        "e nasce só do título e da sinopse. "
        "Não invente trama, prêmio ou fato que não esteja na sinopse. "
        "Não mencione preço, desconto, frete nem avaliações. "
        "Não repita o título. "
        "Não use aspas, emoji, asterisco, sublinhado nem quebra de linha."
    )


def research_prompt() -> str:
    """Instrução padrão das resenhas. Configurações pode trocar este texto."""
    return _research_prompt()


def _research_prompt() -> str:
    return (
        "Pesquise na internet do que trata este livro. "
        "Escreva uma única frase de no máximo 12 palavras, em português do Brasil, "
        "para a legenda no WhatsApp. "
        "A frase resume o assunto com base no que as páginas encontradas dizem. "
        "Se não achar o livro, responda vazio. "
        "Não invente trama, prêmio ou fato que a pesquisa não sustente. "
        "Não mencione preço, desconto, frete nem avaliações. "
        "Não repita o título. "
        "Não use aspas, emoji, asterisco, sublinhado nem quebra de linha."
    )


def _system_prompt(max_chars: int) -> str:
    return (
        "Você escreve uma única frase, em português do Brasil, dizendo do que o livro trata. "
        "Use somente o título, o autor, o nicho e a sinopse recebidos. "
        "Não invente prêmio, crítica, nota ou fato que não esteja na sinopse. "
        "Não mencione preço, desconto nem quantidade de avaliações. "
        "Não use aspas, emoji nem quebra de linha. "
        f"No máximo {max_chars} caracteres."
    )


def _response_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = payload.get("output")
    parts: list[str] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        parts.append(block["text"])
            if isinstance(item.get("text"), str):
                parts.append(item["text"])
    if parts:
        return " ".join(parts)
    return _message_text(payload)


class BlurbCache:
    """Guarda a frase que a IA já achou, para não pesquisar o mesmo livro de novo."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._rows: dict[str, str] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict):
                self._rows = {
                    str(key): value
                    for key, value in loaded.items()
                    if isinstance(value, str) and value.strip()
                }

    def get(self, title: str) -> str:
        with self._lock:
            return self._rows.get(_cache_key(title), "")

    def put(self, title: str, line: str) -> None:
        key = _cache_key(title)
        cleaned = line.strip()
        if not key or not cleaned:
            return
        with self._lock:
            self._rows[key] = cleaned
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self._rows, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self._path)


def _cache_key(title: str) -> str:
    return " ".join(title.casefold().split())


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
