"""Gera textos de convite para uma campanha com a OpenAI (chat completions, como o blurb.py)."""
from __future__ import annotations

import logging
import re

import requests

from promo_livros.campaign_store import MAX_TEXT_LENGTH, CampaignError

logger = logging.getLogger("promo_livros.campaigns")

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
MIN_GENERATED_TEXTS = 3
MAX_GENERATED_TEXTS = 10
_REQUEST_TIMEOUT_SECONDS = 60
# Cada texto pode chegar a 1024 caracteres; 10 textos cabem folgados nesta janela.
_MAX_TOKENS = 4000
_LIST_MARKER = re.compile(r"^\s*(?:\d{1,2}\s*[.)\-:]|[-*•])\s*")

_SYSTEM_PROMPT = (
    "Você escreve convites curtos para grupos de WhatsApp de promoção de livros, em português do Brasil. "
    "Cada convite chama a pessoa para entrar no grupo da campanha, com tom amigável e direto de WhatsApp. "
    "Varie o gancho de cada convite. "
    "Não invente preço, desconto, prazo, cupom nem link. "
    "Escreva exatamente a quantidade pedida, um convite por linha, sem numeração, sem aspas "
    "e sem linhas em branco entre eles. Cada convite fica em uma única linha."
)


def clamp_text_count(count: int) -> int:
    return max(MIN_GENERATED_TEXTS, min(MAX_GENERATED_TEXTS, count))


def generate_campaign_texts(
    *,
    api_key: str,
    model: str,
    campaign_name: str,
    count: int,
    session: requests.Session | None = None,
) -> list[str]:
    """Devolve de 3 a 10 textos prontos para `add_text`. Falha da API vira CampaignError."""
    key = api_key.strip()
    if not key:
        raise CampaignError("Configure a chave da OpenAI (OPENAI_API_KEY) para gerar textos.")
    wanted = clamp_text_count(count)
    owns_session = session is None
    http = session or requests.Session()
    try:
        content = _request_completion(http, key, model, campaign_name, wanted)
    finally:
        if owns_session:
            http.close()
    texts = _parse_lines(content)[:wanted]
    if not texts:
        raise CampaignError("A IA não devolveu textos utilizáveis. Tente de novo.")
    return texts


def _request_completion(
    http: requests.Session, api_key: str, model: str, campaign_name: str, wanted: int
) -> str:
    payload = {
        "model": model,
        "temperature": 0.9,
        "max_tokens": _MAX_TOKENS,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Campanha: {' '.join(campaign_name.split())}\nEscreva {wanted} convites.",
            },
        ],
    }
    try:
        response = http.post(
            OPENAI_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # Só o tipo do erro vai ao log: a mensagem da biblioteca pode trazer cabeçalhos.
        logger.warning("A OpenAI não respondeu ao gerar textos da campanha: %s", type(exc).__name__)
        raise CampaignError("A OpenAI não respondeu. Tente de novo em instantes.") from exc
    if response.status_code in {401, 403}:
        raise CampaignError("A chave da OpenAI foi recusada. Confira OPENAI_API_KEY.")
    if response.status_code >= 400:
        logger.warning("A OpenAI recusou gerar textos da campanha (HTTP %s).", response.status_code)
        raise CampaignError(f"A OpenAI recusou o pedido (HTTP {response.status_code}).")
    try:
        body = response.json()
    except ValueError as exc:
        logger.warning("A OpenAI devolveu um corpo inválido ao gerar textos da campanha.")
        raise CampaignError("A OpenAI devolveu uma resposta inválida. Tente de novo.") from exc
    return _message_content(body)


def _message_content(body: object) -> str:
    choices = body.get("choices") if isinstance(body, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else ""


def _parse_lines(content: str) -> list[str]:
    texts: list[str] = []
    for line in content.splitlines():
        text = _LIST_MARKER.sub("", line).strip().strip('"').strip()
        # Passar do limite da legenda deixaria a campanha com texto que o WhatsApp recusa.
        if text and len(text) <= MAX_TEXT_LENGTH:
            texts.append(text)
    return texts
