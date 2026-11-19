"""Ações da grade da /hoje. Lê o formulário, chama a regra de horários e devolve o JSON da tela."""
from __future__ import annotations

from promo_livros import fila_horarios
from promo_livros.fila_horarios import Limites, Resultado

ACOES = ("trocar", "antes", "horario", "empurrar", "reespacar", "desfazer")


def executar(board, day: str, agora: str, acao: str, form: dict[str, list[str]]) -> dict:
    if acao == "desfazer":
        message = board.restore_clocks(day)
        if message == "Os horários voltaram.":
            return {"ok": True, "message": message}
        return {"ok": False, "error": message}
    if acao not in ACOES:
        return {"ok": False, "error": "Ação desconhecida."}
    try:
        post_id = _inteiro(form, "id")
        permitir = _campo(form, "permitir_fora") == "1"
        change = _mudanca(acao, form, post_id, Limites(agora, board.send_schedule().end, permitir), board)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    result: Resultado = board.apply_clocks(day, change, extend_end=permitir)
    if result.erro:
        return {"ok": False, "error": result.erro}
    if result.fora is not None:
        return {
            "ok": False,
            "fora": {
                "count": result.fora.count,
                "last": result.fora.last,
                "fit_interval": result.fora.fit_interval,
            },
        }
    if not result.clocks:
        return {"ok": True, "message": "Nada mudou."}
    return {"ok": True, "message": _mensagem(acao, len(result.clocks)), "undo": True}


def _mudanca(acao: str, form: dict[str, list[str]], post_id: int, limites: Limites, board):
    if acao == "trocar":
        outro = _inteiro(form, "com")
        return lambda fila: fila_horarios.trocar(fila, post_id, outro, limites)
    if acao == "antes":
        alvo = _inteiro(form, "de")
        return lambda fila: fila_horarios.antes(fila, post_id, alvo, limites)
    if acao == "horario":
        clock = _campo(form, "clock")
        return lambda fila: fila_horarios.no_horario(fila, post_id, clock, limites)
    if acao == "empurrar":
        minutos = _inteiro(form, "minutos", padrao=board.send_schedule().post_interval_minutes)
        intervalo = _inteiro(form, "intervalo") if _campo(form, "intervalo") else None
        return lambda fila: fila_horarios.empurrar(fila, post_id, minutos, limites, intervalo)
    intervalo = _inteiro(form, "intervalo")
    return lambda fila: fila_horarios.reespacar(fila, post_id, intervalo, limites)


def _mensagem(acao: str, quantos: int) -> str:
    plural = "post mudou" if quantos == 1 else "posts mudaram"
    if acao == "trocar":
        return "Os dois posts trocaram de horário."
    return f"{quantos} {plural} de horário."


def _campo(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name) or [""]
    return (values[0] or "").strip()


def _inteiro(form: dict[str, list[str]], name: str, *, padrao: int | None = None) -> int:
    raw = _campo(form, name)
    if not raw and padrao is not None:
        return padrao
    try:
        return int(raw)
    except ValueError:
        raise ValueError("Pedido incompleto. Atualize a página.") from None
