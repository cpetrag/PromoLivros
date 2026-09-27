from __future__ import annotations


class WebsitePoster:
    """Publica a mesma oferta curada no site.

    O site ainda não existe. Quando estiver no ar, este método recebe o texto
    e a capa que o WhatsApp também recebe. Enquanto `website.enabled` for false,
    o ciclo não instancia esta classe.
    """

    def send_deal(self, caption: str, image_url: str | None) -> None:
        raise NotImplementedError(
            "O site ainda não está no ar. "
            "Deixe website.enabled em false para só rodar a curadoria."
        )
