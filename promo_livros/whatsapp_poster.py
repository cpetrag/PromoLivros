"""Conexão com o WhatsApp via WAHA. A fila de disparo está em dispatch.py."""

from promo_livros.waha import WahaClient as WhatsAppPoster

__all__ = ["WhatsAppPoster"]
