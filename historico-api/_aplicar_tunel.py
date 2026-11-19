from pathlib import Path

p = Path.home() / ".cloudflared" / "promo-livros.yml"
text = p.read_text()
backup = p.with_name("promo-livros.yml.bak-historico-20261115")
if not backup.exists():
    backup.write_text(text)
needle = "  - service: http_status:404\n"
block = "  - hostname: historico.promolivros.org\n    service: http://127.0.0.1:8791\n"
if "historico.promolivros.org" not in text:
    if needle not in text:
        raise SystemExit("regra final nao encontrada")
    text = text.replace(needle, block + needle, 1)
    p.write_text(text)
print(p.read_text())
