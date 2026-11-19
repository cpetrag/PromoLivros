import io
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from PIL import Image

from promo_livros.board_store import BoardStore
from promo_livros.campaign_images import save_upload
from promo_livros.campaign_panel import campaign_callbacks
from promo_livros.campaign_rules import INVITE_FIXED, INVITE_LAST
from promo_livros.campaign_store import CampaignStore
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
        self.panel = campaign_callbacks(
            SimpleNamespace(whatsapp_groups=GROUPS),
            self.board,
            self.campaigns,
            root=self.root,
            current_day=lambda: DAY,
            now=lambda: self.clock,
        )

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

    def test_settings_refuse_a_queue_clock(self) -> None:
        self.assertEqual(self.panel["save_settings"]({"fixo": ["08:40"], "final": ["10"]}), "/campanhas")
        self.assertIsNone(self.board.setting("invite_fixed_clock"))
        self.assertIn("horário da fila", self.panel["page"]())
        self.panel["save_settings"]({"fixo": ["13:15"], "final": ["20"]})
        self.assertEqual(self.board.setting("invite_fixed_clock"), "13:15")
        self.assertEqual(self.board.setting("invite_last_offset_minutes"), "20")

    def test_settings_refuse_bad_values_and_clear_the_fixed_clock(self) -> None:
        self.panel["save_settings"]({"fixo": ["25:00"], "final": ["10"]})
        self.panel["save_settings"]({"fixo": ["13:15"], "final": ["999"]})
        self.panel["save_settings"]({"fixo": ["١٣:١٥"], "final": ["10"]})
        self.panel["save_settings"]({"fixo": ["1٣:15"], "final": ["10"]})
        self.assertIsNone(self.board.setting("invite_fixed_clock"))
        self.panel["save_settings"]({"fixo": [""], "final": ["10"]})
        self.assertEqual(self.board.setting("invite_fixed_clock"), "")

    def test_notify_shows_on_the_next_page(self) -> None:
        campaign_id = self.campaigns.create("A")
        self.panel["notify"]("O envio passa de 40 MB.")
        self.assertIn("O envio passa de 40 MB.", self.panel["detail"](campaign_id))

    def test_notice_shows_once(self) -> None:
        self.panel["save_settings"]({"fixo": ["13:15"], "final": ["20"]})
        self.assertIn("Horários dos convites salvos.", self.panel["page"]())
        self.assertNotIn("Horários dos convites salvos.", self.panel["page"]())

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

    def test_invite_cards_predict_the_rotation(self) -> None:
        self.board.put_setting("invite_fixed_clock", "13:15")
        self._ready("A")
        self._ready("B")
        html = self.panel["invites"]()
        self.assertIn("Convite das 13:15", html)
        self.assertIn("Rodízio: A", html)
        self.assertIn("Rodízio: B", html)
        self.assertIn("Convite final ≈ 22:10", html)

    def test_invite_cards_do_not_write_to_the_database(self) -> None:
        self.board.put_setting("invite_fixed_clock", "13:15")
        self._ready("A")
        self.panel["invites"]()
        self.assertIsNone(self.campaigns.peek_run(DAY, INVITE_FIXED))
        self.assertIsNone(self.campaigns.peek_run(DAY, INVITE_LAST))

    def test_fixed_off_shows_as_off(self) -> None:
        self.assertIn("Desligado", self.panel["invites"]())

    def test_fixed_missed_shows_as_missed(self) -> None:
        self.board.put_setting("invite_fixed_clock", "10:00")
        self._ready("A")
        self.assertIn("Não saiu hoje", self.panel["invites"]())

    def test_missed_fixed_invite_does_not_consume_the_rotation(self) -> None:
        self.board.put_setting("invite_fixed_clock", "10:00")
        self._ready("A")
        self._ready("B")
        html = self.panel["invites"]()
        self.assertIn("Não saiu hoje", html)
        self.assertIn("Rodízio: A", html)
        self.assertNotIn("Rodízio: B", html)

    def test_manual_choice_shows_selected_and_moves_the_preview(self) -> None:
        self.board.put_setting("invite_fixed_clock", "13:15")
        self._ready("A")
        second = self._ready("B")
        self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": [str(second)]})
        html = self.panel["invites"]()
        self.assertIn(f'<option value="{second}" selected>B</option>', html)
        self.assertIn("Rodízio: A", html)
        self.assertNotIn("Rodízio: B", html)

    def test_sending_and_skipped_labels(self) -> None:
        campaign_id = self._ready("A")
        fixed = self.campaigns.run_for(DAY, INVITE_FIXED)
        image = self.campaigns.images(campaign_id)[0]
        text = self.campaigns.texts(campaign_id)[0]
        self.campaigns.lock_content(fixed.id, campaign_id, image.id, text.id, "2026-11-03T13:15:00-03:00")
        self.campaigns.skip_run(self.campaigns.run_for(DAY, INVITE_LAST).id)
        html = self.panel["invites"]()
        self.assertIn("Enviando 0/1", html)
        self.assertIn("Pulado: nenhuma campanha pronta", html)

    def test_choose_only_while_pending(self) -> None:
        campaign_id = self._ready("A")
        notice = self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": [str(campaign_id)]})
        self.assertEqual(notice, "Campanha do convite trocada.")
        run = self.campaigns.run_for(DAY, INVITE_FIXED)
        self.assertEqual((run.campaign_id, run.manual), (campaign_id, True))
        self.campaigns.mark_run_sent(run.id, "2026-11-03T13:15:00-03:00")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": [""]}), "Esse convite já saiu.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_FIXED], "campanha": ["999"]}), "Essa campanha não está pronta.")

    def test_choose_refuses_unknown_kind_and_bad_ids(self) -> None:
        self._ready("A")
        self.assertEqual(self.panel["choose"]({"tipo": ["outro"], "campanha": [""]}), "Convite desconhecido.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": ["²"]}), "Essa campanha não está pronta.")
        self.assertEqual(self.panel["choose"]({"tipo": [INVITE_LAST], "campanha": [""]}), "O convite volta para o rodízio.")


if __name__ == "__main__":
    unittest.main()
