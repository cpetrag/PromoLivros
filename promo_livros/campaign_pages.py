"""HTML da /campanhas e do cartão de convites da /hoje."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from promo_livros.campaign_images import MAX_UPLOAD_BYTES
from promo_livros.campaign_rules import MAX_LAST_OFFSET_MINUTES, MIN_LAST_OFFSET_MINUTES, InviteSettings
from promo_livros.campaign_store import MAX_NAME_LENGTH, MAX_TEXT_LENGTH, Campaign, CampaignImage, CampaignText
from promo_livros.dashboard_pages import render_page

CAMPAIGN_STYLE = """
.campaign-settings { display: grid; gap: 10px; margin: 16px 0; padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.campaign-settings form { display: flex; gap: 10px; flex-wrap: wrap; align-items: end; }
.campaigns { display: grid; gap: 8px; margin: 16px 0; }
.campaigns .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--card); }
.campaigns .row form { margin-left: auto; display: flex; gap: 6px; }
body > main.campaign-detail { width: min(72rem, calc(100% - 2rem)); }
.campaign-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 24px; align-items: start; margin: 8px 0 24px; }
.campaign-columns > section { display: grid; gap: 10px; min-width: 0; }
.saved-list { padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.saved-list h3 { margin: 0; font-size: 1rem; }
.thumbs { display: flex; flex-wrap: wrap; gap: 12px; margin: 0; }
.thumbs figure { margin: 0; display: grid; gap: 6px; }
.thumbs img { border-radius: 8px; object-fit: cover; height: 140px; width: auto; }
.new-text { display: grid; gap: 6px; }
.saved-text { display: grid; gap: 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--bg); }
.saved-text .body { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.saved-text details form { display: grid; gap: 6px; margin-top: 8px; }
.saved-text .row-actions { display: flex; gap: 8px; flex-wrap: wrap; }
@media (max-width: 760px) { .campaign-columns { grid-template-columns: 1fr; } }
.paste-preview { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
.paste-preview img { height: 80px; width: auto; border-radius: 6px; }
"""

# O navegador só entrega imagens coladas ao JS; elas entram no mesmo campo de arquivo,
# então o servidor recebe e valida tudo igual a um arquivo escolhido do disco.
PASTE_PHOTO_SCRIPT = """
(function () {
  var form = document.getElementById("photo-upload");
  if (!form) return;
  var input = form.querySelector('input[type="file"]');
  var preview = document.getElementById("paste-preview");
  var status = document.getElementById("paste-status");
  var pasteButton = document.getElementById("paste-photo");
  var maxBytes = parseInt(form.dataset.maxBytes, 10) || 0;
  var accepted = ["image/jpeg", "image/png", "image/webp"];
  var pastedCount = 0;

  function extensionFor(type) {
    return type === "image/jpeg" ? "jpg" : type.split("/")[1];
  }

  function showMessage(text) {
    status.textContent = text;
  }

  function addImages(blobs) {
    var transfer = new DataTransfer();
    Array.prototype.forEach.call(input.files, function (file) { transfer.items.add(file); });
    var added = 0;
    var refused = [];
    blobs.forEach(function (blob) {
      if (accepted.indexOf(blob.type) === -1) {
        refused.push("formato não aceito, use JPEG, PNG ou WebP");
        return;
      }
      if (maxBytes && blob.size > maxBytes) {
        refused.push("imagem acima do limite de tamanho");
        return;
      }
      pastedCount += 1;
      var name = "colada-" + pastedCount + "." + extensionFor(blob.type);
      transfer.items.add(new File([blob], name, { type: blob.type }));
      var thumb = document.createElement("img");
      thumb.alt = "Imagem colada " + pastedCount;
      thumb.src = URL.createObjectURL(blob);
      preview.appendChild(thumb);
      added += 1;
    });
    input.files = transfer.files;
    var message = added ? input.files.length + " foto(s) pronta(s). Clique em Enviar fotos." : "";
    if (refused.length) message += (message ? " " : "") + "Não colei: " + refused.join("; ") + ".";
    showMessage(message);
  }

  document.addEventListener("paste", function (event) {
    var items = (event.clipboardData && event.clipboardData.items) || [];
    var images = [];
    Array.prototype.forEach.call(items, function (item) {
      if (item.kind === "file" && item.type.indexOf("image/") === 0) {
        var file = item.getAsFile();
        if (file) images.push(file);
      }
    });
    if (!images.length) return;
    event.preventDefault();
    addImages(images);
  });

  if (navigator.clipboard && navigator.clipboard.read) {
    pasteButton.hidden = false;
    pasteButton.addEventListener("click", function () {
      navigator.clipboard.read().then(function (entries) {
        var reads = [];
        entries.forEach(function (entry) {
          var type = entry.types.filter(function (t) { return t.indexOf("image/") === 0; })[0];
          if (type) reads.push(entry.getType(type));
        });
        if (!reads.length) {
          showMessage("Não há imagem na área de transferência.");
          return;
        }
        return Promise.all(reads).then(addImages);
      }).catch(function () {
        showMessage("O navegador não deixou ler a área de transferência. Use Ctrl+V.");
      });
    });
  }
})();
"""

# A /hoje já estiliza .panel-card; aqui só entra o miolo do cartão de convites.
INVITE_STYLE = """
#convites .invite { display: grid; gap: 6px; padding: 8px 0; border-bottom: 1px solid var(--line); }
#convites .invite p { margin: 0; }
#convites .invite form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
#convites .invite select { font: inherit; min-height: 40px; max-width: 100%; border: 1px solid var(--line); border-radius: 10px; background: var(--card); color: var(--ink); padding: 0 0.6rem; }
"""


@dataclass(frozen=True)
class InviteCard:
    kind: str
    title: str
    status_label: str
    chosen_id: int | None
    campaign_name: str | None
    can_change: bool


def render_campaign_list(campaigns: list[Campaign], settings: InviteSettings, *, notice: str | None) -> str:
    rows = "".join(_list_row(campaign) for campaign in campaigns)
    listing = f'<div class="campaigns">{rows}</div>' if rows else '<p class="muted">Nenhuma campanha ainda.</p>'
    body = f"""
    <main>
      <h1>Campanhas</h1>
      {_notice(notice)}
      <section class="campaign-settings">
        <h2>Horários dos convites</h2>
        <form method="post" action="/campanhas/config">
          <label>Convite no horário
            <input name="fixo" value="{escape(settings.fixed_clock or "")}" placeholder="13:15" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" maxlength="5">
          </label>
          <label>Convite final, minutos depois do último post
            <input name="final" type="number" min="{MIN_LAST_OFFSET_MINUTES}" max="{MAX_LAST_OFFSET_MINUTES}" required value="{settings.last_offset_minutes}">
          </label>
          <button type="submit">Salvar</button>
        </form>
        <p class="muted">Deixe o horário vazio para não mandar o convite do meio do dia. Ele precisa ficar fora dos horários da fila e só sai até 1 hora depois do horário. O convite final sai depois do último post da fila; sem fila, depois do fim da janela.</p>
      </section>
      {listing}
      <h2>Nova campanha</h2>
      <form method="post" action="/campanhas/acao">
        <input type="hidden" name="acao" value="criar">
        <label>Nome <input name="nome" maxlength="{MAX_NAME_LENGTH}" required></label>
        <button type="submit">Criar</button>
      </form>
    </main>
    """
    return render_page("Campanhas", body, extra_style=CAMPAIGN_STYLE)


def render_campaign_detail(
    campaign: Campaign,
    images: list[CampaignImage],
    texts: list[CampaignText],
    *,
    notice: str | None,
) -> str:
    toggle_action, toggle_label = ("desativar", "Desativar") if campaign.active else ("ativar", "Ativar")
    thumbs = "".join(_thumb(campaign.id, image) for image in images)
    saved_texts = "".join(_saved_text(campaign.id, text) for text in texts)
    upload_megabytes = MAX_UPLOAD_BYTES // (1024 * 1024)
    body = f"""
    <main class="campaign-detail">
      <p><a href="/campanhas">← Campanhas</a></p>
      <h1>{escape(campaign.name)}</h1>
      {_notice(notice)}
      <form method="post" action="/campanhas/acao">
        <input type="hidden" name="id" value="{campaign.id}">
        <label>Nome <input name="nome" value="{escape(campaign.name)}" maxlength="{MAX_NAME_LENGTH}" required></label>
        <button name="acao" value="renomear" type="submit">Renomear</button>
        <button class="ghost" name="acao" value="{toggle_action}" type="submit" formnovalidate>{toggle_label}</button>
      </form>
      <h2>Fotos</h2>
      <div class="campaign-columns">
        <section>
          <form method="post" action="/campanhas/{campaign.id}/fotos" enctype="multipart/form-data" id="photo-upload" data-max-bytes="{MAX_UPLOAD_BYTES}">
            <input type="file" name="fotos" accept="image/jpeg,image/png,image/webp" multiple required>
            <button class="ghost" type="button" id="paste-photo" hidden>Colar imagem</button>
            <button type="submit">Enviar fotos</button>
          </form>
          <div class="paste-preview" id="paste-preview"></div>
          <p class="muted" id="paste-status" aria-live="polite"></p>
          <p class="muted">JPEG, PNG ou WebP, até {upload_megabytes} MB cada. Dá para colar uma imagem copiada com Ctrl+V nesta página. A foto vai como JPEG, sem os dados da câmera.</p>
        </section>
        <section class="saved-list" aria-label="Fotos salvas">
          <h3>Fotos salvas ({len(images)})</h3>
          <div class="thumbs">{thumbs or '<p class="muted">Nenhuma foto ainda.</p>'}</div>
        </section>
      </div>
      <h2>Textos</h2>
      <p class="muted">Na hora do envio sai uma foto e um texto desta lista, evitando repetir o último.</p>
      <div class="campaign-columns">
        <section>
          <form class="new-text" method="post" action="/campanhas/acao">
            <input type="hidden" name="id" value="{campaign.id}">
            <label for="new-text-body">Novo texto</label>
            <textarea id="new-text-body" name="corpo" rows="8" maxlength="{MAX_TEXT_LENGTH}" required placeholder="Entre no nosso grupo de ..."></textarea>
            <div><button name="acao" value="texto_novo" type="submit">Adicionar texto</button></div>
          </form>
        </section>
        <section class="saved-list" aria-label="Textos salvos">
          <h3>Textos salvos ({len(texts)})</h3>
          {saved_texts or '<p class="muted">Nenhum texto ainda.</p>'}
        </section>
      </div>
      <form method="post" action="/campanhas/acao" onsubmit="return confirm('Apagar a campanha, as fotos e os textos?')">
        <input type="hidden" name="id" value="{campaign.id}">
        <button class="ghost" name="acao" value="apagar" type="submit">Apagar campanha</button>
      </form>
    </main>
    """
    return render_page("Campanhas", body, extra_style=CAMPAIGN_STYLE, extra_script=PASTE_PHOTO_SCRIPT)


def render_invite_cards(cards: list[InviteCard], ready: list[Campaign]) -> str:
    blocks = "".join(_invite_block(card, ready) for card in cards)
    return f"""
    <section class="panel-card" id="convites">
      <h2>Convites para outros grupos</h2>
      {blocks}
      <p><a href="/campanhas">Editar campanhas</a></p>
    </section>
    """


def _invite_block(card: InviteCard, ready: list[Campaign]) -> str:
    if card.can_change:
        rotation = f"Rodízio: {card.campaign_name}" if card.chosen_id is None and card.campaign_name else "Rodízio"
        options = [f'<option value="">{escape(rotation)}</option>']
        for campaign in ready:
            selected = " selected" if campaign.id == card.chosen_id else ""
            options.append(f'<option value="{campaign.id}"{selected}>{escape(campaign.name)}</option>')
        detail = f"""
        <form method="post" action="/hoje/convite">
          <input type="hidden" name="tipo" value="{escape(card.kind)}">
          <select name="campanha" aria-label="Campanha do {escape(card.title)}">{''.join(options)}</select>
          <button class="ghost" type="submit">Trocar</button>
        </form>"""
    else:
        detail = f'<p class="muted">{escape(card.campaign_name or "Sem campanha")}</p>'
    return f"""
    <div class="invite">
      <p><strong>{escape(card.title)}</strong> <span class="pill neutral">{escape(card.status_label)}</span></p>
      {detail}
    </div>
    """


def _list_row(campaign: Campaign) -> str:
    if not campaign.active:
        label, kind = "Desativada", "neutral"
    elif campaign.ready:
        label, kind = "Pronta", "ok"
    else:
        label, kind = "Incompleta", "wait"
    return f"""
    <article class="row">
      <a href="/campanhas/{campaign.id}"><strong>{escape(campaign.name)}</strong></a>
      <span class="muted">{campaign.image_count} fotos · {campaign.text_count} textos</span>
      <span class="pill {kind}">{label}</span>
      <form method="post" action="/campanhas/acao">
        <input type="hidden" name="id" value="{campaign.id}">
        <button class="ghost" name="acao" value="subir" type="submit" aria-label="Subir">↑</button>
        <button class="ghost" name="acao" value="descer" type="submit" aria-label="Descer">↓</button>
      </form>
    </article>
    """


def _thumb(campaign_id: int, image: CampaignImage) -> str:
    return f"""
        <figure>
          <img src="/campanhas/foto/{image.id}.jpg" alt="" loading="lazy">
          <form method="post" action="/campanhas/acao">
            <input type="hidden" name="id" value="{campaign_id}">
            <input type="hidden" name="foto" value="{image.id}">
            <button class="ghost" name="acao" value="foto_apagar" type="submit">Remover</button>
          </form>
        </figure>"""


def _saved_text(campaign_id: int, text: CampaignText) -> str:
    """Texto salvo fica só para leitura; a caixa de edição só abre em "Editar", para não confundir com o novo."""
    return f"""
          <article class="saved-text">
            <p class="body">{escape(text.body)}</p>
            <details>
              <summary>Editar</summary>
              <form method="post" action="/campanhas/acao">
                <input type="hidden" name="id" value="{campaign_id}">
                <input type="hidden" name="texto" value="{text.id}">
                <textarea name="corpo" rows="6" maxlength="{MAX_TEXT_LENGTH}" required aria-label="Editar texto {text.id}">{escape(text.body)}</textarea>
                <div class="row-actions">
                  <button name="acao" value="texto_editar" type="submit">Salvar alteração</button>
                </div>
              </form>
            </details>
            <form method="post" action="/campanhas/acao" onsubmit="return confirm('Remover este texto?')">
              <input type="hidden" name="id" value="{campaign_id}">
              <input type="hidden" name="texto" value="{text.id}">
              <button class="ghost" name="acao" value="texto_apagar" type="submit">Remover</button>
            </form>
          </article>"""


def _notice(notice: str | None) -> str:
    return f'<p class="alert" role="status">{escape(notice)}</p>' if notice else ""
