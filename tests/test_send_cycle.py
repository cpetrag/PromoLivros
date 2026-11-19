from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from promo_livros import send_cycle
from promo_livros.send_cycle import CycleResult, run_send_cycle

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
ROOT = Path("project-root")


class FakeBoard:
    def __init__(self, group_sent_at: str | None = None) -> None:
        self.group_sent_at = group_sent_at

    def last_group_sent_at(self) -> str | None:
        return self.group_sent_at

    def send_schedule(self) -> SimpleNamespace:
        return SimpleNamespace(group_gap_seconds=90)


class FakePolls:
    def __init__(self, outbound_at: str | None = None) -> None:
        self.outbound_at = outbound_at

    def last_outbound_at(self) -> str | None:
        return self.outbound_at


class FakeCampaigns:
    def __init__(self, sent_at: str | None = None) -> None:
        self.sent_at = sent_at

    def last_sent_at(self) -> str | None:
        return self.sent_at


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, object]]:
    seen: dict[str, dict[str, object]] = {}

    def invite(config, board, campaigns, client, *, root, now, quiet_since):
        seen["invite"] = {"root": root, "quiet_since": quiet_since}
        return "idle"

    def queue(config, board, client, *, root, now, quiet_since):
        seen["queue"] = {"root": root, "quiet_since": quiet_since}
        return "idle"

    def poll(polls, client, now, *, gap_seconds, other_sent_at):
        seen["poll"] = {"gap_seconds": gap_seconds, "other_sent_at": other_sent_at}
        return "idle"

    monkeypatch.setattr(send_cycle, "publish_due_invite", invite)
    monkeypatch.setattr(send_cycle, "publish_due", queue)
    monkeypatch.setattr(send_cycle, "advance_polls", poll)
    return seen


def _run(board: FakeBoard, polls: FakePolls, campaigns: FakeCampaigns) -> CycleResult:
    return run_send_cycle(object(), board, polls, campaigns, object(), root=ROOT, now=NOW)


def test_invite_waits_for_polls_and_gets_project_root(calls) -> None:
    _run(FakeBoard(), FakePolls("2026-11-04T11:59:00+00:00"), FakeCampaigns())

    assert calls["invite"] == {"root": ROOT, "quiet_since": "2026-11-04T11:59:00+00:00"}


def test_queue_waits_for_latest_invite_or_poll(calls) -> None:
    _run(FakeBoard(), FakePolls("2026-11-04T11:58:00+00:00"), FakeCampaigns("2026-11-04T11:59:30+00:00"))

    assert calls["queue"]["quiet_since"] == "2026-11-04T11:59:30+00:00"
    assert calls["queue"]["root"] == ROOT


def test_polls_wait_for_latest_queue_or_invite(calls) -> None:
    _run(FakeBoard("2026-11-04T11:59:50+00:00"), FakePolls(), FakeCampaigns("2026-11-04T11:59:00+00:00"))

    assert calls["poll"] == {"gap_seconds": 90, "other_sent_at": "2026-11-04T11:59:50+00:00"}


def test_stamps_are_read_after_each_step(monkeypatch: pytest.MonkeyPatch, calls) -> None:
    campaigns = FakeCampaigns()
    board = FakeBoard()

    def invite_sends(config, board_arg, campaigns_arg, client, *, root, now, quiet_since):
        campaigns_arg.sent_at = "2026-11-04T12:00:00+00:00"
        return "sent"

    monkeypatch.setattr(send_cycle, "publish_due_invite", invite_sends)

    result = _run(board, FakePolls(), campaigns)

    assert result.invite == "sent"
    assert calls["queue"]["quiet_since"] == "2026-11-04T12:00:00+00:00"
    assert calls["poll"]["other_sent_at"] == "2026-11-04T12:00:00+00:00"


def test_failed_invite_does_not_block_queue_or_polls(monkeypatch: pytest.MonkeyPatch, calls, caplog) -> None:
    def invite_breaks(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(send_cycle, "publish_due_invite", invite_breaks)

    result = _run(FakeBoard(), FakePolls(), FakeCampaigns())

    assert result == CycleResult(invite="failed", queue="idle", poll="idle")
    assert result.failed
    assert "O ciclo do convite falhou." in caplog.text


def test_failed_queue_still_runs_polls(monkeypatch: pytest.MonkeyPatch, calls) -> None:
    def queue_breaks(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(send_cycle, "publish_due", queue_breaks)

    result = _run(FakeBoard(), FakePolls(), FakeCampaigns())

    assert result == CycleResult(invite="idle", queue="failed", poll="idle")
    assert "poll" in calls


def test_quiet_cycle_is_not_failed() -> None:
    assert not CycleResult(invite="idle", queue="sent", poll="waiting").failed
