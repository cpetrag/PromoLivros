"""Escolhe a campanha rotativa, a foto e o texto de cada slot de campanha da fila."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from random import Random

from promo_livros.campaign_rules import RotationEntry, pick_avoiding, rotation_order
from promo_livros.campaign_store import CampaignStore


def _local_now() -> datetime:
    return datetime.now().astimezone()


@dataclass(frozen=True)
class CampaignQueueContext:
    """O que a montagem da fila precisa para preencher slots de campanha."""

    store: CampaignStore
    rng: Random = field(default_factory=Random)
    now: Callable[[], datetime] = _local_now


@dataclass(frozen=True)
class CampaignPostPlan:
    """Conteúdo de um slot. Sem campanha pronta, o slot vira post vazio para ser resolvido no envio."""

    clock: str
    campaign_id: int | None = None
    image_id: int | None = None
    text_id: int | None = None
    caption: str = ""
    image_path: str = ""


def plan_campaign_posts(
    context: CampaignQueueContext, day: str, clocks: list[str]
) -> tuple[list[CampaignPostPlan], list[str]]:
    """Um plano por horário, na ordem dos horários, e os avisos de slots sem campanha.

    Chame depois de limpar a fila do dia: o cursor do rodízio lê os posts que já estão nela.
    O cursor também anda aqui dentro, porque os planos ainda não foram gravados.
    """
    store = context.store
    ready = store.ready_rotating(day)
    entries = [RotationEntry(item.id, item.position) for item in ready]
    positions = {entry.campaign_id: entry for entry in entries}
    cursor = store.last_used_rotating()
    last_content: dict[int, tuple[int | None, int | None]] = {}
    plans: list[CampaignPostPlan] = []
    warnings: list[str] = []
    for clock in sorted(clocks):
        plan = _plan_one(context, clock, rotation_order(entries, cursor), last_content)
        if plan.campaign_id is None:
            warnings.append(f"{clock}: sem campanha rotativa pronta")
        else:
            cursor = positions[plan.campaign_id]
        plans.append(plan)
    return plans, warnings


def _plan_one(
    context: CampaignQueueContext,
    clock: str,
    order: list[int],
    last_content: dict[int, tuple[int | None, int | None]],
) -> CampaignPostPlan:
    store = context.store
    for campaign_id in order:
        images = store.images(campaign_id)
        texts = store.texts(campaign_id)
        if not images or not texts:
            continue
        if campaign_id not in last_content:
            last_content[campaign_id] = store.last_content(campaign_id)
        last_image_id, last_text_id = last_content[campaign_id]
        image_id = pick_avoiding([image.id for image in images], last_image_id, context.rng)
        text_id = pick_avoiding([text.id for text in texts], last_text_id, context.rng)
        last_content[campaign_id] = (image_id, text_id)
        return CampaignPostPlan(
            clock=clock,
            campaign_id=campaign_id,
            image_id=image_id,
            text_id=text_id,
            caption=next(text.body for text in texts if text.id == text_id),
            image_path=next(image.path for image in images if image.id == image_id),
        )
    return CampaignPostPlan(clock=clock)
