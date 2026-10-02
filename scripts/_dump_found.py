"""Roda dentro do processo da fila para gravar o corte já lido, sem novo Keepa."""
import gc
import json
import os
import sys
from pathlib import Path

NOTE = Path("/tmp/promo-keepa-dump.txt")
OUT = Path("/Volumes/HD 1Tb/Vibecoding/Promo Livros/data/fila_dia/2026-09-29-keepa-parcial.json")


def _frames():
    seen = []
    for obj in gc.get_objects():
        if type(obj).__name__ == "frame":
            seen.append(obj)
    for frame in sys._current_frames().values():
        current = frame
        while current is not None:
            seen.append(current)
            current = current.f_back
    return seen


def _from_frames():
    names = []
    for frame in _frames():
        try:
            name = frame.f_code.co_name
            local = frame.f_locals
        except Exception:
            continue
        names.append(name)
        if name == "_annotate" and isinstance(local, dict) and isinstance(local.get("found"), list):
            return local["found"], names
    return None, names


def _from_heap():
    best = None
    for obj in gc.get_objects():
        if not isinstance(obj, list) or not obj or not isinstance(obj[0], dict):
            continue
        sample = obj[0]
        if "lugar_vitrine" in sample and "no_menor_120" in sample:
            if best is None or len(obj) > len(best):
                best = obj
    return best


found, names = _from_frames()
if found is None:
    found = _from_heap()
if not isinstance(found, list):
    NOTE.write_text("missing\n" + "\n".join(names[:100]), encoding="utf-8")
else:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    NOTE.write_text(f"ok {len(found)}\n", encoding="utf-8")
    os._exit(0)
