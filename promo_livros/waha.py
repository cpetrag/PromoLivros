from __future__ import annotations

import logging
from typing import Protocol

import requests

from promo_livros.models import AppConfig, WhatsAppGroup

logger = logging.getLogger("promo_livros")

_SEND_TIMEOUT_SECONDS = 45
_STATUS_TIMEOUT_SECONDS = 8


class WahaError(Exception):
    """O WAHA recusou ou não respondeu. A fila decide se tenta de novo."""

    def __init__(self, message: str, *, session_down: bool) -> None:
        super().__init__(message)
        self.session_down = session_down


class WhatsAppSender(Protocol):
    def connection_state(self) -> str:
        """connected, qr ou disconnected."""

    def send(self, chat_id: str, caption: str, image_url: str | None) -> str:
        """Envia a oferta e devolve o id da mensagem."""

    def close(self) -> None:
        """Fecha a sessão HTTP."""


class WahaClient:
    """Fala com o WAHA do Promo Livros, na porta 4443 do Mac.

    A sessão esteira, na porta 3000, fica com o Baby Poupe. A API escuta só
    em 127.0.0.1, então este processo precisa estar nessa máquina ou atrás
    de um túnel SSH.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        session: str,
        *,
        http: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.session = session.strip()
        self._http = http or requests.Session()
        self._owns_http = http is None

    @classmethod
    def from_config(cls, config: AppConfig) -> WahaClient:
        return cls(config.waha_url, config.waha_api_key, config.waha_session)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def connection_state(self) -> str:
        try:
            payload = self._request(
                "GET",
                f"/api/sessions/{self.session}",
                timeout=_STATUS_TIMEOUT_SECONDS,
            )
        except WahaError:
            return "disconnected"
        status = ""
        if isinstance(payload, dict):
            status = str(payload.get("status") or "")
        return _map_session_status(status)

    def probe_session(self) -> str:
        """Igual a connection_state, mas deixa o erro subir."""
        payload = self._request(
            "GET",
            f"/api/sessions/{self.session}",
            timeout=_STATUS_TIMEOUT_SECONDS,
        )
        status = ""
        if isinstance(payload, dict):
            status = str(payload.get("status") or "")
        return _map_session_status(status)

    def fetch_qr_png(self) -> bytes:
        headers = {"accept": "image/png"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            response = self._http.request(
                "GET",
                f"{self.base_url}/api/{self.session}/auth/qr",
                headers=headers,
                json=None,
                timeout=_STATUS_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise WahaError("WAHA não respondeu. Confira WAHA_URL.", session_down=True) from exc
        content_type = ""
        response_headers = getattr(response, "headers", {}) or {}
        if hasattr(response_headers, "get"):
            content_type = str(response_headers.get("content-type") or "")
        if response.status_code >= 400 or "image/" not in content_type.lower() or not response.content:
            logger.warning(
                "WAHA recusou o QR: HTTP %s, content-type=%s",
                response.status_code,
                content_type or "(vazio)",
            )
            raise WahaError("WAHA não devolveu o QR.", session_down=False)
        return bytes(response.content)

    def list_groups(self) -> list[WhatsAppGroup]:
        if self.connection_state() != "connected":
            return []
        payload = self._request("GET", f"/api/{self.session}/groups", timeout=_STATUS_TIMEOUT_SECONDS)
        rows = payload if isinstance(payload, list) else []
        if isinstance(payload, dict) and isinstance(payload.get("groups"), list):
            rows = payload["groups"]
        groups: list[WhatsAppGroup] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            chat_id = _group_field(item, ("id", "JID", "jid"))
            if not chat_id.endswith("@g.us"):
                continue
            name = _group_field(item, ("name", "Name", "subject", "Subject")) or chat_id
            groups.append(WhatsAppGroup(name=name, chat_id=chat_id))
        groups.sort(key=lambda group: group.name.casefold())
        return groups

    def send(self, chat_id: str, caption: str, image_url: str | None) -> str:
        if image_url:
            payload = self._request(
                "POST",
                "/api/sendImage",
                timeout=_SEND_TIMEOUT_SECONDS,
                body={
                    "session": self.session,
                    "chatId": chat_id,
                    "caption": caption,
                    "file": {
                        "mimetype": "image/jpeg",
                        "filename": "capa.jpg",
                        "url": image_url,
                    },
                },
            )
        else:
            payload = self._request(
                "POST",
                "/api/sendText",
                timeout=_SEND_TIMEOUT_SECONDS,
                body={
                    "session": self.session,
                    "chatId": chat_id,
                    "text": caption,
                },
            )
        return _message_id(payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        body: dict | None = None,
    ) -> object:
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            response = self._http.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise WahaError("WAHA não respondeu. Confira WAHA_URL.", session_down=True) from exc

        if response.status_code >= 400:
            raise WahaError(_error_message(response), session_down=_session_down(response))
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}


def _map_session_status(status: str) -> str:
    value = status.upper()
    if value == "WORKING":
        return "connected"
    if value in {"SCAN_QR_CODE", "STARTING", "OPENING", "PAIRING", "PASSKEY_REQUIRED"}:
        return "qr"
    return "disconnected"


def _message_id(payload: object) -> str:
    if not isinstance(payload, dict):
        raise WahaError("WAHA não devolveu o id da mensagem.", session_down=False)
    message_id = payload.get("messageId")
    if isinstance(message_id, str) and message_id:
        return message_id
    raw_id = payload.get("id")
    if isinstance(raw_id, str) and raw_id:
        return raw_id
    if isinstance(raw_id, dict):
        serialized = raw_id.get("_serialized") or raw_id.get("id")
        if isinstance(serialized, str) and serialized:
            return serialized
    key = payload.get("key")
    if isinstance(key, dict) and isinstance(key.get("id"), str) and key["id"]:
        return key["id"]
    raise WahaError("WAHA não devolveu o id da mensagem.", session_down=False)


def _group_field(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            serialized = value.get("_serialized")
            if isinstance(serialized, str) and serialized.strip():
                return serialized.strip()
    return ""


def _session_down(response: requests.Response) -> bool:
    text = response.text or ""
    return bool(
        response.status_code in {401, 422}
        or "not working" in text.lower()
        or "scan_qr" in text.lower()
        or "disconnected" in text.lower()
    )


def _error_message(response: requests.Response) -> str:
    detail = (response.text or "").strip()
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if isinstance(message, str) and message.strip():
            detail = message.strip()
    if _session_down(response):
        return "WhatsApp ainda não está pareado. A sessão do WAHA precisa estar WORKING."
    if not detail:
        return f"WAHA recusou o envio. HTTP {response.status_code}."
    return f"WAHA recusou o envio. HTTP {response.status_code}: {detail}"[:280]
