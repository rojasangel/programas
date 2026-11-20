"""Structured homepage content, drafts, validation and atomic publication."""
import copy
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

HOME_CONTENT_LIMITS = {"hero_images": 5, "sections": 6, "announcements": 5}
HOME_CONTENT_LOCK = threading.RLock()
DEFAULT_HOME_CONTENT = {
    "hero": {
        "enabled": True, "eyebrow": "FR BEISSHOP",
        "title": "Los mejores productos", "accent": "están por llegar.",
        "description": "Estamos preparando una nueva selección para tus próximos juegos.",
        "button_label": "Ver el catálogo", "button_url": "/#catalogo",
        "watermark": "PRÓXIMAMENTE", "images": [],
        "image_layout": "side", "image_size": "large", "image_fit": "contain",
        "font_family": "modern", "text_color": "#0b0b0d", "accent_color": "#1234d6",
        "image_position_x": 50, "image_position_y": 50, "image_zoom": 100,
        "image_left": 53, "image_top": 8, "image_width": 42,
        "copy_left": 5, "copy_top": 12, "copy_width": 44, "canvas_height": 560,
        "background_color": "#f4f6ff", "text_align": "left",
    },
    "catalog": {"enabled": True, "eyebrow": "LA SELECCIÓN FR", "title": "Equipo para entrar al juego"},
    "sections": [],
    "announcements": [],
    "callout": {
        "enabled": True, "eyebrow": "¿ESTÁS LEJOS DE MEXICALI?",
        "title": "El juego llega hasta ti.",
        "description": "Preparamos pedidos para toda la República. El costo y tiempo de envío se confirman según tu código postal.",
        "button_label": "", "button_url": "",
    },
}

HOME_STYLE_DEFAULTS = {
    "font_family": "modern", "text_color": "#171d32",
    "accent_color": "#1234d6", "background_color": "#ffffff", "text_align": "left",
    "border_color": "#dce2ef", "panel_radius": 20, "panel_padding": 24,
}


