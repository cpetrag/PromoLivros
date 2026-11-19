import unittest

import re

from promo_livros.campaign_pages import (
    CAMPAIGN_STYLE,
    INVITE_STYLE,
    InviteCard,
    render_campaign_detail,
    render_campaign_list,
    render_invite_cards,
)
from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST, InviteSettings
from promo_livros.campaign_store import Campaign, CampaignImage, CampaignText


class CampaignPageTests(unittest.TestCase):
    def test_list_escapes_names_and_marks_incomplete(self) -> None:
        html = render_campaign_list(
            [Campaign(1, "Terror <b>", True, 1, 0, 2), Campaign(2, "Kindle", True, 2, 1, 1)],
            InviteSettings("13:15", 10),
            notice="Salvo & pronto",
        )
        self.assertIn("Terror &lt;b&gt;", html)
        self.assertNotIn("Terror <b>", html)
        self.assertIn("Incompleta", html)
        self.assertIn("Pronta", html)
        self.assertIn('value="13:15"', html)
        self.assertIn('action="/campanhas/config"', html)
        self.assertIn("Salvo &amp; pronto", html)
        self.assertIn('href="/campanhas" aria-current="page"', html)

    def test_list_marks_inactive_campaigns(self) -> None:
        html = render_campaign_list([Campaign(1, "Velha", False, 1, 1, 1)], InviteSettings(None, 10), notice=None)
        self.assertIn("Desativada", html)
        self.assertIn('name="fixo" value=""', html)

    def test_detail_has_upload_form_and_escaped_texts(self) -> None:
        html = render_campaign_detail(
            Campaign(3, "Kindle", True, 1, 1, 1),
            [CampaignImage(9, 3, "data/campaigns/3/a.jpg")],
            [CampaignText(4, 3, "<script>x</script>")],
            notice=None,
        )
        self.assertIn('action="/campanhas/3/fotos"', html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('src="/campanhas/foto/9.jpg"', html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertIn('maxlength="1024"', html)

    def test_detail_lists_saved_texts_and_photos_apart_from_the_new_text_box(self) -> None:
        html = render_campaign_detail(
            Campaign(3, "Kindle", True, 1, 2, 2),
            [CampaignImage(9, 3, "data/campaigns/3/a.jpg"), CampaignImage(10, 3, "data/campaigns/3/b.jpg")],
            [CampaignText(4, 3, "Primeiro"), CampaignText(5, 3, "Segundo")],
            notice=None,
        )
        self.assertIn("Fotos salvas (2)", html)
        self.assertIn("Textos salvos (2)", html)
        saved = html.split("Textos salvos (2)", 1)[1]
        self.assertIn('<p class="body">Primeiro</p>', saved)
        self.assertIn('<p class="body">Segundo</p>', saved)
        self.assertIn('name="texto" value="4"', saved)
        self.assertIn('name="texto" value="5"', saved)
        new_box = re.search(r'<textarea id="new-text-body"[^>]*>(.*?)</textarea>', html, re.S)
        self.assertIsNotNone(new_box)
        self.assertEqual(new_box.group(1), "")
        self.assertNotIn('value="texto_novo"', saved)

    def test_detail_lets_the_user_paste_photos(self) -> None:
        html = render_campaign_detail(Campaign(3, "Kindle", True, 1, 0, 0), [], [], notice=None)
        self.assertIn('id="photo-upload"', html)
        self.assertIn('data-max-bytes="', html)
        self.assertIn('id="paste-photo"', html)
        self.assertIn('id="paste-preview"', html)
        self.assertIn('id="paste-status"', html)
        self.assertIn('addEventListener("paste"', html)

    def test_invite_cards_offer_the_ready_campaigns(self) -> None:
        ready = [Campaign(1, "A", True, 1, 1, 1), Campaign(2, "B", True, 2, 1, 1)]
        html = render_invite_cards(
            [
                InviteCard(INVITE_FIXED, "Convite das 13:15", "Aguardando", None, "A", True),
                InviteCard(INVITE_LAST, "Convite final ≈ 22:10", "Aguardando", 2, "B", True),
            ],
            ready,
        )
        self.assertIn("Rodízio: A", html)
        self.assertIn('<option value="2" selected>B</option>', html)
        self.assertIn('action="/hoje/convite"', html)
        self.assertIn('href="/campanhas"', html)

    def test_invite_cards_escape_campaign_names(self) -> None:
        ready = [Campaign(1, "<i>A</i>", True, 1, 1, 1)]
        html = render_invite_cards(
            [InviteCard(INVITE_FIXED, "Convite das 13:15", "Aguardando", None, "<i>A</i>", True)],
            ready,
        )
        self.assertNotIn("<i>A</i>", html)
        self.assertIn("Rodízio: &lt;i&gt;A&lt;/i&gt;", html)

    def test_styles_do_not_touch_the_shared_panel_card(self) -> None:
        self.assertNotIn(".panel-card", CAMPAIGN_STYLE)
        self.assertNotIn(".panel-card", INVITE_STYLE)
        html = render_campaign_list([], InviteSettings(None, 10), notice=None)
        self.assertIn('class="campaign-settings"', html)
        self.assertNotIn("panel-card", html)

    def test_invite_style_only_reaches_inside_the_invite_section(self) -> None:
        selectors = [
            selector.strip()
            for block in re.findall(r"([^{}]+)\{", INVITE_STYLE)
            for selector in block.split(",")
            if selector.strip()
        ]
        self.assertTrue(selectors)
        for selector in selectors:
            self.assertTrue(selector.startswith("#convites"), selector)

    def test_sent_invite_shows_the_campaign_without_a_form(self) -> None:
        html = render_invite_cards(
            [InviteCard(INVITE_FIXED, "Convite das 13:15", "Enviado", None, "A", False)],
            [],
        )
        self.assertIn("Enviado", html)
        self.assertNotIn("/hoje/convite", html)


if __name__ == "__main__":
    unittest.main()
