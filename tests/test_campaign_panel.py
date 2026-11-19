import io
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from random import Random
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from PIL import Image

from promo_livros.board_store import BoardStore
from promo_livros.campaign_images import save_upload
from promo_livros.campaign_panel import campaign_callbacks
from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST
from promo_livros.campaign_store import CampaignError, CampaignStore
from promo_livros.models import WhatsAppGroup
from promo_livros.send_schedule import parse_schedule

ZONE = ZoneInfo("America/Sao_Paulo")
DAY = "2026-11-03"
GROUPS = (WhatsAppGroup("Black Livros 01", "120363430990609445@g.us"),)


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), (0, 0, 0)).save(buffer, "PNG")
    return buffer.getvalue()


class CampaignPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.board = BoardStore(self.root / "board.sqlite")
        self.board.save_send_schedule(parse_schedule("08:00", "22:00", "40", "45"))
        self.campaigns = CampaignStore(self.root / "board.sqlite")
        self.clock = datetime(2026, 11, 3, 12, 0, tzinfo=ZONE)
        self.config = SimpleNamespace(whatsapp_groups=GROUPS, openai_api_key="sk-test", openai_model="gpt-test")
        self.generated: list[dict] = []
        self.generation_result: list[str] | Exception = ["Gerado um.", "Gerado dois.", "Gerado três."]
        self.panel = campaign_callbacks(
            self.config,
            self.board,
            self.campaigns,
            root=self.root,
            current_day=lambda: DAY,
            now=lambda: self.clock,
            generate_texts=self._fake_generate,
            rng=Random(7),
        )

    def _fake_generate(self, **kwargs) -> list[str]:
        self.generated.append(kwargs)
        if isinstance(self.generation_result, Exception):
            raise self.generation_result
        return self.generation_result

    def tearDown(self) -> None:
        self.campaigns.close()
        self.board.close()
        self.folder.cleanup()

    def _ready(self, name: str) -> int:
        campaign_id = self.campaigns.create(name)
        self.panel["upload"](campaign_id, [_png()])
        self.campaigns.add_text(campaign_id, f"Texto {name}")
        return campaign_id

    def _campaign_files(self, campaign_id: int) -> list[Path]:
        folder = self.root / "data" / "campaigns" / str(campaign_id)
        return list(folder.iterdir()) if folder.exists() else []

    def test_settings_save_only_the_last_invite_offset(self) -> None:
        self.assertEqual(self.panel["save_settings"]({"fixo": ["13:15"], "final": ["20"]}), "/campanhas")
        self.assertEqual(self.board.setting("invite_last_offset_minutes"), "20")
        self.assertIsNone(self.board.setting("invite_fixed_clock"))

    def test_settings_refuse_bad_offsets(self) -> None:
        self.panel["save_settings"]({"final": ["10"]})
        self.panel["save_settings"]({"final": ["999"]})
        self.assertEqual(self.board.setting("invite_last_offset_minutes"), "10")
        self.assertIn("minutos", self.panel["page"]())

    def test_list_page_has_no_fixed_invite_input(self) -> None:
        self.assertNotIn('name="fixo"', self.panel["page"]())

    def test_notify_shows_on_the_next_page(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.panel["notify"]("O envio passa de 40 MB.")
        self.assertIn("O envio passa de 40 MB.", self.panel["detail"](campaign_id))

    def test_notice_shows_once(self) -> None:
        self.panel["save_settings"]({"final": ["20"]})
        self.assertIn("Horário do convite final salvo.", self.panel["page"]())
        self.assertNotIn("Horário do convite final salvo.", self.panel["page"]())

    def test_create_add_text_and_rename(self) -> None:
        target = self.panel["action"]({"acao": ["criar"], "nome": ["Terror"]})
        campaign_id = int(target.rsplit("/", 1)[1])
        self.panel["action"]({"acao": ["texto_novo"], "id": [str(campaign_id)], "corpo": ["Entre!"]})
        self.panel["action"]({"acao": ["renomear"], "id": [str(campaign_id)], "nome": ["Terror BR"]})
        campaign = self.campaigns.campaign(campaign_id)
        self.assertEqual((campaign.name, campaign.text_count), ("Terror BR", 1))

    def test_store_errors_become_notices(self) -> None:
        self.assertEqual(self.panel["action"]({"acao": ["criar"], "nome": ["  "]}), "/campanhas")
        self.assertIn("Dê um nome", self.panel["page"]())
        campaign_id = self.campaigns.create("A")
        self.panel["action"]({"acao": ["texto_novo"], "id": [str(campaign_id)], "corpo": ["x" * 2000]})
        self.assertIn("1024", self.panel["detail"](campaign_id))

    def test_bad_ids_and_actions_are_refused(self) -> None:
        campaign_id = self.campaigns.create("A")
        for raw in ("", "abc", "-1", "²", "1" * 40):
            self.assertEqual(self.panel["action"]({"acao": ["apagar"], "id": [raw]}), "/campanhas")
        self.assertIsNotNone(self.campaigns.campaign(campaign_id))
        target = self.panel["action"]({"acao": ["hackear"], "id": [str(campaign_id)]})
        self.assertEqual(target, f"/campanhas/{campaign_id}")
        self.assertIn("Ação desconhecida.", self.panel["detail"](campaign_id))

    def test_move_and_toggle(self) -> None:
        first = self.campaigns.create("A")
        second = self.campaigns.create("B")
        self.panel["action"]({"acao": ["descer"], "id": [str(first)]})
        self.assertEqual([item.id for item in self.campaigns.campaigns()], [second, first])
        self.panel["action"]({"acao": ["desativar"], "id": [str(first)]})
        self.assertFalse(self.campaigns.campaign(first).active)

    def test_cannot_touch_content_of_another_campaign(self) -> None:
        first = self._ready("A")
        second = self._ready("B")
        foreign_text = self.campaigns.texts(second)[0]
        foreign_image = self.campaigns.images(second)[0]
        self.panel["action"]({"acao": ["texto_apagar"], "id": [str(first)], "texto": [str(foreign_text.id)]})
        self.panel["action"]({"acao": ["texto_editar"], "id": [str(first)], "texto": [str(foreign_text.id)], "corpo": ["x"]})
        self.panel["action"]({"acao": ["foto_apagar"], "id": [str(first)], "foto": [str(foreign_image.id)]})
        self.assertEqual(self.campaigns.text(foreign_text.id).body, "Texto B")
        self.assertIsNotNone(self.campaigns.image(foreign_image.id))
        self.assertEqual(len(self._campaign_files(second)), 1)

    def test_remove_photo_deletes_row_and_file(self) -> None:
        campaign_id = self._ready("A")
        image = self.campaigns.images(campaign_id)[0]
        self.panel["action"]({"acao": ["foto_apagar"], "id": [str(campaign_id)], "foto": [str(image.id)]})
        self.assertIsNone(self.campaigns.image(image.id))
        self.assertEqual(self._campaign_files(campaign_id), [])

    def test_photo_file_error_is_logged_after_the_row_is_gone(self) -> None:
        campaign_id = self._ready("A")
        image = self.campaigns.images(campaign_id)[0]
        with (
            mock.patch("promo_livros.campaign_panel.remove_image", side_effect=PermissionError("secret path")),
            self.assertLogs("promo_livros.campaigns", level="WARNING") as logs,
        ):
            self.panel["action"]({"acao": ["foto_apagar"], "id": [str(campaign_id)], "foto": [str(image.id)]})
        self.assertIsNone(self.campaigns.image(image.id))
        self.assertNotIn("secret path", "".join(logs.output))

    def test_edit_and_remove_text(self) -> None:
        campaign_id = self._ready("A")
        text = self.campaigns.texts(campaign_id)[0]
        self.panel["action"]({"acao": ["texto_editar"], "id": [str(campaign_id)], "texto": [str(text.id)], "corpo": ["Novo"]})
        self.assertEqual(self.campaigns.text(text.id).body, "Novo")
        self.panel["action"]({"acao": ["texto_apagar"], "id": [str(campaign_id)], "texto": [str(text.id)]})
        self.assertIsNone(self.campaigns.text(text.id))

    def test_upload_keeps_the_good_files_and_names_the_bad_ones(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.panel["upload"](campaign_id, [_png(), b"lixo"])
        self.assertEqual(len(self.campaigns.images(campaign_id)), 1)
        page = self.panel["detail"](campaign_id)
        self.assertIn("1 foto salva.", page)
        self.assertIn("Arquivo 2", page)
        image = self.campaigns.images(campaign_id)[0]
        self.assertIsNotNone(self.panel["image"](image.id))

    def test_upload_to_missing_campaign_or_without_files(self) -> None:
        self.assertEqual(self.panel["upload"](999, [_png()]), "/campanhas")
        self.assertFalse((self.root / "data" / "campaigns" / "999").exists())
        campaign_id = self.campaigns.create("A")
        self.assertEqual(self.panel["upload"](campaign_id, []), f"/campanhas/{campaign_id}")
        self.assertIn("Escolha ao menos uma foto.", self.panel["detail"](campaign_id))

    def test_upload_drops_the_file_when_the_campaign_vanishes(self) -> None:
        campaign_id = self.campaigns.create("A")
        real_add = self.campaigns.add_image

        def vanish_then_add(target: int, path: str) -> int:
            self.campaigns.delete(target)
            return real_add(target, path)

        with mock.patch.object(self.campaigns, "add_image", side_effect=vanish_then_add):
            self.assertEqual(self.panel["upload"](campaign_id, [_png()]), "/campanhas")
        self.assertEqual(self._campaign_files(campaign_id), [])

    def test_upload_disk_error_refuses_only_that_file(self) -> None:
        campaign_id = self.campaigns.create("A")
        real_save = save_upload
        calls = {"count": 0}

        def flaky_save(root: Path, target: int, payload: bytes) -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("C:/segredo/pasta")
            return real_save(root, target, payload)

        with (
            mock.patch("promo_livros.campaign_panel.save_upload", side_effect=flaky_save),
            self.assertLogs("promo_livros.campaigns", level="WARNING") as logs,
        ):
            self.panel["upload"](campaign_id, [_png(), _png()])
        self.assertEqual(len(self.campaigns.images(campaign_id)), 1)
        page = self.panel["detail"](campaign_id)
        self.assertIn("1 foto salva.", page)
        self.assertIn("Arquivo 1", page)
        self.assertNotIn("segredo", "".join(logs.output))

    def test_upload_database_error_drops_that_file(self) -> None:
        campaign_id = self.campaigns.create("A")
        real_add = self.campaigns.add_image
        calls = {"count": 0}

        def busy_then_add(target: int, path: str) -> int:
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return real_add(target, path)

        with (
            mock.patch.object(self.campaigns, "add_image", side_effect=busy_then_add),
            self.assertLogs("promo_livros.campaigns", level="WARNING"),
        ):
            self.assertEqual(self.panel["upload"](campaign_id, [_png(), _png()]), f"/campanhas/{campaign_id}")
        self.assertEqual(len(self.campaigns.images(campaign_id)), 1)
        self.assertEqual(len(self._campaign_files(campaign_id)), 1)
        self.assertIn("Arquivo 1", self.panel["detail"](campaign_id))

    def test_out_of_range_ids_are_not_found(self) -> None:
        huge = 10**30
        self.assertIsNone(self.panel["detail"](huge))
        self.assertIsNone(self.panel["image"](huge))
        self.assertEqual(self.panel["upload"](huge, [_png()]), "/campanhas")
        self.assertIsNone(self.panel["detail"](0))
        self.assertIsNone(self.panel["image"](-1))

    def test_image_read_failure_returns_none(self) -> None:
        campaign_id = self._ready("A")
        image = self.campaigns.images(campaign_id)[0]
        self.assertIsNone(self.panel["image"](999))
        with (
            mock.patch("promo_livros.campaign_panel.read_image", side_effect=OSError("share down")),
            self.assertLogs("promo_livros.campaigns", level="WARNING"),
        ):
            self.assertIsNone(self.panel["image"](image.id))

    def test_detail_of_missing_campaign_is_none(self) -> None:
        self.assertIsNone(self.panel["detail"](999))

    def test_delete_removes_the_folder(self) -> None:
        campaign_id = self._ready("A")
        self.panel["action"]({"acao": ["apagar"], "id": [str(campaign_id)]})
        self.assertIsNone(self.campaigns.campaign(campaign_id))
        self.assertFalse((self.root / "data" / "campaigns" / str(campaign_id)).exists())

    def _fixed(self, name: str, clock: str, valid_until: str | None = None) -> int:
        campaign_id = self._ready(name)
        self.campaigns.set_schedule(campaign_id, clock, valid_until)
        return campaign_id

    def test_invite_cards_predict_the_rotation(self) -> None:
        self._ready("A")
        self._ready("B")
        html = self.panel["invites"]()
        self.assertIn("Rodízio: A", html)
        self.assertIn("Convite final ≈ 22:10", html)
        self.assertNotIn("Convite no horário", html)

    def test_invite_cards_do_not_write_to_the_database(self) -> None:
        self._ready("A")
        self._fixed("F", "13:15")
        self.panel["invites"]()
        self.assertIsNone(self.campaigns.peek_run(DAY, INVITE_LAST))
        self.assertIsNone(self.campaigns.peek_clock_run(DAY, 2))

    def test_fixed_campaigns_get_their_own_cards(self) -> None:
        self._fixed("Fixa Tarde", "13:15")
        self._fixed("Fixa Manhã", "09:00")
        html = self.panel["invites"]()
        self.assertIn("Fixa Tarde às 13:15", html)
        self.assertLess(html.index("Fixa Manhã às 09:00"), html.index("Fixa Tarde às 13:15"))
        self.assertIn("Aguardando", html.split("Fixa Tarde às 13:15", 1)[1])

    def test_fixed_campaign_is_not_offered_in_the_rotation(self) -> None:
        self._ready("Rotativa")
        fixed = self._fixed("Fixa", "13:15")
        html = self.panel["invites"]()
        self.assertNotIn(f'<option value="{fixed}"', html)
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": [str(fixed)]}), "Essa campanha não está pronta.")

    def test_expired_campaign_has_no_card(self) -> None:
        self._fixed("Velha", "13:15", valid_until="2026-11-02")
        self.assertNotIn("Velha", self.panel["invites"]())

    def test_fixed_missed_shows_as_missed(self) -> None:
        self._fixed("Fixa", "10:00")
        self.assertIn("Não saiu hoje", self.panel["invites"]())

    def test_fixed_run_states_show_on_the_card(self) -> None:
        sent = self._fixed("Enviada", "09:00")
        skipped = self._fixed("Pulada", "09:30")
        self.campaigns.mark_run_sent(self.campaigns.run_for_clock(DAY, sent, "09:00").id, "2026-11-03T09:00:00-03:00")
        self.campaigns.skip_run(self.campaigns.run_for_clock(DAY, skipped, "09:30").id)
        html = self.panel["invites"]()
        self.assertIn("Enviado", html)
        self.assertIn("Não saiu hoje", html)

    def test_missed_fixed_invite_does_not_consume_the_rotation(self) -> None:
        self._fixed("Fixa", "10:00")
        self._ready("A")
        self._ready("B")
        html = self.panel["invites"]()
        self.assertIn("Rodízio: A", html)
        self.assertNotIn("Rodízio: B", html)

    def test_manual_choice_shows_selected(self) -> None:
        self._ready("A")
        second = self._ready("B")
        self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": [str(second)]})
        html = self.panel["invites"]()
        self.assertIn(f'<option value="{second}" selected>B</option>', html)

    def test_last_invite_sending_and_skipped_labels(self) -> None:
        campaign_id = self._ready("A")
        last = self.campaigns.run_for(DAY, INVITE_LAST)
        image = self.campaigns.images(campaign_id)[0]
        text = self.campaigns.texts(campaign_id)[0]
        self.campaigns.lock_content(last.id, campaign_id, image.id, text.id, "2026-11-03T22:10:00-03:00")
        self.assertIn("Enviando 0/1", self.panel["invites"]())
        self.campaigns.skip_run(last.id)
        self.assertIn("Pulado: nenhuma campanha pronta", self.panel["invites"]())

    def test_choose_only_while_pending(self) -> None:
        campaign_id = self._ready("A")
        notice = self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": [str(campaign_id)]})
        self.assertEqual(notice, "Campanha do convite trocada.")
        run = self.campaigns.run_for(DAY, INVITE_LAST)
        self.assertEqual((run.campaign_id, run.manual), (campaign_id, True))
        self.campaigns.mark_run_sent(run.id, "2026-11-03T22:10:00-03:00")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": [""]}), "Esse convite já saiu.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": ["999"]}), "Essa campanha não está pronta.")

    def test_choose_refuses_unknown_kind_and_bad_ids(self) -> None:
        self._ready("A")
        self.assertEqual(self.panel["choose"]({"tipo": ["outro"], "campanha": [""]}), "Convite desconhecido.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": [""]}), "Convite desconhecido.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": ["²"]}), "Essa campanha não está pronta.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": [""]}), "O convite volta para o rodízio.")

    # Agenda da campanha

    def test_schedule_action_saves_fixed_clock_and_validity(self) -> None:
        campaign_id = self.campaigns.create("A")
        target = self.panel["action"](
            {"acao": ["agenda"], "id": [str(campaign_id)], "fixed_clock": ["13:15"], "valid_until": ["2026-12-31"]}
        )
        self.assertEqual(target, f"/campanhas/{campaign_id}")
        campaign = self.campaigns.campaign(campaign_id)
        self.assertEqual((campaign.fixed_clock, campaign.valid_until), ("13:15", "2026-12-31"))
        self.assertIn("Agenda salva.", self.panel["detail"](campaign_id))

    def test_schedule_action_clears_values_and_refuses_bad_ones(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.campaigns.set_schedule(campaign_id, "13:15", "2026-12-31")
        self.panel["action"]({"acao": ["agenda"], "id": [str(campaign_id)], "fixed_clock": ["25:00"], "valid_until": [""]})
        self.assertEqual(self.campaigns.campaign(campaign_id).fixed_clock, "13:15")
        self.panel["action"]({"acao": ["agenda"], "id": [str(campaign_id)], "fixed_clock": [""], "valid_until": ["2026-13-40"]})
        self.assertEqual(self.campaigns.campaign(campaign_id).valid_until, "2026-12-31")
        self.panel["action"]({"acao": ["agenda"], "id": [str(campaign_id)], "fixed_clock": [""], "valid_until": [""]})
        campaign = self.campaigns.campaign(campaign_id)
        self.assertEqual((campaign.fixed_clock, campaign.valid_until), (None, None))

    def test_list_shows_status_labels(self) -> None:
        self._fixed("Fixa", "13:15")
        self._ready("Rotativa")
        self._fixed("Velha", "13:15", valid_until="2026-11-02")
        self.campaigns.create("Vazia")
        page = self.panel["page"]()
        for label in ("Fixa 13:15", "Rotativa", "Vencida", "Incompleta"):
            self.assertIn(label, page)

    # Gerar textos com IA

    def test_generate_adds_texts_and_goes_back_to_the_campaign(self) -> None:
        campaign_id = self.campaigns.create("Grupo X")
        target = self.panel["generate"]({"id": [str(campaign_id)], "count": ["3"]})
        self.assertEqual(target, f"/campanhas/{campaign_id}")
        self.assertEqual([text.body for text in self.campaigns.texts(campaign_id)], ["Gerado um.", "Gerado dois.", "Gerado três."])
        self.assertEqual(
            self.generated,
            [{"api_key": "sk-test", "model": "gpt-test", "campaign_name": "Grupo X", "count": 3}],
        )
        self.assertIn("3 textos gerados", self.panel["detail"](campaign_id))

    def test_generate_clamps_the_count(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.panel["generate"]({"id": [str(campaign_id)], "count": ["99"]})
        self.panel["generate"]({"id": [str(campaign_id)], "count": ["1"]})
        self.assertEqual([call["count"] for call in self.generated], [10, 3])

    def test_generate_refuses_bad_input_without_calling_the_api(self) -> None:
        campaign_id = self.campaigns.create("A")
        for raw in ("", "abc", "-3", "²", "1000"):
            self.assertEqual(self.panel["generate"]({"id": [str(campaign_id)], "count": [raw]}), f"/campanhas/{campaign_id}")
        self.assertEqual(self.panel["generate"]({"id": ["999"], "count": ["3"]}), "/campanhas")
        self.assertEqual(self.panel["generate"]({"id": [""], "count": ["3"]}), "/campanhas")
        self.assertEqual(self.generated, [])

    def test_generate_without_a_key_does_not_call_the_api(self) -> None:
        self.config.openai_api_key = "  "
        campaign_id = self.campaigns.create("A")
        self.panel["generate"]({"id": [str(campaign_id)], "count": ["3"]})
        self.assertEqual(self.generated, [])
        page = self.panel["detail"](campaign_id)
        self.assertIn("OPENAI_API_KEY", page)
        self.assertRegex(page, r'<button class="ghost" type="submit" disabled>Gerar textos com IA')

    def test_generate_button_is_enabled_with_a_key(self) -> None:
        campaign_id = self.campaigns.create("A")
        page = self.panel["detail"](campaign_id)
        self.assertIn('action="/campanhas/gerar"', page)
        self.assertNotRegex(page, r'type="submit" disabled>Gerar textos com IA')

    def test_generate_api_failure_becomes_a_notice_and_adds_nothing(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.generation_result = CampaignError("A OpenAI não respondeu.")
        self.assertEqual(self.panel["generate"]({"id": [str(campaign_id)], "count": ["3"]}), f"/campanhas/{campaign_id}")
        self.assertEqual(self.campaigns.texts(campaign_id), [])
        self.assertIn("A OpenAI não respondeu.", self.panel["detail"](campaign_id))

    # Troca de conteúdo de post de campanha na fila

    def _queue_campaign_post(self, campaign_id: int | None = None, clock: str = "11:00") -> int:
        if campaign_id is None:
            return self.board.add_campaign_post(DAY, clock)
        image = self.campaigns.images(campaign_id)[0]
        text = self.campaigns.texts(campaign_id)[0]
        return self.board.add_campaign_post(
            DAY,
            clock,
            campaign_id=campaign_id,
            image_id=image.id,
            text_id=text.id,
            caption=text.body,
            image_path=image.path,
            locked_at="2026-11-03T08:00:00-03:00",
        )

    def test_queue_campaign_posts_show_selects_with_escaped_content(self) -> None:
        first = self._ready("<b>A</b>")
        self._ready("B")
        post_id = self._queue_campaign_post(first)
        html = self.panel["invites"]()
        self.assertIn('action="/hoje/campanha-post"', html)
        self.assertIn(f'name="post_id" value="{post_id}"', html)
        self.assertIn("Campanha às 11:00", html)
        self.assertIn(f'<option value="{first}" selected>&lt;b&gt;A&lt;/b&gt;</option>', html)
        self.assertNotIn("<b>A</b>", html)
        self.assertIn("Texto &lt;b&gt;A&lt;/b&gt;", html)

    def test_no_campaign_selects_without_campaign_posts(self) -> None:
        self._ready("A")
        html = self.panel["invites"]()
        self.assertNotIn("/hoje/campanha-post", html)
        self.assertNotIn("Campanhas na fila", html)

    def test_grade_row_of_a_campaign_post_carries_the_swap_form(self) -> None:
        from promo_livros.dashboard_belt import _rows

        first = self._ready("<b>A</b>")
        post_id = self._queue_campaign_post(first)
        empty_slot_id = self.board.add_campaign_post(DAY, "12:00")
        feed = self.board.day_feed(DAY)
        campaign_feed = next(item for item in feed if item.id == post_id)
        self.assertEqual((campaign_feed.post_kind, campaign_feed.campaign_id), ("campaign", first))
        self.assertIsNotNone(campaign_feed.image_id)
        self.assertIsNotNone(campaign_feed.text_id)

        forms = self.panel["post_forms"]()
        self.assertEqual(set(forms), {post_id, empty_slot_id})
        html = _rows(feed, feed, "todas", (), None, "unknown", None, forms)

        self.assertIn('action="/hoje/campanha-post"', html)
        self.assertIn(f'name="post_id" value="{post_id}"', html)
        self.assertIn(f'<option value="{first}" selected>&lt;b&gt;A&lt;/b&gt;</option>', html)
        self.assertNotIn("<b>A</b>", html)

    def test_empty_queue_slot_asks_for_a_campaign(self) -> None:
        self._ready("A")
        self._queue_campaign_post(None)
        html = self.panel["invites"]()
        self.assertIn("Escolha a campanha", html)

    def test_swap_post_changes_campaign_and_content(self) -> None:
        first = self._ready("A")
        second = self._ready("B")
        post_id = self._queue_campaign_post(first)
        notice = self.panel["swap_post"]({"post_id": [str(post_id)], "campaign_id": [str(second)], "image_id": [""], "text_id": [""]})
        self.assertEqual(notice, "Post de campanha trocado.")
        post = self.board.post_by_id(post_id)
        image = self.campaigns.images(second)[0]
        self.assertEqual((post.campaign_id, post.image_id, post.caption, post.image_path), (second, image.id, "Texto B", image.path))
        self.assertEqual(post.campaign_locked_at, "2026-11-03T08:00:00-03:00")

    def test_swap_post_picks_specific_image_and_text(self) -> None:
        campaign_id = self._ready("A")
        self.panel["upload"](campaign_id, [_png()])
        extra_text = self.campaigns.add_text(campaign_id, "Segundo texto")
        post_id = self._queue_campaign_post(campaign_id)
        wanted_image = self.campaigns.images(campaign_id)[1]
        self.panel["swap_post"](
            {"post_id": [str(post_id)], "campaign_id": [str(campaign_id)], "image_id": [str(wanted_image.id)], "text_id": [str(extra_text)]}
        )
        post = self.board.post_by_id(post_id)
        self.assertEqual((post.image_id, post.text_id, post.caption, post.image_path), (wanted_image.id, extra_text, "Segundo texto", wanted_image.path))

    def test_swap_post_fills_an_empty_slot_and_stamps_the_lock(self) -> None:
        campaign_id = self._ready("A")
        post_id = self._queue_campaign_post(None)
        self.panel["swap_post"]({"post_id": [str(post_id)], "campaign_id": [str(campaign_id)]})
        post = self.board.post_by_id(post_id)
        self.assertEqual(post.campaign_id, campaign_id)
        self.assertEqual(post.campaign_locked_at, self.clock.isoformat(timespec="seconds"))

    def test_swap_post_refuses_foreign_content_and_unready_campaigns(self) -> None:
        first = self._ready("A")
        second = self._ready("B")
        post_id = self._queue_campaign_post(first)
        foreign_image = self.campaigns.images(second)[0]
        foreign_text = self.campaigns.texts(second)[0]
        base = {"post_id": [str(post_id)], "campaign_id": [str(first)]}
        self.assertIn("não é da campanha", self.panel["swap_post"]({**base, "image_id": [str(foreign_image.id)]}))
        self.assertIn("não é da campanha", self.panel["swap_post"]({**base, "text_id": [str(foreign_text.id)]}))
        self.assertEqual(self.panel["swap_post"]({**base, "campaign_id": ["999"]}), "Essa campanha não está pronta.")
        self.assertEqual(self.panel["swap_post"]({**base, "campaign_id": ["²"]}), "Essa campanha não está pronta.")
        fixed = self._fixed("F", "13:15")
        self.assertEqual(self.panel["swap_post"]({**base, "campaign_id": [str(fixed)]}), "Essa campanha não está pronta.")
        self.assertEqual(self.board.post_by_id(post_id).campaign_id, first)

    def test_swap_post_refuses_missing_sent_and_book_posts(self) -> None:
        campaign_id = self._ready("A")
        form = {"campaign_id": [str(campaign_id)]}
        self.assertEqual(self.panel["swap_post"]({**form, "post_id": ["999"]}), "Esse post não está mais na fila.")
        self.assertEqual(self.panel["swap_post"]({**form, "post_id": ["x"]}), "Esse post não está mais na fila.")
        post_id = self._queue_campaign_post(campaign_id)
        self.board.cancel(DAY, post_id)
        self.assertEqual(self.panel["swap_post"]({**form, "post_id": [str(post_id)]}), "Esse post não está mais na fila.")


if __name__ == "__main__":
    unittest.main()