def _visual_style(data, defaults=None):
    defaults = {**HOME_STYLE_DEFAULTS, **(defaults or {})}
    result = {}
    for key in ("text_color", "accent_color", "background_color"):
        value = data.get(key, defaults[key])
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise HomeContentError("Elige colores válidos para la sección.")
        result[key] = value.lower()
    for key, choices in (("font_family", {"modern", "classic", "sport", "mono"}), ("text_align", {"left", "center", "right"})):
        value = data.get(key, defaults[key])
        if value not in choices:
            raise HomeContentError("Revisa el estilo de la sección.")
        result[key] = value
    border_color = data.get("border_color", defaults["border_color"])
    if not isinstance(border_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", border_color):
        raise HomeContentError("Elige un color valido para el borde del panel.")
    result["border_color"] = border_color.lower()
    for key, minimum, maximum in (("panel_radius", 0, 48), ("panel_padding", 12, 72)):
        value = data.get(key, defaults[key])
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise HomeContentError("Revisa el espaciado y la forma del panel.")
        result[key] = value
    return result


class HomeContentError(ValueError):
    pass


def _object(value, label):
    if not isinstance(value, dict):
        raise HomeContentError(f"Revisa los datos de {label}.")
    return value


def _text(data, key, limit, label, default="", required=False):
    value = data.get(key, default)
    if not isinstance(value, str):
        raise HomeContentError(f"Revisa el texto de {label}.")
    value = value.strip()
    if len(value) > limit:
        raise HomeContentError(f"{label} admite hasta {limit} caracteres.")
    if required and not value:
        raise HomeContentError(f"Completa {label}.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise HomeContentError(f"Revisa los caracteres de {label}.")
    return value


def _enabled(data, default=True):
    value = data.get("enabled", default)
    if not isinstance(value, bool):
        raise HomeContentError("Revisa las opciones para mostrar u ocultar las secciones.")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise HomeContentError(f"Revisa el identificador de {label}.")
    return value


def validate_button_url(value):
    if not isinstance(value, str) or len(value) > 300 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise HomeContentError("Usa un destino como /nuestra-marca, /#catalogo o https://ejemplo.com.")
    if value.startswith("#") or (value.startswith("/") and not value.startswith("//")):
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
            parsed.port  # Validate a supplied port as well.
            return value
    except ValueError:
        pass
    raise HomeContentError("Los botones deben apuntar a una sección de la tienda o a una dirección https:// válida.")


def validate_home_image_url(value):
    if not isinstance(value, str) or not re.fullmatch(r"/static/uploads/[a-f0-9]{32}\.(?:jpg|png|webp)", value):
        raise HomeContentError("Selecciona una foto subida desde el editor.")
    return value


def _button(data):
    label = _text(data, "button_label", 50, "el texto del botón")
    url = _text(data, "button_url", 300, "el destino del botón")
    if label and not url:
        raise HomeContentError("Agrega el destino del botón o deja vacío su texto para ocultarlo.")
    return {"button_label": label, "button_url": validate_button_url(url) if label else ""}


def normalize_home_content(raw):
    raw = _object(raw, "la página de inicio")
    hero_raw = _object(raw.get("hero", {}), "la portada")
    hero_default = DEFAULT_HOME_CONTENT["hero"]
    hero_enabled = _enabled(hero_raw)
    hero = {"enabled": hero_enabled}
    for key, limit in (("eyebrow", 60), ("title", 100), ("accent", 100), ("description", 500), ("watermark", 40)):
        hero[key] = _text(hero_raw, key, limit, f"la portada ({key})", hero_default[key], required=key == "title" and hero_enabled)
    hero.update(_button({**hero_default, **hero_raw}))
    image_layout = hero_raw.get("image_layout", hero_default["image_layout"])
    image_size = hero_raw.get("image_size", hero_default["image_size"])
    image_fit = hero_raw.get("image_fit", hero_default["image_fit"])
    if image_layout not in {"side", "left", "below", "above", "background", "free"}:
        raise HomeContentError("Elige una posición válida para la imagen de portada.")
    if image_size not in {"small", "medium", "large"}:
        raise HomeContentError("Elige un tamaño válido para la imagen de portada.")
    if image_fit not in {"contain", "cover"}:
        raise HomeContentError("Elige cómo debe ajustarse la imagen de portada.")
    hero.update(image_layout=image_layout, image_size=image_size, image_fit=image_fit)
    font_family = hero_raw.get("font_family", hero_default["font_family"])
    if font_family not in {"modern", "classic", "sport", "mono"}:
        raise HomeContentError("Elige un tipo de letra válido para la portada.")
    colors = {}
    for key, label, default in (("text_color", "el color del texto", hero_default["text_color"]), ("accent_color", "el color destacado", hero_default["accent_color"])):
        value = hero_raw.get(key, default)
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise HomeContentError(f"Elige un color hexadecimal válido para {label}.")
        colors[key] = value.lower()
    hero.update(font_family=font_family, **colors)
    hero.update(_visual_style(hero_raw, hero_default))
    for key, label, minimum, maximum, default in (
        ("image_position_x", "la posición horizontal de la imagen", 0, 100, hero_default["image_position_x"]),
        ("image_position_y", "la posición vertical de la imagen", 0, 100, hero_default["image_position_y"]),
        ("image_zoom", "el zoom de la imagen", 100, 180, hero_default["image_zoom"]),
        ("image_left", "la ubicación horizontal de la foto", 0, 95, hero_default["image_left"]),
        ("image_top", "la ubicación vertical de la foto", 0, 95, hero_default["image_top"]),
        ("image_width", "el ancho de la foto", 15, 100, hero_default["image_width"]),
        ("copy_left", "la ubicación horizontal del texto", 0, 95, hero_default["copy_left"]),
        ("copy_top", "la ubicación vertical del texto", 0, 95, hero_default["copy_top"]),
        ("copy_width", "el ancho del texto", 15, 100, hero_default["copy_width"]),
        ("canvas_height", "la altura de la portada", 400, 1000, hero_default["canvas_height"]),
    ):
        value = hero_raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise HomeContentError(f"Revisa {label}.")
        hero[key] = value
    images_raw = hero_raw.get("images", [])
    if not isinstance(images_raw, list) or len(images_raw) > HOME_CONTENT_LIMITS["hero_images"]:
        raise HomeContentError("La portada admite hasta 5 fotos.")
    hero["images"] = []
    image_ids = set()
    for image_raw in images_raw:
        image_raw = _object(image_raw, "las fotos de portada")
        image_id = _identifier(image_raw.get("id"), "la foto")
        if image_id in image_ids:
            raise HomeContentError("Una foto de portada aparece repetida.")
        image_ids.add(image_id)
        hero["images"].append({
            "id": image_id, "url": validate_home_image_url(image_raw.get("url")),
            "alt": _text(image_raw, "alt", 180, "la descripción de la foto") or hero["title"],
        })

    catalog_raw = _object(raw.get("catalog", {}), "el catálogo")
    catalog_enabled = _enabled(catalog_raw)
    catalog = {
        "enabled": catalog_enabled,
        "eyebrow": _text(catalog_raw, "eyebrow", 60, "el subtítulo del catálogo", DEFAULT_HOME_CONTENT["catalog"]["eyebrow"]),
        "title": _text(catalog_raw, "title", 100, "el título del catálogo", DEFAULT_HOME_CONTENT["catalog"]["title"], required=catalog_enabled),
        **_visual_style(catalog_raw, {"background_color": "#f5f6fc"}),
    }
    sections_raw = raw.get("sections", [])
    if not isinstance(sections_raw, list) or len(sections_raw) > HOME_CONTENT_LIMITS["sections"]:
        raise HomeContentError("Puedes agregar hasta 6 bloques de información.")
    sections, section_ids = [], set()
    for section_raw in sections_raw:
        section_raw = _object(section_raw, "los bloques")
        section_id = _identifier(section_raw.get("id"), "el bloque")
        if section_id in section_ids:
            raise HomeContentError("Un bloque aparece repetido.")
        section_ids.add(section_id)
        enabled = _enabled(section_raw)
        position = section_raw.get("position", "before_catalog")
        if position not in {"before_catalog", "after_catalog"}:
            raise HomeContentError("Elige si el bloque aparece antes o después del catálogo.")
        image_url = section_raw.get("image_url", "")
        section = {
            "id": section_id, "enabled": enabled, "position": position,
            "eyebrow": _text(section_raw, "eyebrow", 60, "el subtítulo del bloque"),
            "title": _text(section_raw, "title", 100, "el título del bloque", required=enabled),
            "body": _text(section_raw, "body", 1600, "el texto del bloque"),
            "image_url": validate_home_image_url(image_url) if image_url else "",
            "image_alt": _text(section_raw, "image_alt", 180, "la descripción de la imagen del bloque"),
            **_button(section_raw),
            **_visual_style(section_raw),
        }
        sections.append(section)

    announcements_raw = raw.get("announcements", [])
    if not isinstance(announcements_raw, list) or len(announcements_raw) > HOME_CONTENT_LIMITS["announcements"]:
        raise HomeContentError("Puedes agregar hasta 5 anuncios.")
    announcements, announcement_ids = [], set()
    for announcement_raw in announcements_raw:
        announcement_raw = _object(announcement_raw, "los anuncios")
        announcement_id = _identifier(announcement_raw.get("id"), "el anuncio")
        if announcement_id in announcement_ids:
            raise HomeContentError("Un anuncio aparece repetido.")
        announcement_ids.add(announcement_id)
        enabled = _enabled(announcement_raw)
        announcements.append({
            "id": announcement_id,
            "enabled": enabled,
            "eyebrow": _text(announcement_raw, "eyebrow", 60, "el subtítulo del anuncio"),
            "title": _text(announcement_raw, "title", 100, "el título del anuncio", required=enabled),
            "body": _text(announcement_raw, "body", 500, "el texto del anuncio"),
            "image_url": validate_home_image_url(announcement_raw.get("image_url", "")) if announcement_raw.get("image_url", "") else "",
            "image_alt": _text(announcement_raw, "image_alt", 180, "la descripción de la imagen del anuncio"),
            **_button(announcement_raw),
            **_visual_style(announcement_raw),
        })

    callout_raw = _object(raw.get("callout", {}), "la banda final")
    callout_default = DEFAULT_HOME_CONTENT["callout"]
    callout_enabled = _enabled(callout_raw)
    callout = {"enabled": callout_enabled}
    for key, limit in (("eyebrow", 60), ("title", 100), ("description", 500)):
        callout[key] = _text(callout_raw, key, limit, f"la banda final ({key})", callout_default[key], required=key == "title" and callout_enabled)
    callout.update(_button({**callout_default, **callout_raw}))
    callout.update(_visual_style(callout_raw, {"background_color": "#f4f6ff"}))
    if not catalog_enabled and any(
        block.get("enabled") and block.get("button_url", "").split("?", 1)[0] in {"#catalogo", "/#catalogo"}
        for block in [hero, callout, *sections]
    ):
        raise HomeContentError("Activa el catálogo o cambia los botones que apuntan a /#catalogo.")
    original_order = ["hero", *[f"announcement:{item['id']}" for item in announcements],
                      *[f"section:{item['id']}" for item in sections if item["position"] == "before_catalog"],
                      "catalog", *[f"section:{item['id']}" for item in sections if item["position"] == "after_catalog"], "callout"]
    order = raw.get("block_order", original_order)
    if not isinstance(order, list) or any(not isinstance(key, str) or key not in original_order for key in order) or len(set(order)) != len(order):
        raise HomeContentError("Revisa el orden de las secciones de inicio.")
    order = [*order, *[key for key in original_order if key not in order]]
    return {"hero": hero, "catalog": catalog, "sections": sections, "announcements": announcements, "callout": callout, "block_order": order}


def default_homepage_settings():
    defaults = normalize_home_content(DEFAULT_HOME_CONTENT)
    return {"version": 1, "draft": copy.deepcopy(defaults), "published": copy.deepcopy(defaults), "updated_at": None, "published_at": None}


def load_homepage_settings(path):
    path = Path(path)
    with HOME_CONTENT_LOCK:
        if not path.exists():
            return default_homepage_settings()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError("Unsupported homepage settings")
            return {
                "version": 1,
                "draft": normalize_home_content(raw["draft"]),
                "published": normalize_home_content(raw["published"]),
                "updated_at": raw.get("updated_at"), "published_at": raw.get("published_at"),
            }
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise HomeContentError("No se pudo leer la configuración de inicio guardada. No se han reemplazado tus cambios.") from error


def save_homepage_settings(path, content, publish=False):
    path = Path(path)
    content = normalize_home_content(content)
    with HOME_CONTENT_LOCK:
        settings = load_homepage_settings(path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        settings.update(draft=copy.deepcopy(content), updated_at=now)
        if publish:
            settings.update(published=copy.deepcopy(content), published_at=now)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(json.dumps(settings, ensure_ascii=False, indent=2))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return settings

