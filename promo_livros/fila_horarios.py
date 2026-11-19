"""Regras de horário da fila agendada. Recebe (id, horário) e devolve só o que muda."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_LAST_MINUTE = 23 * 60 + 59
_MIN_INTERVAL = 5
_MAX_INTERVAL = 180
_MIN_SHIFT = -60
_MAX_SHIFT = 180

Fila = list[tuple[int, str]]


@dataclass(frozen=True)
class Limites:
    agora: str
    fim: str
    permitir_fora: bool = False


@dataclass(frozen=True)
class Fora:
    count: int
    last: str
    fit_interval: int | None


@dataclass(frozen=True)
class Resultado:
    clocks: dict[int, str] = field(default_factory=dict)
    fora: Fora | None = None
    erro: str = ""

    @property
    def ok(self) -> bool:
        return not self.erro and self.fora is None


def trocar(fila: Fila, a: int, b: int, limites: Limites) -> Resultado:
    atual = dict(fila)
    if a not in atual or b not in atual:
        return _sumiu()
    if a == b:
        return Resultado()
    return _validar(fila, {a: atual[b], b: atual[a]}, limites)


def antes(fila: Fila, post_id: int, alvo_id: int, limites: Limites) -> Resultado:
    """Tira o post do lugar e põe logo antes do alvo. Os horários da fila não mudam, só quem ocupa cada um."""
    ordem = [item for item, _clock in _ordenada(fila)]
    if post_id not in ordem or alvo_id not in ordem:
        return _sumiu()
    if post_id == alvo_id:
        return Resultado()
    clocks = [clock for _item, clock in _ordenada(fila)]
    ordem.remove(post_id)
    ordem.insert(ordem.index(alvo_id), post_id)
    return _validar(fila, dict(zip(ordem, clocks)), limites)


def no_horario(fila: Fila, post_id: int, clock: str, limites: Limites) -> Resultado:
    atual = dict(fila)
    if post_id not in atual:
        return _sumiu()
    if _minutes(clock) is None:
        return Resultado(erro="Horário inválido.")
    dono = next((item for item, outro in fila if outro == clock and item != post_id), None)
    if dono is not None:
        return Resultado(erro=f"Já tem um post às {clock}.")
    return _validar(fila, {post_id: clock}, limites)


def empurrar(
    fila: Fila,
    post_id: int,
    minutos: int,
    limites: Limites,
    intervalo: int | None = None,
) -> Resultado:
    """Soma minutos a este post e aos seguintes. Com `intervalo`, reespaça os afetados a partir do novo horário."""
    if not _MIN_SHIFT <= minutos <= _MAX_SHIFT:
        return Resultado(erro=f"Empurre entre {_MIN_SHIFT} e +{_MAX_SHIFT} minutos.")
    afetados = _daqui_em_diante(fila, post_id)
    if afetados is None:
        return _sumiu()
    inicio = _minutes(afetados[0][1]) + minutos
    if intervalo is not None:
        if not _MIN_INTERVAL <= intervalo <= _MAX_INTERVAL:
            return _intervalo_invalido()
        novos = {item: _format(inicio + index * intervalo) for index, (item, _clock) in enumerate(afetados)}
    else:
        novos = {item: _format(_minutes(clock) + minutos) for item, clock in afetados}
    return _validar(fila, novos, limites, inicio_afetados=inicio, afetados=len(afetados))


def reespacar(fila: Fila, post_id: int, intervalo: int, limites: Limites) -> Resultado:
    """Este post fica onde está. Cada seguinte vai para `intervalo` minutos depois do anterior."""
    if not _MIN_INTERVAL <= intervalo <= _MAX_INTERVAL:
        return _intervalo_invalido()
    afetados = _daqui_em_diante(fila, post_id)
    if afetados is None:
        return _sumiu()
    inicio = _minutes(afetados[0][1])
    novos = {item: _format(inicio + index * intervalo) for index, (item, _clock) in enumerate(afetados)}
    return _validar(fila, novos, limites, inicio_afetados=inicio, afetados=len(afetados))


def _validar(
    fila: Fila,
    novos: dict[int, str],
    limites: Limites,
    *,
    inicio_afetados: int | None = None,
    afetados: int | None = None,
) -> Resultado:
    mudou = {item: clock for item, clock in novos.items() if dict(fila).get(item) != clock}
    agora = _minutes(limites.agora)
    fim = _minutes(limites.fim)
    for clock in mudou.values():
        minute = _minutes(clock)
        if minute is None or minute > _LAST_MINUTE:
            return Resultado(erro="O horário passaria da meia-noite.")
        if agora is not None and minute <= agora:
            return Resultado(erro=f"O horário {clock} já passou.")
    final = {**dict(fila), **mudou}
    vistos: set[str] = set()
    for clock in sorted(final.values()):
        if clock in vistos:
            return Resultado(erro=f"Ficaria junto com o post das {clock}.")
        vistos.add(clock)
    ordem_antes = [item for item, _clock in _ordenada(fila)]
    ordem_depois = [item for item, _clock in sorted(final.items(), key=lambda pair: (pair[1], ordem_antes.index(pair[0])))]
    if afetados is not None and ordem_depois != ordem_antes:
        primeiro = next(item for item in ordem_antes if item in novos)
        anterior = ordem_antes[ordem_antes.index(primeiro) - 1] if ordem_antes.index(primeiro) > 0 else None
        if anterior is not None:
            return Resultado(erro=f"Ficaria antes do post das {final[anterior]}.")
    fora = [clock for clock in mudou.values() if fim is not None and _minutes(clock) >= fim]
    if fora and not limites.permitir_fora:
        return Resultado(
            clocks=mudou,
            fora=Fora(len(fora), max(fora), _encaixe(inicio_afetados, afetados, fim)),
        )
    return Resultado(clocks=mudou)


def _encaixe(inicio: int | None, quantos: int | None, fim: int | None) -> int | None:
    """Maior intervalo que deixa todos os afetados antes do fim."""
    if inicio is None or not quantos or quantos < 2 or fim is None or inicio >= fim:
        return None
    passo = (fim - 1 - inicio) // (quantos - 1)
    return passo if passo >= _MIN_INTERVAL else None


def _daqui_em_diante(fila: Fila, post_id: int) -> Fila | None:
    ordem = _ordenada(fila)
    index = next((i for i, (item, _clock) in enumerate(ordem) if item == post_id), None)
    if index is None:
        return None
    return ordem[index:]


def _ordenada(fila: Fila) -> Fila:
    return sorted(fila, key=lambda pair: pair[1])


def _sumiu() -> Resultado:
    return Resultado(erro="Esse post não está mais na fila.")


def _intervalo_invalido() -> Resultado:
    return Resultado(erro=f"Use um intervalo entre {_MIN_INTERVAL} e {_MAX_INTERVAL} minutos.")


def _minutes(value: str) -> int | None:
    match = _CLOCK.fullmatch((value or "").strip())
    if match is None:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _format(minute: int) -> str:
    """Passou de 23:59 vira 24:xx de propósito: a validação recusa com a mensagem de meia-noite.

    Antes da meia-noite vira 00:00, que a validação recusa como horário que já passou.
    """
    hour, mins = divmod(max(minute, 0), 60)
    return f"{hour:02d}:{mins:02d}"
