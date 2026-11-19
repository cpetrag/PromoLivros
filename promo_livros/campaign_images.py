"""Fotos das campanhas. Tudo vira JPEG em data/campaigns/{id}/, sem metadados."""
from __future__ import annotations

import io
import logging
import shutil
import struct
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_SIDE = 4096
MAX_PIXELS = 40_000_000
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
JPEG_QUALITY = 88
SIXTEEN_BIT_MODES = {"I", "I;16", "I;16L", "I;16B", "I;16N"}
ALPHA_MODES = {"RGBA", "LA", "PA"}
# Perfis ICC só valem para saída RGB quando a origem já era RGB (CMYK/cinza ficariam com cores erradas).
RGB_PROFILE_MODES = {"RGB", "RGBA", "P", "PA"}
WHITE = (255, 255, 255)
# O Pillow sinaliza arquivo estragado com exceções variadas, como SyntaxError("broken PNG file").
_DECODER_ERRORS = (OSError, SyntaxError, ValueError, EOFError, struct.error)

logger = logging.getLogger(__name__)


class ImageUploadError(ValueError):
    """Arquivo recusado. A mensagem vai para a tela."""


def campaign_dir(root: Path, campaign_id: int) -> Path:
    return root / "data" / "campaigns" / str(int(campaign_id))


def save_upload(root: Path, campaign_id: int, payload: bytes) -> str:
    """Valida pelo conteúdo, não pela extensão, e devolve o caminho relativo à raiz."""
    if not payload:
        raise ImageUploadError("O arquivo veio vazio.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ImageUploadError("A foto passa de 8 MB.")
    accepted = sorted(ACCEPTED_FORMATS)
    try:
        with Image.open(io.BytesIO(payload), formats=accepted) as probe:
            width, height = probe.size
            if width * height > MAX_PIXELS:
                raise ImageUploadError("A foto tem resolução grande demais.")
            probe.verify()
        with Image.open(io.BytesIO(payload), formats=accepted) as source:
            icc_profile = source.info.get("icc_profile") if source.mode in RGB_PROFILE_MODES else None
            source.draft("RGB", (MAX_SIDE, MAX_SIDE))
            # Reduz antes de girar e converter para não manter cópias em resolução cheia na memória.
            source.thumbnail((MAX_SIDE, MAX_SIDE))
            image = _to_rgb(ImageOps.exif_transpose(source))
    except ImageUploadError:
        raise
    except UnidentifiedImageError as exc:
        raise ImageUploadError("Use foto JPEG, PNG ou WebP.") from exc
    except Image.DecompressionBombError as exc:
        raise ImageUploadError("A foto tem resolução grande demais.") from exc
    except _DECODER_ERRORS as exc:
        raise ImageUploadError("Esse arquivo não é uma foto JPEG, PNG ou WebP.") from exc
    folder = campaign_dir(root, campaign_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}.jpg"
    save_options: dict[str, object] = {"quality": JPEG_QUALITY, "optimize": True}
    if icc_profile:
        save_options["icc_profile"] = icc_profile
    image.save(folder / name, "JPEG", **save_options)
    return f"data/campaigns/{int(campaign_id)}/{name}"


def read_image(root: Path, relative_path: str) -> bytes | None:
    resolved = _inside_campaigns(root, relative_path)
    if resolved is None or not resolved.is_file():
        return None
    return resolved.read_bytes()


def remove_image(root: Path, relative_path: str) -> None:
    resolved = _inside_campaigns(root, relative_path)
    if resolved is not None and resolved.is_file():
        resolved.unlink(missing_ok=True)


def remove_campaign_dir(root: Path, campaign_id: int) -> None:
    folder = campaign_dir(root, campaign_id)
    if not folder.exists():
        return
    shutil.rmtree(folder, onexc=_log_removal_error)


def _log_removal_error(_function: object, path: str, error: BaseException) -> None:
    logger.warning("Não foi possível apagar %s da campanha: %s", Path(path).name, type(error).__name__)


def _to_rgb(image: Image.Image) -> Image.Image:
    """16 bits vira 8 bits e transparência vira fundo branco, em vez de preto."""
    if image.mode in SIXTEEN_BIT_MODES:
        image = image.point(lambda value: value / 256).convert("L")
    if image.mode == "P" and "transparency" in image.info:
        image = image.convert("RGBA")
    if image.mode in ALPHA_MODES:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, WHITE + (255,))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _inside_campaigns(root: Path, relative_path: str) -> Path | None:
    """Só aceita data/campaigns/{id}/{nome}.jpg, nunca pastas ou arquivos fora dali."""
    base = (root / "data" / "campaigns").resolve()
    resolved = (root / relative_path).resolve()
    if resolved.parent.parent != base or resolved.suffix != ".jpg":
        return None
    return resolved
