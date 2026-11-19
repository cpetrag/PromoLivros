import unittest

import re

from promo_livros.campaign_pages import (
    CAMPAIGN_STYLE,
    INVITE_STYLE,
    InviteCard,
    QueuePostCard,
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
        self.assertIn("Rotativa", html)
        self.assertNotIn('name="fixo"', html)
        self.assertIn('action="/campanhas/config"', html)
        self.assertIn("Salvo &amp; pronto", html)
        self.assertIn('href="/campanhas" aria-current="page"', html)

    def test_list_marks_inactive_campaigns(self) -> None:
        html = render_campaign_list([Campaign(1, "Velha", False, 1, 1, 1)], InviteSettings(None, 10), notice=None)
        self.assertIn("Desativada", html)

    def test_list_labels_fixed_rotating_expired_and_incomplete(self) -> None:
        html = render_campaign_list(
            [
                Campaign(1, "A", True, 1, 1, 1, fixed_clock="13:15"),
                Campaign(2, "B", True, 2, 1, 1),
                Campaign(3, "C", True, 3, 1, 1, valid_until="2026-11-02"),
                Campaign(4, "D", True, 4, 0, 1, fixed_clock="09:00"),
            ],
            InviteSettings(None, 10),
            notice=None,
            day="2026-11-03",
        )
        for label in ("Fixa 13:15", "Rotativa", "Vencida", "Incompleta"):
            self.assertIn(label, html)

    def test_detail_has_schedule_form_with_current_values(self) -> None:
        html = render_campaign_detail(
            Campaign(3, "Kindle", True, 1, 1, 1, fixed_clock="13:15", valid_until="2026-12-31"),
            [],
            [],
            notice=None,
        )
        self.assertIn('name="fixed_clock" value="13:15"', html)
        self.assertIn('name="valid_until" type="date" value="2026-12-31"', html)
        self.assertIn('value="agenda"', html)

    def test_detail_generate_button_follows_the_key(self) -> None:
        campaign = Campaign(3, "Kindle", True, 1, 0, 0)
        enabled = render_campaign_detail(campaign, [], [], notice=None, can_generate=True)
        disabled = render_campaign_detail(campaign, [], [], notice=None)
        self.assertIn('action="/campanhas/gerar"', enabled)
        self.assertIn('min="3" max="10"', enabled)
        self.assertNotIn("disabled>Gerar textos com IA", enabled)
        self.assertIn("disabled>Gerar textos com IA", disabled)
        self.assertIn("OPENAI_API_KEY", disabled)

    def test_queue_posts_render_selects_and_escape_everything(self) -> None:
        ready = [Campaign(1, "<i>A</i>", True, 1, 1, 1)]
        post = QueuePostCard(
            post_id=7,
            clock="11:00",
            campaign_id=1,
            image_id=2,
            text_id=3,
            images=(CampaignImage(2, 1, "a.jpg"),),
            texts=(CampaignText(3, 1, "<script>x</script>"),),
        )
        html = render_invite_cards([], ready, (post,))
        self.assertIn('action="/hoje/campanha-post"', html)
        self.assertIn('name="post_id" value="7"', html)
        self.assertIn('<option value="2" selected>Foto 1</option>', html)
        self.assertIn('<option value="3" selected>&lt;script&gt;x&lt;/script&gt;</option>', html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<i>A</i>", html)

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
