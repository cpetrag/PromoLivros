import importlib.util
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "enviar_fila.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("enviar_fila_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Closable:
    opened: list["_Closable"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.closed = False
        _Closable.opened.append(self)

    def close(self) -> None:
        self.closed = True


class SendCycleOpeningTests(unittest.TestCase):
    def setUp(self) -> None:
        _Closable.opened = []
        self.script = _load_script()
        self.config = SimpleNamespace(sqlite_path=Path("unused.sqlite"))
        self.logger = logging.getLogger("test.enviar_fila")

    def test_failure_opening_a_store_closes_the_ones_already_open(self) -> None:
        with (
            mock.patch.object(self.script, "BoardStore", _Closable),
            mock.patch.object(self.script, "PollStore", _Closable),
            mock.patch.object(self.script, "CampaignStore", side_effect=RuntimeError("disco")),
            self.assertRaises(RuntimeError),
        ):
            self.script._send_once(self.config, self.logger, 0.0)
        self.assertEqual(len(_Closable.opened), 2)
        self.assertTrue(all(item.closed for item in _Closable.opened))

    def test_everything_is_closed_after_a_cycle(self) -> None:
        result = object()
        waha = SimpleNamespace(from_config=lambda _config: _Closable())
        with (
            mock.patch.object(self.script, "BoardStore", _Closable),
            mock.patch.object(self.script, "PollStore", _Closable),
            mock.patch.object(self.script, "CampaignStore", _Closable),
            mock.patch.object(self.script, "WahaClient", waha),
            mock.patch.object(self.script, "_refresh_links", return_value=5.0),
            mock.patch.object(self.script, "zone", return_value=None),
            mock.patch.object(self.script, "run_send_cycle", return_value=result),
        ):
            self.config.schedule = SimpleNamespace(timezone="America/Sao_Paulo")
            self.assertEqual(self.script._send_once(self.config, self.logger, 0.0), (result, 5.0))
        self.assertEqual(len(_Closable.opened), 4)
        self.assertTrue(all(item.closed for item in _Closable.opened))


if __name__ == "__main__":
    unittest.main()
