import json
import csv
import copy
import base64
import hashlib
import hmac
from html import escape
import io
import math
import os
import re
import secrets
import smtplib
import sqlite3
import threading
import time
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from functools import wraps
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from homepage_content import (
    DEFAULT_HOME_CONTENT, HOME_CONTENT_LIMITS, HomeContentError,
    default_homepage_settings, load_homepage_settings,
    normalize_home_content, save_homepage_settings,
)

app = Flask(__name__)
SECRET_KEY_FILE = Path(__file__).with_name(".flask-secret")
load_dotenv(Path(__file__).with_name(".env"))


def get_secret_key():
    configured_key = os.environ.get("SECRET_KEY", "").strip()
    if configured_key:
        if APP_ENV == "production" and len(configured_key) < 32:
            raise RuntimeError("En producción, SECRET_KEY debe tener al menos 32 caracteres aleatorios.")
        return configured_key
    if APP_ENV == "production":
        raise RuntimeError("Configura SECRET_KEY en el entorno antes de iniciar la tienda en producción.")
    try:
        if SECRET_KEY_FILE.exists():
            saved_key = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
            if saved_key:
                return saved_key
        generated_key = secrets.token_urlsafe(48)
        SECRET_KEY_FILE.write_text(generated_key, encoding="utf-8")
        return generated_key
    except OSError:
        return secrets.token_urlsafe(48)


APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}
app.secret_key = get_secret_key()
secure_cookie_override = os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower()
app.config.update(
    MAX_CONTENT_LENGTH=32 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(IS_PRODUCTION or secure_cookie_override in {"1", "true", "yes"}),
)
WHATSAPP_NUMBER = re.sub(r"\D", "", os.environ.get("WHATSAPP_NUMBER", "6867731536"))
if len(WHATSAPP_NUMBER) == 10:
    WHATSAPP_NUMBER = "52" + WHATSAPP_NUMBER
CUSTOM_BAT_ORDER_ALERT_EMAILS = tuple(dict.fromkeys(
    email.strip().lower()
    for email in os.environ.get(
        "CUSTOM_BAT_ORDER_ALERT_EMAILS",
        "robertofrbeisshop@gmail.com,frbeisshop23@gmail.com",
    ).split(",")
    if email.strip()
))
SHOP_EMAIL = os.environ.get("SHOP_EMAIL", "").strip()
BUSINESS_LEGAL_NAME = os.environ.get("BUSINESS_LEGAL_NAME", "").strip()
BUSINESS_RFC = os.environ.get("BUSINESS_RFC", "").strip()
BUSINESS_PHYSICAL_ADDRESS = os.environ.get("BUSINESS_PHYSICAL_ADDRESS", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER or SHOP_EMAIL
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "").strip() or SHOP_EMAIL
EMAIL_NOTIFICATIONS = os.environ.get("EMAIL_NOTIFICATIONS", "1").strip().lower() not in {"0", "false", "no", "off"}
EMAIL_CONFIG_FILE = Path(__file__).with_name(".email-config.json")
SHIPPING_CONFIG_FILE = Path(__file__).with_name(".shipping-config.json")
try:
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
except (TypeError, ValueError):
    SMTP_PORT = 587
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:5000").strip().rstrip("/")
PRIVACY_NOTICE_VERSION = "2026-10-29"
PURCHASE_TERMS_VERSION = "2026-10-29"
try:
    SHIPPING_ESTIMATE = max(float(os.environ.get("SHIPPING_ESTIMATE", "180")), 0)
except (TypeError, ValueError):
    SHIPPING_ESTIMATE = 180
SKYDROPX_API_BASE = os.environ.get("SKYDROPX_API_BASE", "https://api-pro.skydropx.com").strip().rstrip("/")
SKYDROPX_CLIENT_ID = os.environ.get("SKYDROPX_CLIENT_ID", "").strip()
SKYDROPX_CLIENT_SECRET = os.environ.get("SKYDROPX_CLIENT_SECRET", "").strip()
SKYDROPX_ORIGIN = {
    "country_code": os.environ.get("SKYDROPX_ORIGIN_COUNTRY", "MX").strip().upper() or "MX",
    "postal_code": os.environ.get("SKYDROPX_ORIGIN_POSTAL_CODE", "").strip(),
    "area_level1": os.environ.get("SKYDROPX_ORIGIN_STATE", "").strip(),
    "area_level2": os.environ.get("SKYDROPX_ORIGIN_CITY", "Mexicali").strip(),
    "area_level3": os.environ.get("SKYDROPX_ORIGIN_NEIGHBORHOOD", "").strip(),
}
SKYDROPX_ORIGIN_ADDRESS = os.environ.get("SKYDROPX_ORIGIN_ADDRESS", "").strip()
SKYDROPX_ORIGIN_PHONE = os.environ.get("SKYDROPX_ORIGIN_PHONE", "").strip()
SKYDROPX_REQUESTED_CARRIERS = [
    carrier.strip().lower()
    for carrier in os.environ.get("SKYDROPX_REQUESTED_CARRIERS", "").split(",")
    if carrier.strip()
]
SKYDROPX_TOKEN = {"value": "", "expires_at": 0.0}
SKYDROPX_TOKEN_LOCK = threading.Lock()


def refresh_email_config():
    """Load optional admin-managed email settings without exposing secrets in templates."""
    global SHOP_EMAIL, SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, EMAIL_REPLY_TO, EMAIL_NOTIFICATIONS, SMTP_PORT
    saved = {}
    try:
        saved = json.loads(EMAIL_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    env_or_saved = lambda key, default="": str(os.environ.get(key, "") or saved.get(key.lower(), default) or "").strip()
    SHOP_EMAIL = env_or_saved("SHOP_EMAIL")
    SMTP_HOST = env_or_saved("SMTP_HOST")
    SMTP_USER = env_or_saved("SMTP_USER")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "") or str(saved.get("smtp_password", ""))
    SMTP_FROM = env_or_saved("SMTP_FROM") or SMTP_USER or SHOP_EMAIL
    EMAIL_REPLY_TO = env_or_saved("EMAIL_REPLY_TO") or SHOP_EMAIL
    raw_port = os.environ.get("SMTP_PORT", "") or saved.get("smtp_port", 587)
    try:
        SMTP_PORT = int(raw_port)
    except (TypeError, ValueError):
        SMTP_PORT = 587
    raw_notifications = os.environ.get("EMAIL_NOTIFICATIONS", "")
    if not raw_notifications and "email_notifications" in saved:
        raw_notifications = str(saved.get("email_notifications"))
    EMAIL_NOTIFICATIONS = str(raw_notifications or "1").strip().lower() not in {"0", "false", "no", "off"}


def refresh_shipping_config():
    """Load Skydropx settings from environment variables or the admin config file."""
    global SKYDROPX_API_BASE, SKYDROPX_CLIENT_ID, SKYDROPX_CLIENT_SECRET
    global SKYDROPX_ORIGIN, SKYDROPX_ORIGIN_ADDRESS, SKYDROPX_ORIGIN_PHONE, SKYDROPX_REQUESTED_CARRIERS
    saved = {}
    try:
        saved = json.loads(SHIPPING_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}

    def value(env_key, saved_key=None, default=""):
        raw_env = os.environ.get(env_key, "")
        if str(raw_env).strip():
            return str(raw_env).strip()
        return str(saved.get(saved_key or env_key.lower(), default) or default).strip()

    SKYDROPX_API_BASE = value("SKYDROPX_API_BASE", "skydropx_api_base", "https://api-pro.skydropx.com").rstrip("/")
    SKYDROPX_CLIENT_ID = value("SKYDROPX_CLIENT_ID", "skydropx_client_id")
    SKYDROPX_CLIENT_SECRET = value("SKYDROPX_CLIENT_SECRET", "skydropx_client_secret")
    SKYDROPX_ORIGIN = {
        "country_code": value("SKYDROPX_ORIGIN_COUNTRY", "skydropx_origin_country", "MX").upper() or "MX",
        "postal_code": value("SKYDROPX_ORIGIN_POSTAL_CODE", "skydropx_origin_postal_code"),
        "area_level1": value("SKYDROPX_ORIGIN_STATE", "skydropx_origin_state"),
        "area_level2": value("SKYDROPX_ORIGIN_CITY", "skydropx_origin_city", "Mexicali"),
        "area_level3": value("SKYDROPX_ORIGIN_NEIGHBORHOOD", "skydropx_origin_neighborhood"),
    }
    SKYDROPX_ORIGIN_ADDRESS = value("SKYDROPX_ORIGIN_ADDRESS", "skydropx_origin_address")
    SKYDROPX_ORIGIN_PHONE = value("SKYDROPX_ORIGIN_PHONE", "skydropx_origin_phone")
    raw_carriers = value("SKYDROPX_REQUESTED_CARRIERS", "skydropx_requested_carriers")
    SKYDROPX_REQUESTED_CARRIERS = [carrier.strip().lower() for carrier in raw_carriers.split(",") if carrier.strip()]
    SKYDROPX_TOKEN.update(value="", expires_at=0.0)


refresh_shipping_config()


def skydropx_is_configured():
    """Return whether the private credentials and origin are ready for a quote."""
    refresh_email_config()
    return bool(
        SKYDROPX_CLIENT_ID
        and SKYDROPX_CLIENT_SECRET
        and all(SKYDROPX_ORIGIN.get(field) for field in ("postal_code", "area_level1", "area_level2", "area_level3"))
        and SKYDROPX_ORIGIN_ADDRESS
        and (SKYDROPX_ORIGIN_PHONE or WHATSAPP_NUMBER)
        and (SHOP_EMAIL or SMTP_FROM)
    )


def _skydropx_json_request(method, path, token="", payload=None, form=False):
    body = None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        if form:
            body = urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
    request = Request(f"{SKYDROPX_API_BASE}{path}", data=body, headers=headers, method=method.upper())
    try:
        with urlopen(request, timeout=20) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        # Skydropx devuelve los motivos de validación en el cuerpo de la
        # respuesta (por ejemplo, campos obligatorios del paquete). Incluimos
        # ese detalle para que el administrador pueda corregirlo sin tener que
        # revisar la consola del servidor.
        try:
            detail = error.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        if detail:
            raise RuntimeError(
                f"Skydropx rechazó la solicitud (HTTP {error.code}): {detail[:420]}"
            ) from error
        raise RuntimeError(f"Skydropx rechazó la solicitud (HTTP {error.code}).") from error
    except URLError as error:
        raise RuntimeError("No pudimos conectar con Skydropx. Inténtalo de nuevo.") from error
    try:
        parsed = json.loads(raw_response) if raw_response else {}
    except json.JSONDecodeError as error:
        raise RuntimeError("Skydropx devolvió una respuesta inválida.") from error
    if not isinstance(parsed, dict):
        raise RuntimeError("Skydropx devolvió un formato inesperado.")
    return parsed


def skydropx_access_token():
    """Get and cache the short-lived Skydropx bearer token on the server."""
    if not SKYDROPX_CLIENT_ID or not SKYDROPX_CLIENT_SECRET:
        raise RuntimeError("Faltan las credenciales de Skydropx en el archivo .env.")
    now = time.time()
    with SKYDROPX_TOKEN_LOCK:
        if SKYDROPX_TOKEN["value"] and SKYDROPX_TOKEN["expires_at"] > now + 60:
            return SKYDROPX_TOKEN["value"]
        response = _skydropx_json_request(
            "POST",
            "/api/v1/oauth/token",
            payload={
                "grant_type": "client_credentials",
                "client_id": SKYDROPX_CLIENT_ID,
                "client_secret": SKYDROPX_CLIENT_SECRET,
            },
            form=True,
        )
        token = str(response.get("access_token") or response.get("token") or "").strip()
        if not token:
            raise RuntimeError("Skydropx no entregó un token de acceso.")
        try:
            expires_in = max(float(response.get("expires_in", 7200)), 300)
        except (TypeError, ValueError):
            expires_in = 7200
        SKYDROPX_TOKEN.update(value=token, expires_at=now + expires_in)
        return token


def _skydropx_number(value):
    if isinstance(value, dict):
        for key in ("amount", "value", "total", "price", "cost"):
            if key in value:
                return _skydropx_number(value[key])
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _skydropx_rates(response):
    """Normalize the different rate wrappers returned by Skydropx versions."""
    rates = []

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else node
        rate_id = str(
            node.get("rate_id")
            or node.get("id")
            or attributes.get("rate_id")
            or attributes.get("id")
            or ""
        ).strip()
        amount = None
        for key in ("total", "price", "amount", "cost", "amount_local"):
            amount = _skydropx_number(attributes.get(key))
            if amount is not None:
                break
        if rate_id and amount is not None:
            carrier = str(
                attributes.get("provider_display_name")
                or attributes.get("provider_name")
                or attributes.get("provider")
                or attributes.get("carrier")
                or attributes.get("carrier_name")
                or attributes.get("company")
                or ""
            ).strip()
            service = str(
                attributes.get("provider_service_name")
                or attributes.get("service")
                or attributes.get("service_level")
                or attributes.get("service_name")
                or attributes.get("name")
                or ""
            ).strip()
            days = _skydropx_number(attributes.get("days"))
            if not any(rate["id"] == rate_id for rate in rates):
                rates.append({
                    "id": rate_id,
                    "price": round(amount, 2),
                    "carrier": carrier,
                    "service": service,
                    "days": int(days) if days is not None else None,
                    "currency": str(attributes.get("currency") or "MXN").upper(),
                })
        for key in ("data", "rates", "shipping_rates", "available_rates", "services", "attributes"):
            child = node.get(key)
            if child is not node and isinstance(child, (dict, list)):
                visit(child)

    visit(response)
    return rates


def _skydropx_quote_payload(items, destination):
    weight = 0.0
    length = width = height = 1
    declared_value = 0.0
    for item in items:
        product = item.get("product", {})
        quantity = max(int(item.get("quantity", 1) or 1), 1)
        weight += float(product.get("package_weight_kg", 0.5) or 0.5) * quantity
        length = max(length, int(math.ceil(float(product.get("package_length_cm", 30) or 30))))
        width = max(width, int(math.ceil(float(product.get("package_width_cm", 20) or 20))))
        height += int(math.ceil(float(product.get("package_height_cm", 15) or 15))) * quantity
        declared_value += float(product.get("price", 0) or 0) * quantity
    parcel = {
        "length": min(length, 500),
        "width": min(width, 500),
        "height": min(max(height, 1), 500),
        "weight": round(max(weight, 0.1), 3),
        "package_protected": False,
        "declared_value": round(max(declared_value, 0), 2),
    }
    if SKYDROPX_REQUESTED_CARRIERS:
        parcel["requested_carriers"] = SKYDROPX_REQUESTED_CARRIERS
    address_to = {
        "country_code": "MX",
        "postal_code": str(destination.get("postal_code", "")).strip(),
        "area_level1": str(destination.get("state", "")).strip(),
        "area_level2": str(destination.get("city", "")).strip(),
        "area_level3": str(destination.get("neighborhood", "")).strip(),
    }
    if destination.get("address"):
        address_to["address"] = str(destination["address"]).strip()
    address_from = dict(SKYDROPX_ORIGIN)
    if SKYDROPX_ORIGIN_ADDRESS:
        address_from["address"] = SKYDROPX_ORIGIN_ADDRESS
    return {"quotation": {"address_from": address_from, "address_to": address_to, "parcels": [parcel]}}


def skydropx_quote(items, destination):
    if not skydropx_is_configured():
        raise RuntimeError("Skydropx está pendiente de configurar: agrega credenciales y la dirección de origen.")
    required = ("postal_code", "state", "city", "neighborhood")
    if any(not str(destination.get(field, "")).strip() for field in required):
        raise RuntimeError("Completa ciudad, estado, colonia y código postal para cotizar el envío.")
    token = skydropx_access_token()
    created = _skydropx_json_request("POST", "/api/v1/quotations", token=token, payload=_skydropx_quote_payload(items, destination))
    quotation_node = created.get("data") if isinstance(created.get("data"), dict) else created
    quotation_attributes = quotation_node.get("attributes", {}) if isinstance(quotation_node, dict) else {}
    quotation_id = str(
        created.get("quotation_id")
        or created.get("id")
        or (quotation_node.get("id") if isinstance(quotation_node, dict) else "")
        or quotation_attributes.get("id")
        or ""
    ).strip()
    if not quotation_id:
        raise RuntimeError("Skydropx no devolvió el identificador de la cotización.")
    rates = _skydropx_rates(created)
    latest = created
    for _ in range(12):
        status_node = latest.get("data") if isinstance(latest.get("data"), dict) else latest
        status_attrs = status_node.get("attributes", {}) if isinstance(status_node, dict) else {}
        status = str(
            latest.get("status")
            or (status_node.get("status") if isinstance(status_node, dict) else "")
            or status_attrs.get("status")
            or ""
        ).strip().lower()
        if rates or status in {"is_completed", "completed", "complete", "success"}:
            break
        if status in {"failed", "error", "cancelled", "canceled"}:
            raise RuntimeError("Skydropx no pudo completar la cotización.")
        time.sleep(1)
        latest = _skydropx_json_request("GET", f"/api/v1/quotations/{quote(quotation_id, safe='')}", token=token)
        rates = _skydropx_rates(latest)
    if not rates:
        raise RuntimeError("Skydropx no encontró tarifas para ese destino y paquete.")
    return {"quotation_id": quotation_id, "rates": rates}


def _skydropx_address_from():
    """Build the origin address required when creating a Skydropx shipment."""
    return {
        "country_code": SKYDROPX_ORIGIN.get("country_code", "MX"),
        "postal_code": SKYDROPX_ORIGIN.get("postal_code", ""),
        "area_level1": SKYDROPX_ORIGIN.get("area_level1", ""),
        "area_level2": SKYDROPX_ORIGIN.get("area_level2", ""),
        "area_level3": SKYDROPX_ORIGIN.get("area_level3", ""),
        "street1": SKYDROPX_ORIGIN_ADDRESS or "Origen FR BEISSHOP",
        "name": "FR BEISSHOP",
        "company": "FR BEISSHOP",
        "phone": SKYDROPX_ORIGIN_PHONE or WHATSAPP_NUMBER or "6860000000",
        "email": SHOP_EMAIL or SMTP_FROM or "pedidos@frbeisshop.com",
        "reference": "FR BEISSHOP",
    }


def _skydropx_address_to(order):
    """Build the destination address from a local order record."""
    return {
        "country_code": "MX",
        "postal_code": str(order.get("postal_code", "")).strip(),
        "area_level1": str(order.get("state", "")).strip(),
        "area_level2": str(order.get("city", "")).strip(),
        "area_level3": str(order.get("neighborhood", "")).strip(),
        "street1": str(order.get("address", "")).strip(),
        "name": str(order.get("customer_name", ""))[:30],
        "company": "FR BEISSHOP",
        "phone": str(order.get("phone", "")).strip(),
        "email": str(order.get("customer_email", "")).strip(),
        "reference": f"Pedido {order.get('id', '')}"[:40],
    }


def _skydropx_shipment_result(response):
    """Normalize shipment responses from the legacy and current API shapes."""
    data = response.get("data") if isinstance(response, dict) else None
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        data = response if isinstance(response, dict) else {}
    attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else data
    included = response.get("included", []) if isinstance(response, dict) else []
    package_attrs = []
    for node in included if isinstance(included, list) else []:
        if isinstance(node, dict) and isinstance(node.get("attributes"), dict):
            candidate = node["attributes"]
            if candidate.get("label_url") or candidate.get("tracking_number"):
                package_attrs.append(candidate)
    label_urls = []
    for package in package_attrs:
        value = package.get("label_url")
        if value and value not in label_urls:
            label_urls.append(str(value))
    # El enlace de etiqueta normalmente viene dentro del paquete. Conservamos
    # los enlaces del envío como respaldo para respuestas antiguas del API.
    for value in [attrs.get("label_url"), attrs.get("order_detail_url")]:
        if value and value not in label_urls:
            label_urls.append(str(value))
    tracking = str(
        attrs.get("master_tracking_number")
        or attrs.get("tracking_number")
        or next((item.get("tracking_number") for item in package_attrs if item.get("tracking_number")), "")
        or ""
    ).strip()
    carrier = str(attrs.get("carrier_name") or attrs.get("carrier") or "Skydropx").strip()
    shipment_id = str(data.get("id") or attrs.get("id") or "").strip()
    order_id = str(attrs.get("order_id") or data.get("order_id") or "").strip()
    relationships = data.get("relationships", {})
    if not order_id and isinstance(relationships, dict):
        relation = relationships.get("order", {})
        relation_data = relation.get("data", {}) if isinstance(relation, dict) else {}
        if isinstance(relation_data, dict):
            order_id = str(relation_data.get("id") or "").strip()
    return {
        "shipment_id": shipment_id,
        "order_id": order_id,
        "tracking_number": tracking,
        "carrier": carrier,
        "label_urls": label_urls,
    }


def create_skydropx_shipment(order):
    """Create an idempotent shipping guide for a paid home-delivery order."""
    if not order or order.get("delivery_method") == "local":
        return order, ""
    if order.get("shipping_label_url"):
        return order, ""
    if not skydropx_is_configured():
        return order, "Skydropx todavía está pendiente de configurar."
    token = skydropx_access_token()
    existing_shipment_id = str(order.get("skydropx_shipment_id", "")).strip()
    existing_skydropx_order_id = str(order.get("skydropx_order_id", "")).strip()
    if existing_shipment_id and not existing_skydropx_order_id:
        # Una creación exitosa puede devolver el shipment_id antes de que el
        # API tenga listo el enlace de la etiqueta. Consultamos el envío antes
        # de permitir otro intento, evitando comprar una segunda guía.
        try:
            shipment_response = _skydropx_json_request(
                "GET", f"/api/v1/shipments/{quote(existing_shipment_id, safe='')}", token=token
            )
            result = _skydropx_shipment_result(shipment_response)
            if result["label_urls"] or result["tracking_number"]:
                label_urls = result["label_urls"]
                note = "Guía de envío lista para descargar." if label_urls else "Guía creada; rastreo disponible."
                with closing(get_users_db()) as db:
                    db.execute(
                        """UPDATE orders SET tracking_number = ?, shipping_carrier = ?,
                           shipping_label_url = ?, shipping_label_urls = ?, shipping_note = ?
                           WHERE id = ?""",
                        (
                            result["tracking_number"], result["carrier"],
                            label_urls[0] if label_urls else "", json.dumps(label_urls, ensure_ascii=False),
                            note, order["id"],
                        ),
                    )
                    updated = db.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
                    db.commit()
                updated_order = dict(updated) if updated else dict(order)
                send_order_status_update(updated_order, order.get("status", "Pagado"))
                return updated_order, ""
        except Exception:
            # Si la etiqueta sigue procesándose, conservamos el shipment_id y
            # mostramos el estado pendiente sin volver a crear el envío.
            pass
        return order, "Envío creado; la etiqueta todavía está en proceso de generación en Skydropx."
    if existing_shipment_id and existing_skydropx_order_id:
        try:
            label_urls = []
            for attempt in range(3):
                labels_response = _skydropx_json_request(
                    "GET", f"/api/v1/orders/{quote(existing_skydropx_order_id, safe='')}/labels", token=token
                )
                labels_data = labels_response.get("data", {}) if isinstance(labels_response, dict) else {}
                labels = labels_data.get("label_urls", []) if isinstance(labels_data, dict) else []
                label_urls = [str(value) for value in labels if value]
                if label_urls or attempt == 2:
                    break
                time.sleep(1)
            if label_urls:
                with closing(get_users_db()) as db:
                    db.execute(
                        "UPDATE orders SET shipping_label_url = ?, shipping_label_urls = ?, shipping_note = ? WHERE id = ?",
                        (label_urls[0], json.dumps(label_urls, ensure_ascii=False), "Guía de envío lista para descargar.", order["id"]),
                    )
                    updated = db.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
                    db.commit()
                updated_order = dict(updated) if updated else dict(order)
                send_order_status_update(updated_order, order.get("status", "Pagado"))
                return updated_order, ""
        except Exception as error:
            return order, str(error)[:240]
        return order, "La etiqueta todavía está en proceso de generación en Skydropx."
    rate_id = str(order.get("shipping_rate_id", "")).strip()
    if not rate_id:
        return order, "No hay una tarifa de Skydropx seleccionada para crear la guía."
    lines = get_order_lines(order)
    line = lines[0] if lines else {}
    item_text = " ".join(
        str(line.get(field, "")) for field in ("name", "category", "where")
    ).lower()
    # Skydropx valida estos códigos contra sus catálogos. 49161506 es bate de
    # béisbol y 49161520 bate de softbol; 4G corresponde a empaque tipo caja.
    consignment_note = "49161520" if "softbol" in item_text or "softball" in item_text else "49161506"
    package = {
        "package_number": "1",
        "package_protected": False,
        # Estos atributos son obligatorios al crear el envío aunque ya se
        # hayan enviado al cotizar. El API rechaza la guía con HTTP 422 si
        # faltan en cada paquete.
        "consignment_note": consignment_note,
        "package_type": "4G",
        "declared_value": round(float(order.get("total", 0) or 0), 2),
        "products": [{
            "name": str(line.get("name", "Artículo de subasta"))[:120],
            "sku": str(line.get("sku") or line.get("product_id") or order.get("id"))[:80],
            "product_type_code": "P",
            "product_type_name": "Producto",
            "quantity": max(int(line.get("quantity", 1) or 1), 1),
            "price": round(float(line.get("unit_price", order.get("total", 0)) or 0), 2),
            "country_code": "MX",
        }],
    }
    payload = {"shipment": {
        "rate_id": rate_id,
        "unique_shipment": True,
        "printing_format": "standard",
        "include_order_detail": True,
        "address_from": _skydropx_address_from(),
        "address_to": _skydropx_address_to(order),
        "packages": [package],
    }}
    try:
        response = _skydropx_json_request("POST", "/api/v1/shipments/", token=token, payload=payload)
        result = _skydropx_shipment_result(response)
        if not result["label_urls"] and result["order_id"]:
            # Skydropx puede generar la etiqueta de forma asíncrona. Esperamos
            # unos segundos para que el comprador y el administrador reciban
            # el enlace en el mismo cierre de pago.
            for attempt in range(4):
                labels_response = _skydropx_json_request(
                    "GET", f"/api/v1/orders/{quote(result['order_id'], safe='')}/labels", token=token
                )
                labels_data = labels_response.get("data", {}) if isinstance(labels_response, dict) else {}
                labels = labels_data.get("label_urls", []) if isinstance(labels_data, dict) else []
                result["label_urls"] = [str(value) for value in labels if value]
                if result["label_urls"] or attempt == 3:
                    break
                time.sleep(1)
        if not result["shipment_id"]:
            raise RuntimeError("Skydropx no devolvió el identificador de la guía.")
        label_urls = result["label_urls"]
        note = "Guía generada automáticamente con Skydropx."
        if not label_urls:
            note = "Envío creado; la etiqueta todavía está en proceso de generación."
        with closing(get_users_db()) as db:
            db.execute(
                """UPDATE orders SET skydropx_shipment_id = ?, tracking_number = ?,
                   shipping_carrier = ?, shipping_label_url = ?, shipping_label_urls = ?,
                   skydropx_order_id = ?,
                   shipping_note = ? WHERE id = ?""",
                (
                    result["shipment_id"], result["tracking_number"], result["carrier"],
                    label_urls[0] if label_urls else "", json.dumps(label_urls, ensure_ascii=False), result["order_id"],
                    note, order["id"],
                ),
            )
            updated = db.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
            db.commit()
        updated_order = dict(updated) if updated else dict(order)
        send_order_status_update(updated_order, order.get("status", "Pagado"))
        return updated_order, ""
    except Exception as error:
        message = str(error)[:240]
        with closing(get_users_db()) as db:
            db.execute("UPDATE orders SET shipping_note = ? WHERE id = ?", (f"Guía pendiente: {message}", order["id"]))
            db.commit()
        return order, message


try:
    LOW_STOCK_THRESHOLD = max(int(os.environ.get("LOW_STOCK_THRESHOLD", "3")), 0)
except (TypeError, ValueError):
    LOW_STOCK_THRESHOLD = 3
ADMIN_CONFIG_FILE = Path(__file__).with_name(".admin-config.json")


def load_admin_config():
    saved_config = {}
    try:
        if ADMIN_CONFIG_FILE.exists():
            saved_config = json.loads(ADMIN_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved_config = {}
    if not isinstance(saved_config, dict):
        saved_config = {}
    username = os.environ.get("ADMIN_USERNAME", "").strip() or saved_config.get("username", "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip() or saved_config.get("password_hash", "")
    return username, password, password_hash


ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_PASSWORD_HASH = load_admin_config()
GOOGLE_CONFIG_FILE = Path(__file__).with_name(".google-config.json")


def load_google_client_id():
    configured = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    if configured:
        return configured
    try:
        saved = json.loads(GOOGLE_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = {}
    return str(saved.get("client_id", "")).strip() if isinstance(saved, dict) else ""


GOOGLE_CLIENT_ID = load_google_client_id()
PRODUCTS_FILE = Path(__file__).with_name("products.json")
DELETED_PRODUCTS_FILE = Path(__file__).with_name("deleted_products.json")
AUCTIONS_FILE = Path(__file__).with_name("auctions.json")
USERS_DB = Path(__file__).with_name("users.sqlite3")
UPLOAD_FOLDER = Path(__file__).with_name("static") / "uploads"
HOMEPAGE_FILE = Path(__file__).with_name("homepage.json")
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PRODUCTS_LOCK = threading.RLock()
AUCTIONS_LOCK = threading.RLock()
AUTH_ATTEMPT_LIMIT = 8
AUTH_ATTEMPT_WINDOW = 300
AUCTION_WINNER_PAYMENT_DAYS = 3
AUCTION_WINNER_REMINDER_HOURS = 24
CUSTOM_BAT_VIEW_LABELS = {
    "engraving": "Letras de cerca",
    "logo": "Marca de cerca",
    "handle": "Punta del mango",
    "base": "Base del mango",
}


def save_product_images(uploads):
    """Validate, re-encode, and save product images without their original metadata."""
    valid_uploads = [upload for upload in (uploads or []) if upload and upload.filename]
    if not valid_uploads:
        return []
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as error:
        raise ValueError("Falta instalar Pillow para validar imágenes: ejecuta pip install -r requirements.txt.") from error

    Image.MAX_IMAGE_PIXELS = 24_000_000
    allowed_formats = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
    prepared = []
    for upload in valid_uploads:
        filename = secure_filename(upload.filename)
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("Selecciona imágenes JPG, PNG o WEBP.")
        raw_data = upload.stream.read(8 * 1024 * 1024 + 1)
        if len(raw_data) > 8 * 1024 * 1024:
            raise ValueError("Cada imagen debe pesar máximo 8 MB.")
        try:
            with Image.open(io.BytesIO(raw_data)) as source:
                image_format = source.format
                width, height = source.size
                if image_format not in allowed_formats or width < 1 or height < 1 or width * height > 24_000_000:
                    raise ValueError("La imagen debe ser JPG, PNG o WEBP y medir máximo 24 megapíxeles.")
                source.verify()
            with Image.open(io.BytesIO(raw_data)) as source:
                sanitized = ImageOps.exif_transpose(source)
                if sanitized.mode not in {"RGB", "RGBA"}:
                    sanitized = sanitized.convert("RGBA" if "A" in sanitized.getbands() else "RGB")
                output = io.BytesIO()
                if image_format == "JPEG":
                    sanitized.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
                elif image_format == "PNG":
                    sanitized.save(output, format="PNG", optimize=True)
                else:
                    sanitized.save(output, format="WEBP", quality=88, method=6)
                prepared.append((output.getvalue(), allowed_formats[image_format]))
        except ValueError:
            raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError("No se pudo validar la imagen. Sube un archivo JPG, PNG o WEBP válido.") from error
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    image_urls = []
    for image_data, extension in prepared:
        stored_name = f"{uuid4().hex}.{extension}"
        (UPLOAD_FOLDER / stored_name).write_bytes(image_data)
        image_urls.append(url_for("static", filename=f"uploads/{stored_name}"))
    return image_urls


def save_product_image(upload):
    """Keep the single-image helper for auctions and other legacy forms."""
    return (save_product_images([upload]) or [None])[0]


def save_custom_bat_preview(data_url):
    """Validate and persist the PNG preview drawn by the bat customizer."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/png;base64,"):
        return ""
    encoded = data_url.partition(",")[2]
    if not encoded or len(encoded) > 4 * 1024 * 1024:
        return ""
    try:
        image_data = base64.b64decode(encoded, validate=True)
        from PIL import Image
        with Image.open(io.BytesIO(image_data)) as source:
            if source.format != "PNG" or source.width < 1 or source.height < 1 or source.width * source.height > 12_000_000:
                return ""
            source.verify()
        with Image.open(io.BytesIO(image_data)) as source:
            output = io.BytesIO()
            source.convert("RGBA").save(output, format="PNG", optimize=True)
        image_data = output.getvalue()
    except (ValueError, OSError, ImportError):
        return ""
    folder = UPLOAD_FOLDER / "custom-bats"
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.png"
    (folder / filename).write_bytes(image_data)
    return filename


def read_custom_bat_preview(filename):
    """Read only app-generated preview filenames from the custom-bats folder."""
    if not isinstance(filename, str) or not re.fullmatch(r"[a-f0-9]{32}\.png", filename):
        return b""
    try:
        return (UPLOAD_FOLDER / "custom-bats" / filename).read_bytes()
    except OSError:
        return b""


def is_valid_email(value):
    return bool(EMAIL_PATTERN.fullmatch(value))


def auth_attempt_key(identifier):
    address = request.remote_addr or "unknown"
    fingerprint = f"{address}:{str(identifier or '').strip().casefold()[:120]}"
    return hmac.new(app.secret_key.encode("utf-8"), fingerprint.encode("utf-8"), hashlib.sha256).hexdigest()


def auth_is_rate_limited(identifier):
    now = time.time()
    key = auth_attempt_key(identifier)
    with closing(get_users_db()) as db:
        row = db.execute("SELECT attempts_json FROM auth_attempts WHERE fingerprint = ?", (key,)).fetchone()
        if not row:
            return False
        try:
            attempts = [float(stamp) for stamp in json.loads(row["attempts_json"]) if now - float(stamp) < AUTH_ATTEMPT_WINDOW]
        except (TypeError, ValueError, json.JSONDecodeError):
            attempts = []
        if attempts:
            db.execute("UPDATE auth_attempts SET attempts_json = ?, updated_at = ? WHERE fingerprint = ?", (json.dumps(attempts), now, key))
        else:
            db.execute("DELETE FROM auth_attempts WHERE fingerprint = ?", (key,))
        db.commit()
        return len(attempts) >= AUTH_ATTEMPT_LIMIT


def record_auth_failure(identifier):
    now = time.time()
    key = auth_attempt_key(identifier)
    with closing(get_users_db()) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT attempts_json FROM auth_attempts WHERE fingerprint = ?", (key,)).fetchone()
        try:
            attempts = [float(stamp) for stamp in json.loads(row["attempts_json"]) if now - float(stamp) < AUTH_ATTEMPT_WINDOW] if row else []
        except (TypeError, ValueError, json.JSONDecodeError):
            attempts = []
        attempts.append(now)
        db.execute(
            "INSERT INTO auth_attempts (fingerprint, attempts_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(fingerprint) DO UPDATE SET attempts_json = excluded.attempts_json, updated_at = excluded.updated_at",
            (key, json.dumps(attempts), now),
        )
        db.execute("DELETE FROM auth_attempts WHERE updated_at < ?", (now - AUTH_ATTEMPT_WINDOW,))
        db.commit()


def clear_auth_failures(identifier):
    with closing(get_users_db()) as db:
        db.execute("DELETE FROM auth_attempts WHERE fingerprint = ?", (auth_attempt_key(identifier),))
        db.commit()


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.path.startswith(("/cuenta", "/admin", "/checkout", "/pago/")):
        response.headers.setdefault("Cache-Control", "private, no-store, max-age=0")
    if request.is_secure or IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def email_is_configured():
    """Return whether transactional email is enabled and has the minimum SMTP settings."""
    refresh_email_config()
    if not (EMAIL_NOTIFICATIONS and SMTP_HOST and SMTP_FROM and SMTP_PORT > 0):
        return False
    if SMTP_HOST.lower() == "smtp.gmail.com":
        app_password = "".join(SMTP_PASSWORD.split())
        return bool(SMTP_USER and len(app_password) == 16)
    return True


def _send_email(message):
    """Send one email without making an order fail when email is unavailable."""
    if not email_is_configured():
        return False
    try:
        if SMTP_PORT == 465:
            server_factory = smtplib.SMTP_SSL
        else:
            server_factory = smtplib.SMTP
        with server_factory(SMTP_HOST, SMTP_PORT, timeout=12) as server:
            if SMTP_PORT != 465:
                server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        app.logger.exception("Falló el envío SMTP del correo con asunto: %s", message.get("Subject", "(sin asunto)"))
        return False


def send_test_email(recipient):
    """Send a small admin test message using the active SMTP settings."""
    if not (recipient and is_valid_email(recipient) and email_is_configured()):
        return False
    message = EmailMessage()
    message["Subject"] = "FR BEISSHOP | Prueba de correo"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = recipient
    message.set_content(
        "Este es un correo de prueba de FR BEISSHOP.\n\n"
        "Las confirmaciones de pedidos y cambios de envío ya pueden enviarse desde el panel."
    )
    return _send_email(message)


def send_password_reset_email(email, reset_url):
    """Send a temporary password reset link when SMTP is configured."""
    if not (email and is_valid_email(email) and reset_url and email_is_configured()):
        return False
    message = EmailMessage()
    message["Subject"] = "FR BEISSHOP | Restablece tu contraseña"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = email
    if EMAIL_REPLY_TO and is_valid_email(EMAIL_REPLY_TO):
        message["Reply-To"] = EMAIL_REPLY_TO
    message.set_content(
        "Recibimos una solicitud para cambiar la contraseña de tu cuenta de FR BEISSHOP.\n\n"
        f"Abre este enlace para crear una nueva contraseña:\n{reset_url}\n\n"
        "El enlace caduca en 30 minutos. Si no solicitaste este cambio, ignora este correo.\n\n"
        "FR BEISSHOP"
    )
    return _send_email(message)


def send_email_verification_email(email, name, verify_url):
    """Send the link used to confirm a new customer's email address."""
    if not (email and is_valid_email(email) and verify_url and email_is_configured()):
        return False
    message = EmailMessage()
    message["Subject"] = "FR BEISSHOP | Confirma tu correo electrónico"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = email
    if EMAIL_REPLY_TO and is_valid_email(EMAIL_REPLY_TO):
        message["Reply-To"] = EMAIL_REPLY_TO
    greeting = name.strip() or "deportista"
    message.set_content(
        f"Hola {greeting},\n\n"
        "Confirma tu correo para mantener segura tu cuenta de FR BEISSHOP.\n\n"
        f"Abre este enlace para confirmar tu correo:\n{verify_url}\n\n"
        "El enlace caduca en 24 horas. Si no creaste esta cuenta, ignora este mensaje.\n\n"
        "FR BEISSHOP"
    )
    safe_name = escape(greeting)
    safe_url = escape(verify_url, quote=True)
    message.add_alternative(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8"></head>
<body style="margin:0;background:#f2f5fb;color:#17203b;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:560px;margin:28px auto;padding:32px;background:#fff;border:1px solid #e1e7f2;border-radius:16px;">
<div style="font-size:12px;font-weight:800;letter-spacing:1.5px;color:#2447e8;">FR BEISSHOP</div>
<h1 style="font-size:28px;margin:14px 0 10px;">Confirma tu correo</h1>
<p style="font-size:15px;line-height:1.6;color:#56617b;">Hola {safe_name}. Confirma tu correo para mantener segura tu cuenta y recibir las actualizaciones importantes de tus pedidos.</p>
<p style="margin:26px 0;"><a href="{safe_url}" style="display:inline-block;padding:13px 22px;border-radius:9px;background:#2447e8;color:#fff;text-decoration:none;font-weight:800;">Confirmar mi correo</a></p>
<p style="font-size:12px;line-height:1.5;color:#7a8498;">Este enlace caduca en 24 horas. Si no creaste esta cuenta, puedes ignorar este mensaje.</p>
</div></body></html>""",
        subtype="html",
    )
    return _send_email(message)


def send_welcome_email(email, name="", unsubscribe_url=""):
    """Send a welcome message after a new customer account is created."""
    if not (email and is_valid_email(email) and email_is_configured()):
        return False
    message = EmailMessage()
    message["Subject"] = "Tu bienvenida a FR BEISSHOP: 10% de descuento"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = email
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if EMAIL_REPLY_TO and is_valid_email(EMAIL_REPLY_TO):
        message["Reply-To"] = EMAIL_REPLY_TO
    message.make_related()
    body = EmailMessage()
    greeting = name.strip() or "deportista"
    coupon_code = "BIENVENIDO10"
    unsubscribe_text = (
        f"\n\nPara no recibir promociones, usa este enlace:\n{unsubscribe_url}"
        if unsubscribe_url else ""
    )
    body.set_content(
        f"Hola {greeting},\n\n"
        "¡Te damos la bienvenida a FR BEISSHOP! Gracias por crear tu cuenta.\n\n"
        f"Disfruta 10% de descuento en tu primera compra con el código {coupon_code}. "
        "Escríbelo en el carrito antes de pagar. El descuento se aplica al subtotal de productos.\n\n"
        "¡Gracias por elegirnos!\nFR BEISSHOP"
        f"{unsubscribe_text}"
    )
    store_url = escape(url_for("index", _external=True), quote=True)
    safe_name = escape(greeting)
    unsubscribe_html = (
        f'<br><a href="{escape(unsubscribe_url, quote=True)}" '
        'style="color:#2447e8;">Cancelar promociones</a>'
        if unsubscribe_url else ""
    )
    logo_path = Path(app.root_path) / "static" / "logo.png"
    try:
        logo_bytes = logo_path.read_bytes()
    except OSError:
        logo_bytes = b""
    logo_cid = make_msgid(domain="frbeisshop.com") if logo_bytes else ""
    logo_html = (
        f'<img src="cid:{logo_cid[1:-1]}" alt="Logo FR BEISSHOP" width="76" '
        'style="display:block;width:76px;height:76px;object-fit:contain;margin:0 auto;border:0;">'
        if logo_cid else
        '<div style="font-size:20px;font-weight:800;letter-spacing:2px;color:#17244d;">FR BEISSHOP</div>'
    )
    html_body = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<style>html,body{{margin:0!important;padding:0!important;background-color:#f2f5fb!important;color:#17203b!important;}}
@media (prefers-color-scheme:dark){{html,body{{background-color:#f2f5fb!important;color:#17203b!important;}}
.email-card{{background-color:#ffffff!important}}.email-copy{{color:#56617b!important}}.offer-card{{background-color:#f3f5ff!important}}}}
@media screen and (max-width:620px){{.outer-pad{{padding:14px 8px!important}}.inner-pad{{padding-left:22px!important;padding-right:22px!important}}.welcome-title{{font-size:27px!important}}}}</style>
</head><body class="body" bgcolor="#f2f5fb" style="margin:0;padding:0;background-color:#f2f5fb;color:#17203b;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f2f5fb" style="width:100%;background-color:#f2f5fb;"><tr><td class="outer-pad" align="center" style="padding:30px 12px;">
<table class="email-card" role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" bgcolor="#ffffff" style="width:100%;max-width:600px;background-color:#ffffff;border:1px solid #e1e7f2;border-radius:18px;overflow:hidden;">
<tr><td align="center" bgcolor="#ffffff" style="padding:25px 20px 20px;background-color:#ffffff;border-bottom:4px solid #2447e8;">
{logo_html}<div style="margin-top:10px;font-size:21px;font-weight:900;letter-spacing:2px;color:#17244d;">FR BEISSHOP</div>
<div style="margin-top:5px;font-size:10px;font-weight:700;letter-spacing:1.7px;color:#68738c;">LO MEJOR PARA LOS MEJORES</div>
</td></tr>
<tr><td class="inner-pad" bgcolor="#ffffff" style="padding:32px 34px 13px;background-color:#ffffff;">
<div style="font-size:11px;font-weight:800;letter-spacing:1.5px;color:#2447e8;">BIENVENIDO A LA TIENDA</div>
<h1 class="welcome-title" style="margin:11px 0 12px;font-size:30px;line-height:1.2;color:#17203b;">Hola {safe_name},</h1>
<p class="email-copy" style="margin:0;font-size:16px;line-height:1.65;color:#56617b;">Gracias por unirte a FR BEISSHOP. Ya puedes explorar la tienda y consultar tus pedidos desde tu perfil.</p>
</td></tr>
<tr><td class="inner-pad" style="padding:17px 34px 25px;">
<table class="offer-card" role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f3f5ff" style="width:100%;background-color:#f3f5ff;border:1px solid #dce3ff;border-radius:15px;"><tr><td align="center" style="padding:23px 16px 22px;">
<div style="font-size:11px;font-weight:800;letter-spacing:1.3px;color:#2447e8;">UN REGALO PARA TU PRIMERA COMPRA</div>
<div style="margin:10px 0 1px;font-size:40px;line-height:1.1;font-weight:900;color:#17244d;">10% OFF</div>
<div style="font-size:13px;color:#56617b;">en el subtotal de productos</div>
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:17px auto 0;"><tr><td align="center" bgcolor="#ffffff" style="padding:11px 19px;border:2px dashed #2447e8;border-radius:9px;background-color:#ffffff;color:#17244d;font-size:19px;font-weight:900;letter-spacing:2px;">{coupon_code}</td></tr></table>
<p class="email-copy" style="margin:13px 0 0;font-size:12px;line-height:1.55;color:#56617b;">Ingresa el código en tu carrito. Válido una vez en tu primera compra.</p>
</td></tr></table></td></tr>
<tr><td align="center" bgcolor="#ffffff" style="padding:0 24px 29px;background-color:#ffffff;">
<a href="{store_url}" style="display:inline-block;padding:14px 25px;border-radius:9px;background-color:#2447e8;color:#ffffff;text-decoration:none;font-size:14px;font-weight:800;">Explorar la tienda</a>
</td></tr>
<tr><td align="center" bgcolor="#f7f8fc" style="padding:17px 20px;background-color:#f7f8fc;color:#68738c;font-size:11px;line-height:1.55;">FR BEISSHOP · Mexicali, Baja California<br>Gracias por elegirnos.{unsubscribe_html}</td></tr>
</table></td></tr></table></body></html>"""
    body.add_alternative(html_body, subtype="html")
    message.attach(body)
    if logo_bytes:
        # Keep the image beside the alternative body so mobile clients can resolve its CID.
        message.add_related(
            logo_bytes, maintype="image", subtype="png", cid=logo_cid,
            filename="fr-beisshop-logo.png", disposition="inline",
        )
    return _send_email(message)


def _order_email_details(order, lines):
    """Build the readable order section shared by customer and store emails."""
    line_text = []
    for line in lines:
        customizations = line.get("customizations") or {}
        customization_text = ""
        if customizations:
            customization_text = " (" + "; ".join(
                f"{label}: {value}" for label, value in customizations.items()
            ) + ")"
        line_text.append(
            f"- {line.get('quantity', 0)} x {line.get('name', 'Producto')}"
            f"{customization_text} — {format_mxn(line.get('subtotal', 0))} MXN"
        )
    delivery = "Entrega personal el mismo día en Mexicali" if order.get("delivery_method") == "local" else "Envío a domicilio"
    address = ", ".join(
        value for value in (
            order.get("address", ""),
            order.get("neighborhood", ""),
            order.get("city", ""),
            order.get("state", ""),
            f"C.P. {order.get('postal_code', '')}" if order.get("postal_code") else "",
        ) if value
    )
    shipping_fee = float(order.get("shipping_fee", 0) or 0)
    discount = float(order.get("discount", 0) or 0)
    summary = [
        f"Pedido #{order.get('id')}",
        f"Cliente: {order.get('customer_name', '')}",
        f"Correo: {order.get('customer_email', '')}",
        f"Teléfono: {order.get('phone', '')}",
        f"Entrega: {delivery}",
    ]
    if address:
        summary.append(f"Dirección: {address}")
    summary.extend([
        "",
        "Artículos:",
        *line_text,
        "",
        f"Descuento: {format_mxn(discount)} MXN" if discount else "",
        f"Envío: {format_mxn(shipping_fee)} MXN" if shipping_fee else "Envío: $0.00 MXN",
        f"Total: {format_mxn(order.get('total', 0))} MXN",
    ])
    return "\n".join(line for line in summary if line != "")


def send_order_confirmation(order_id, customer_email, customer_name, total, lines, payment_method, order=None):
    """Send the paid-order confirmation to the customer when SMTP is configured."""
    if not (customer_email and is_valid_email(customer_email) and email_is_configured()):
        return False
    order_data = dict(order or {})
    order_data.update({
        "id": order_id,
        "customer_email": customer_email,
        "customer_name": customer_name,
        "total": total,
    })
    message = EmailMessage()
    message["Subject"] = f"FR BEISSHOP | Pedido #{order_id} confirmado"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = customer_email
    if EMAIL_REPLY_TO and is_valid_email(EMAIL_REPLY_TO):
        message["Reply-To"] = EMAIL_REPLY_TO
    details = _order_email_details(order_data, lines)
    guide_text = f"\nDescarga tu guía de envío: {order_data['shipping_label_url']}\n" if order_data.get("shipping_label_url") else ""
    message.set_content(
        f"Hola {customer_name},\n\n"
        f"Tu pago con Stripe fue confirmado. Estos son los detalles de tu pedido:\n\n"
        f"{details}\n{guide_text}\n"
        "Te contactaremos para coordinar la entrega y resolver cualquier duda.\n\n"
        "FR BEISSHOP"
    )
    return _send_email(message)


def send_shop_order_notification(order, lines):
    """Notify the store about a paid order, replying to the buyer when possible."""
    customer_email = order.get("customer_email", "")
    if not (SHOP_EMAIL and is_valid_email(SHOP_EMAIL) and email_is_configured()):
        return False
    message = EmailMessage()
    message["Subject"] = f"FR BEISSHOP | Nuevo pedido pagado #{order.get('id')}"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = SHOP_EMAIL
    if customer_email and is_valid_email(customer_email):
        message["Reply-To"] = customer_email
    details = _order_email_details(order, lines)
    shipment_details = []
    if order.get("shipping_carrier"):
        shipment_details.append(f"Transportista: {order['shipping_carrier']}")
    if order.get("tracking_number"):
        shipment_details.append(f"Número de guía: {order['tracking_number']}")
    if order.get("shipping_label_url"):
        shipment_details.append(f"Descarga la guía: {order['shipping_label_url']}")
    shipment_text = "\n".join(shipment_details) if shipment_details else "La guía se está generando en Skydropx."
    message.set_content(
        "Se confirmó un nuevo pago en Stripe. Revisa el pedido desde el panel de administración.\n\n"
        f"{details}\n\n"
        f"{shipment_text}\n"
    )
    return _send_email(message)


def is_customized_bat_order(lines):
    for line in lines:
        if not isinstance(line, dict) or not line.get("customizations"):
            continue
        category = str(line.get("category", "")).strip().casefold()
        product_name = str(line.get("name", "")).casefold()
        if category == "bat" or "bat" in product_name:
            return True
    return False


def send_custom_bat_order_notifications(order, lines):
    """Send one separate order alert to each configured custom-bat recipient."""
    if not email_is_configured():
        return False
    details = _order_email_details(order, lines)
    shipment_details = []
    if order.get("shipping_carrier"):
        shipment_details.append(f"Transportista: {order['shipping_carrier']}")
    if order.get("tracking_number"):
        shipment_details.append(f"Número de guía: {order['tracking_number']}")
    if order.get("shipping_label_url"):
        shipment_details.append(f"Descarga la guía: {order['shipping_label_url']}")
    shipment_text = "\n".join(shipment_details) if shipment_details else "La guía se está generando en Skydropx."
    sent_any = False
    for recipient in CUSTOM_BAT_ORDER_ALERT_EMAILS:
        if not is_valid_email(recipient):
            continue
        message = EmailMessage()
        message["Subject"] = f"FR BEISSHOP | Bat personalizado pagado · Pedido #{order.get('id')}"
        message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
        message["To"] = recipient
        customer_email = order.get("customer_email", "")
        if customer_email and is_valid_email(customer_email):
            message["Reply-To"] = customer_email
        message.set_content(
            "Se confirmó el pago de un pedido que incluye un bat personalizado. "
            "El pedido ya está disponible en el panel de administración.\n\n"
            f"{details}\n\n{shipment_text}\n\n"
            f"Abrir pedidos: {APP_BASE_URL}/admin/pedidos\n"
        )
        inline_images = []
        logo_bytes = b""
        try:
            logo_bytes = (Path(__file__).with_name("static") / "logo.png").read_bytes()
        except OSError:
            pass
        logo_cid = make_msgid(domain="frbeisshop.com") if logo_bytes else ""
        logo_markup = (
            f'<img src="cid:{logo_cid[1:-1]}" width="54" height="54" alt="FR BEISSHOP" '
            'style="display:block;width:54px;height:54px;object-fit:contain;border:0;">'
            if logo_cid else '<strong style="font-size:19px;letter-spacing:2px;color:#ffffff">FR BEISSHOP</strong>'
        )
        item_cards = []
        for line in lines:
            name = escape(str(line.get("name", "Producto")))
            customizations = line.get("customizations") or {}
            detail_rows = "".join(
                '<tr><td style="padding:5px 0;color:#68738c;font-size:13px;">'
                f'<strong style="color:#26304b">{escape(str(label))}:</strong> {escape(str(value))}'
                '</td></tr>'
                for label, value in customizations.items()
            ) if isinstance(customizations, dict) else ""
            preview_data = read_custom_bat_preview(line.get("custom_image", ""))
            preview_markup = ""
            if preview_data:
                preview_cid = make_msgid(domain="frbeisshop.com")
                inline_images.append((preview_cid, preview_data, "image", "png", "bat-personalizado.png"))
                preview_markup = (
                    f'<img src="cid:{preview_cid[1:-1]}" alt="Vista previa del bat personalizado" '
                    'width="220" style="display:block;width:100%;max-width:220px;height:auto;max-height:280px;'
                    'object-fit:contain;margin:0 auto;border:0;">'
                )
            item_cards.append(f'''<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin:0 0 14px;border:1px solid #e3e8f2;border-radius:14px;background:#ffffff;">
<tr><td style="padding:18px 20px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
<td valign="top" style="font-size:15px;font-weight:800;color:#17203b;">{int(line.get('quantity', 0) or 0)} × {name}</td>
<td align="right" valign="top" style="white-space:nowrap;font-size:14px;font-weight:800;color:#2447e8;">{format_mxn(line.get('subtotal', 0))} MXN</td></tr></table>
{f'<div style="margin:16px 0;padding:12px;background:#f5f7fc;border-radius:10px;text-align:center">{preview_markup}</div>' if preview_markup else ''}
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{detail_rows}</table></td></tr></table>''')
        address = ", ".join(value for value in (
            order.get("address", ""), order.get("neighborhood", ""), order.get("city", ""),
            order.get("state", ""), f"C.P. {order.get('postal_code', '')}" if order.get("postal_code") else "",
        ) if value)
        customer_name = escape(str(order.get("customer_name", "")))
        customer_email_html = escape(str(customer_email))
        phone_html = escape(str(order.get("phone", "")))
        delivery = "Entrega personal en Mexicali" if order.get("delivery_method") == "local" else "Envío a domicilio"
        admin_url = escape(f"{APP_BASE_URL}/admin/pedidos", quote=True)
        tracking_html = escape(str(order.get("tracking_number", "")))
        label_url = escape(str(order.get("shipping_label_url", "")), quote=True)
        shipping_html = (
            f'<strong style="color:#17203b;">Transportista:</strong> {escape(str(order.get("shipping_carrier", "Skydropx")))}'
            f'{f"<br><strong style=\"color:#17203b;\">Guía:</strong> {tracking_html}" if tracking_html else ""}'
            f'{f"<br><a href=\"{label_url}\" style=\"color:#2447e8;font-weight:800;\">Descargar guía de envío</a>" if label_url else "<br>La guía se está generando en Skydropx."}'
        )
        html_body = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:24px 10px;background:#f2f5fb;font-family:Arial,Helvetica,sans-serif;color:#17203b;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr><td align="center">
<table role="presentation" width="620" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:620px;background:#ffffff;border:1px solid #e1e7f2;border-radius:18px;overflow:hidden;">
<tr><td style="padding:20px 26px;background:#17244d;border-bottom:4px solid #2447e8;"><table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr><td valign="middle" style="padding-right:13px;">{logo_markup}</td><td valign="middle"><div style="font-size:17px;font-weight:900;letter-spacing:2px;color:#ffffff;">FR BEISSHOP</div><div style="margin-top:4px;font-size:10px;letter-spacing:1.2px;color:#dbe3ff;">LO MEJOR PARA LOS MEJORES</div></td></tr></table></td></tr>
<tr><td style="padding:28px 28px 12px;"><div style="font-size:11px;font-weight:800;letter-spacing:1.5px;color:#2447e8;">NUEVO PEDIDO PAGADO</div><h1 style="margin:9px 0 8px;font-size:27px;line-height:1.2;color:#17203b;">Bat personalizado listo</h1><p style="margin:0;color:#68738c;font-size:14px;line-height:1.6;">Pedido #{escape(str(order.get('id', '')))} · Confirmado y disponible en administración.</p></td></tr>
<tr><td style="padding:12px 28px 8px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f7fc;border-radius:12px;"><tr><td style="padding:16px 18px;font-size:13px;line-height:1.8;color:#59647d;"><strong style="color:#17203b;">Cliente:</strong> {customer_name}<br><strong style="color:#17203b;">Correo:</strong> {customer_email_html}<br><strong style="color:#17203b;">Teléfono:</strong> {phone_html}<br><strong style="color:#17203b;">Entrega:</strong> {escape(delivery)}{f'<br><strong style="color:#17203b;">Dirección:</strong> {escape(address)}' if address else ''}<br>{shipping_html}</td></tr></table></td></tr>
<tr><td style="padding:18px 28px 4px;"><h2 style="margin:0 0 12px;font-size:16px;color:#17203b;">Diseño y artículos</h2>{''.join(item_cards)}</td></tr>
<tr><td style="padding:4px 28px 24px;"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-top:1px solid #e3e8f2;"><tr><td style="padding:16px 0 0;color:#68738c;font-size:13px;">Descuento</td><td align="right" style="padding:16px 0 0;color:#26304b;font-size:13px;">{format_mxn(order.get('discount', 0))} MXN</td></tr><tr><td style="padding:7px 0;color:#68738c;font-size:13px;">Envío</td><td align="right" style="padding:7px 0;color:#26304b;font-size:13px;">{format_mxn(order.get('shipping_fee', 0))} MXN</td></tr><tr><td style="padding:10px 0 0;font-size:16px;font-weight:800;color:#17203b;">Total pagado</td><td align="right" style="padding:10px 0 0;font-size:18px;font-weight:900;color:#2447e8;">{format_mxn(order.get('total', 0))} MXN</td></tr></table></td></tr>
<tr><td align="center" style="padding:0 28px 28px;"><a href="{admin_url}" style="display:inline-block;padding:14px 23px;border-radius:9px;background:#2447e8;color:#ffffff;text-decoration:none;font-size:14px;font-weight:800;">Abrir pedido en administración</a></td></tr>
<tr><td align="center" style="padding:16px;background:#f7f8fc;color:#68738c;font-size:11px;">FR BEISSHOP · Mexicali, Baja California</td></tr></table></td></tr></table></body></html>'''
        message.add_alternative(html_body, subtype="html")
        html_part = message.get_payload()[-1]
        if logo_bytes:
            inline_images.append((logo_cid, logo_bytes, "image", "png", "fr-beisshop-logo.png"))
        try:
            for cid, image_data, maintype, subtype, filename in inline_images:
                html_part.add_related(image_data, maintype=maintype, subtype=subtype, cid=cid,
                                      filename=filename, disposition="inline")
            sent = _send_email(message)
            sent_any = sent or sent_any
            if not sent:
                app.logger.error("No se pudo enviar el aviso del pedido #%s a %s.", order.get("id"), recipient)
        except Exception:
            app.logger.exception("No se pudo preparar el aviso del pedido #%s a %s.", order.get("id"), recipient)
    return sent_any


def notify_paid_order(order, payment_method="stripe"):
    """Send customer and store notifications after a payment is confirmed."""
    lines = get_order_lines(order)
    customer_sent = send_order_confirmation(
        order["id"], order.get("customer_email", ""), order.get("customer_name", ""),
        order.get("total", 0), lines, payment_method, order=order,
    )
    if is_customized_bat_order(lines):
        shop_sent = send_custom_bat_order_notifications(order, lines)
    else:
        shop_sent = send_shop_order_notification(order, lines)
    return customer_sent or shop_sent


def send_order_status_update(order, previous_status=""):
    """Tell the buyer when the store changes the order status or shipment details."""
    customer_email = order.get("customer_email", "")
    if not (customer_email and is_valid_email(customer_email) and email_is_configured()):
        return False
    status = order.get("status", "Actualizado")
    message = EmailMessage()
    message["Subject"] = f"FR BEISSHOP | Pedido #{order.get('id')} actualizado"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = customer_email
    if EMAIL_REPLY_TO and is_valid_email(EMAIL_REPLY_TO):
        message["Reply-To"] = EMAIL_REPLY_TO
    details = _order_email_details(order, get_order_lines(order))
    shipment = []
    if order.get("shipping_carrier"):
        shipment.append(f"Transportista: {order['shipping_carrier']}")
    if order.get("tracking_number"):
        shipment.append(f"Número de guía: {order['tracking_number']}")
    if order.get("shipping_label_url"):
        shipment.append(f"Descarga la guía: {order['shipping_label_url']}")
    if order.get("shipping_note"):
        shipment.append(f"Nota de entrega: {order['shipping_note']}")
    shipment_text = "\n".join(shipment) if shipment else "Sin datos de guía nuevos."
    previous_text = f"Estado anterior: {previous_status}\n" if previous_status else ""
    message.set_content(
        f"Hola {order.get('customer_name', '')},\n\n"
        f"El estado de tu pedido #{order.get('id')} cambió a: {status}.\n"
        f"{previous_text}\n"
        f"{shipment_text}\n\n"
        f"{details}\n\n"
        "Si tienes alguna duda, responde a este correo.\n\n"
        "FR BEISSHOP"
    )
    return _send_email(message)


def create_stripe_checkout_session(order_id, customer_email, lines, total, shipping_fee=0, discount=0, shipping_rate_id="", shipping_quote_id="", expires_at=None):
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("Stripe no está configurado.")
    try:
        import stripe
    except ImportError as error:
        raise RuntimeError("Falta instalar la dependencia de Stripe.") from error

    stripe.api_key = STRIPE_SECRET_KEY
    line_items = []
    for line in lines:
        price = max(int(round(float(line.get("unit_price", 0)) * 100)), 1)
        customizations = line.get("customizations") or {}
        customization_description = "; ".join(
            f"{label}: {value}" for label, value in customizations.items()
        ) if isinstance(customizations, dict) else ""
        product_description = str(line.get("description", ""))
        if customization_description:
            product_description = f"{product_description} · {customization_description}".strip(" ·")
        line_items.append({
            "price_data": {
                "currency": "mxn",
                "product_data": {
                    "name": str(line.get("name", "Producto"))[:120],
                    "description": product_description[:500],
                },
                "unit_amount": price,
            },
            "quantity": max(int(line.get("quantity", 1)), 1),
        })
    if shipping_fee > 0:
        line_items.append({
            "price_data": {
                "currency": "mxn",
                "product_data": {
                    "name": "Envío a domicilio",
                    "description": "Costo estimado de envío desde Mexicali.",
                },
                "unit_amount": max(int(round(float(shipping_fee) * 100)), 1),
            },
            "quantity": 1,
        })
    checkout_args = {
        "mode": "payment",
        "line_items": line_items,
        "customer_email": customer_email,
        "client_reference_id": str(order_id),
        "metadata": {
            "order_id": str(order_id),
            "shipping_rate_id": str(shipping_rate_id or "")[:120],
            "shipping_quote_id": str(shipping_quote_id or "")[:120],
        },
        "success_url": f"{APP_BASE_URL}/pago/stripe/exito?session_id={{CHECKOUT_SESSION_ID}}&order_id={order_id}",
        "cancel_url": f"{APP_BASE_URL}/pago/stripe/cancelado?order_id={order_id}",
        "phone_number_collection": {"enabled": True},
    }
    if expires_at is not None:
        checkout_args["expires_at"] = int(expires_at)
    discount = max(round(float(discount or 0), 2), 0)
    if discount:
        stripe_coupon = stripe.Coupon.create(
            amount_off=max(int(round(discount * 100)), 1),
            currency="mxn",
            duration="once",
            name=f"FR BEISSHOP pedido #{order_id}",
        )
        checkout_args["discounts"] = [{"coupon": stripe_coupon.id}]
    checkout_session = stripe.checkout.Session.create(**checkout_args)
    return checkout_session


def mark_stripe_order_paid(session_object):
    metadata = session_object.get("metadata", {}) if hasattr(session_object, "get") else {}
    order_id = metadata.get("order_id") or session_object.get("client_reference_id")
    try:
        order_id = int(order_id)
    except (TypeError, ValueError):
        return None, False
    with closing(get_users_db()) as db:
        row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return None, False
        if row["status"] in {"Cancelado", "Reembolsado"} or int(row["stock_released"] or 0):
            return None, False
        status_text = str(row["status"] or "").lower()
        already_paid = status_text in {"pagado", "enviado", "completado"} or "prepar" in status_text
        db.execute(
            "UPDATE orders SET status = 'Pagado', stripe_session_id = ?, stripe_payment_intent_id = ? WHERE id = ?",
            (session_object.get("id", ""), session_object.get("payment_intent", "") or "", order_id),
        )
        if not already_paid and row["coupon_code"]:
            db.execute("UPDATE coupons SET used_count = used_count + 1 WHERE code = ?", (row["coupon_code"],))
        db.commit()
    order = dict(row)
    order.update({
        "status": "Pagado",
        "stripe_session_id": session_object.get("id", "") or order.get("stripe_session_id", ""),
        "stripe_payment_intent_id": session_object.get("payment_intent", "") or order.get("stripe_payment_intent_id", ""),
    })
    if order.get("delivery_method") != "local":
        order, _shipping_error = create_skydropx_shipment(order)
    return order, not already_paid


def restore_order_stock(order_id, final_status="Cancelado"):
    restockable_statuses = {"Pago pendiente", "Pagado", "Enviado", "Completado", "Reembolsado"}
    with PRODUCTS_LOCK, closing(get_users_db()) as db:
        row = db.execute(
            "SELECT status, lines_json, stock_released FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if not row or (row["status"] not in restockable_statuses and "prepar" not in str(row["status"] or "").lower()) or int(row["stock_released"] or 0):
            return False
        lines = get_order_lines(row)
        cursor = db.execute(
            "UPDATE orders SET status = ?, stock_released = 1 WHERE id = ? AND stock_released = 0",
            (final_status, order_id),
        )
        if not cursor.rowcount:
            return False
        for line in lines:
            try:
                product_id = int(line.get("product_id", 0))
                quantity = max(int(line.get("quantity", 0)), 0)
            except (AttributeError, TypeError, ValueError):
                continue
            product = PRODUCT_BY_ID.get(product_id)
            if product and quantity:
                product["stock"] = int(product.get("stock", 0)) + quantity
        save_products()
        db.commit()
    return True


def release_expired_stock_reservations():
    now = datetime.now().isoformat(timespec="minutes")
    with closing(get_users_db()) as db:
        rows = db.execute(
            "SELECT id FROM orders WHERE status = 'Pago pendiente' AND stock_released = 0 AND auction_id = 0 AND stock_reserved_until != '' AND stock_reserved_until < ?",
            (now,),
        ).fetchall()
    for row in rows:
        restore_order_stock(row["id"])


def reserve_order_stock(items):
    """Atomically reserve all cart units so two checkouts cannot oversell stock."""
    with PRODUCTS_LOCK:
        for item in items:
            try:
                requested = int(item.get("quantity", 0))
                available = int(item["product"].get("stock", 0))
            except (AttributeError, TypeError, ValueError):
                return False, "este producto"
            if requested <= 0 or requested > available:
                return False, item["product"].get("name", "este producto")
        for item in items:
            product = item["product"]
            product["stock"] = max(int(product.get("stock", 0)) - int(item["quantity"]), 0)
        save_products()
    return True, ""


def is_admin_password_valid(password):
    if ADMIN_PASSWORD and hmac.compare_digest(password, ADMIN_PASSWORD):
        return True
    if ADMIN_PASSWORD_HASH:
        try:
            return check_password_hash(ADMIN_PASSWORD_HASH, password)
        except ValueError:
            return False
    return False


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": csrf_token}


@app.before_request
def protect_post_requests():
    if request.method != "POST":
        return None
    if request.endpoint == "admin_homepage" and session.get("is_admin"):
        request.max_content_length = 96 * 1024 * 1024
    if request.path == "/webhooks/stripe":
        return None
    expected_token = session.get("csrf_token")
    received_token = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if (not expected_token or not received_token
            or not hmac.compare_digest(expected_token, received_token)):
        abort(400, description="La sesión expiró. Recarga la página e inténtalo de nuevo.")
    return None


@app.errorhandler(404)
def page_not_found(error):
    return render_template("error.html", code=404, title="P&aacute;gina no encontrada", message="No encontramos esa p&aacute;gina."), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html", code=500, title="Algo sali&oacute; mal", message="No pudimos completar la solicitud. Int&eacute;ntalo de nuevo."), 500

PRODUCTS = [
    {
        "id": 1,
        "name": "Guante de infield Pro",
        "category": "Béisbol",
        "price": 1499,
        "description": "Piel sintética suave, 11.5 pulgadas.",
        "tag": "Más vendido",
        "image": "https://images.unsplash.com/photo-1566577739112-5180d4bf9390?auto=format&fit=crop&w=900&q=85",
    },
    {
        "id": 2,
        "name": "Bat de aluminio 32\"",
        "category": "Béisbol",
        "price": 1890,
        "description": "Balance ligero para entrenamientos y juego.",
        "tag": "Béisbol",
        "image": "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=900&q=85",
    },
    {
        "id": 3,
        "name": "Set de pelotas de softball",
        "category": "Softball",
        "price": 799,
        "description": "Paquete de 6 pelotas para práctica y equipo.",
        "tag": "Softball",
        "image": "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=900&q=85",
    },
    {
        "id": 4,
        "name": "Casco de bateo",
        "category": "Béisbol",
        "price": 1099,
        "description": "Protección cómoda con ventilación lateral.",
        "tag": "Protección",
        "image": "https://images.unsplash.com/photo-1566577739112-5180d4bf9390?auto=format&fit=crop&w=900&q=85",
    },
    {
        "id": 5,
        "name": "Bat de softball 34\"",
        "category": "Softball",
        "price": 2290,
        "description": "Diseño de aluminio para juego recreativo.",
        "tag": "Softball",
        "image": "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=900&q=85",
    },
    {
        "id": 6,
        "name": "Guante juvenil 10.5\"",
        "category": "Béisbol",
        "price": 899,
        "description": "Ajuste juvenil para aprender y jugar con confianza.",
        "tag": "Juvenil",
        "image": "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=900&q=85",
    },
]


def repair_mojibake(value):
    """Repair legacy UTF-8 text that was decoded as Latin-1 more than once."""
    if isinstance(value, str):
        repaired = value
        markers = ("\u00c3", "\u00c2", "\u00e2", "\u00f0", "\ufffd")
        for _ in range(3):
            if not any(marker in repaired for marker in markers):
                break
            try:
                candidate = repaired.encode("latin1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
            if candidate == repaired:
                break
            repaired = candidate
        return repaired
    if isinstance(value, list):
        return [repair_mojibake(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_mojibake(item) for key, item in value.items()}
    return value


products_encoding_migrated = False


def load_products():
    global products_encoding_migrated
    if not PRODUCTS_FILE.exists():
        repaired_products = repair_mojibake(PRODUCTS)
        products_encoding_migrated = repaired_products != PRODUCTS
        return repaired_products
    try:
        saved_products = json.loads(PRODUCTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        repaired_products = repair_mojibake(PRODUCTS)
        products_encoding_migrated = repaired_products != PRODUCTS
        return repaired_products
    if not isinstance(saved_products, list):
        return repair_mojibake(PRODUCTS)
    repaired_products = repair_mojibake(saved_products)
    products_encoding_migrated = repaired_products != saved_products
    return repaired_products


def normalize_product_images(product):
    """Keep a backward-compatible primary image and a gallery list for every product."""
    raw_images = product.get("images")
    if isinstance(raw_images, str):
        raw_images = [raw_images]
    if not isinstance(raw_images, list):
        raw_images = [product.get("image", "")]
    images = []
    for image in raw_images:
        image = str(image or "").strip()
        if image and image not in images:
            images.append(image)
    if not images:
        images = ["/static/logo.png"]
    changed = product.get("images") != images or product.get("image") != images[0]
    product["images"] = images
    product["image"] = images[0]
    return changed


def product_gallery_options(product):
    """Return saved gallery images plus bundled bat reference photos for the admin picker."""
    options = []
    raw_images = product.get("images") or [product.get("image", "")]
    for image in raw_images:
        image = str(image or "").strip()
        if image and image not in options:
            options.append(image)
    if product.get("category") == "Bat" and product.get("customizable"):
        reference_folder = Path(__file__).with_name("static") / "bat-photos"
        try:
            reference_files = sorted(reference_folder.iterdir(), key=lambda path: path.name.lower())
        except OSError:
            reference_files = []
        for reference_file in reference_files:
            if reference_file.is_file() and reference_file.suffix.lower().lstrip(".") in ALLOWED_IMAGE_EXTENSIONS:
                image_url = f"/static/bat-photos/{reference_file.name}"
                if image_url not in options:
                    options.append(image_url)
    return options


PRODUCTS = load_products()
products_stock_migrated = False
products_active_migrated = False
products_images_migrated = False
products_brand_migrated = False
products_bat_views_migrated = False
for product in PRODUCTS:
    if normalize_product_images(product):
        products_images_migrated = True
    product.setdefault("views", 0)
    if "stock" not in product:
        product["stock"] = 10
        products_stock_migrated = True
    if "active" not in product:
        product["active"] = True
        products_active_migrated = True
    if "brand_featured" not in product:
        product["brand_featured"] = False
        products_brand_migrated = True
    if product.get("customizable") and not isinstance(product.get("bat_views"), dict):
        product["bat_views"] = {}
        products_bat_views_migrated = True


def save_products():
    with PRODUCTS_LOCK:
        PRODUCTS_FILE.write_text(
            json.dumps(PRODUCTS, ensure_ascii=False, indent=2), encoding="utf-8"
        )


DELETED_PRODUCTS_RETENTION_DAYS = 30


def _parse_deleted_product_datetime(value, fallback=None):
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def load_deleted_products():
    """Load the product recycle bin and discard items older than 30 days."""
    try:
        saved = json.loads(DELETED_PRODUCTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(saved, list):
        return []

    now = datetime.now()
    kept = []
    changed = False
    for entry in saved:
        if not isinstance(entry, dict) or not isinstance(entry.get("product"), dict):
            changed = True
            continue
        deleted_at = _parse_deleted_product_datetime(entry.get("deleted_at"), now)
        expires_at = _parse_deleted_product_datetime(
            entry.get("expires_at"), deleted_at + timedelta(days=DELETED_PRODUCTS_RETENTION_DAYS)
        )
        if expires_at <= now:
            changed = True
            continue
        normalized = dict(entry)
        normalized["deleted_at"] = deleted_at.isoformat(timespec="seconds")
        normalized["expires_at"] = expires_at.isoformat(timespec="seconds")
        if normalized != entry:
            changed = True
        kept.append(normalized)
    if changed:
        try:
            DELETED_PRODUCTS_FILE.write_text(
                json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
    return kept


def save_deleted_products():
    with PRODUCTS_LOCK:
        DELETED_PRODUCTS_FILE.write_text(
            json.dumps(DELETED_PRODUCTS, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def prune_deleted_products():
    """Remove expired recycle-bin entries while the application is running."""
    global DELETED_PRODUCTS
    now = datetime.now()
    with PRODUCTS_LOCK:
        kept = []
        changed = False
        for entry in DELETED_PRODUCTS:
            deleted_at = _parse_deleted_product_datetime(entry.get("deleted_at"), now)
            expires_at = _parse_deleted_product_datetime(
                entry.get("expires_at"), deleted_at + timedelta(days=DELETED_PRODUCTS_RETENTION_DAYS)
            )
            if expires_at <= now:
                changed = True
                continue
            kept.append(entry)
        if changed:
            DELETED_PRODUCTS = kept
            save_deleted_products()
    return DELETED_PRODUCTS


def deleted_products_for_admin():
    """Return recycle-bin entries with the remaining retention time for the admin UI."""
    prune_deleted_products()
    now = datetime.now()
    entries = []
    with PRODUCTS_LOCK:
        source = list(DELETED_PRODUCTS)
    for entry in source:
        expires_at = _parse_deleted_product_datetime(entry.get("expires_at"), now)
        remaining_seconds = max((expires_at - now).total_seconds(), 0)
        item = dict(entry)
        item["days_left"] = max(1, math.ceil(remaining_seconds / 86400))
        entries.append(item)
    return sorted(entries, key=lambda entry: entry.get("expires_at", ""))


DELETED_PRODUCTS = load_deleted_products()


def load_auctions():
    if not AUCTIONS_FILE.exists():
        return []
    try:
        saved_auctions = json.loads(AUCTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return saved_auctions if isinstance(saved_auctions, list) else []


AUCTIONS = load_auctions()


def save_auctions():
    AUCTIONS_FILE.write_text(
        json.dumps(AUCTIONS, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_local_datetime(value):
    try:
        return datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def auction_is_closed(auction):
    deadline = parse_local_datetime(auction.get("ends_at"))
    return not deadline or datetime.now() >= deadline


def auction_current_price(auction):
    bids = auction.get("bids", [])
    amounts = []
    for bid in bids if isinstance(bids, list) else []:
        try:
            amounts.append(float(bid.get("amount", 0)))
        except (AttributeError, TypeError, ValueError):
            continue
    try:
        starting_price = float(auction.get("price", 0))
    except (TypeError, ValueError):
        starting_price = 0
    return max([starting_price, *amounts]) if amounts else starting_price


def auction_ranked_bidders(auction):
    """Rank distinct bidders by their best bid, favoring the latest tie."""
    best_by_user = {}
    bids = auction.get("bids", [])
    for index, bid in enumerate(bids if isinstance(bids, list) else []):
        try:
            amount = float(bid.get("amount", 0))
        except (AttributeError, TypeError, ValueError):
            continue
        if not math.isfinite(amount) or amount <= 0:
            continue
        user_id = bid.get("user_id")
        bidder_key = f"user:{user_id}" if user_id is not None else f"bid:{index}"
        previous = best_by_user.get(bidder_key)
        if not previous or amount > previous["amount"] or (amount == previous["amount"] and index > previous["_bid_index"]):
            ranked_bid = dict(bid)
            ranked_bid["amount"] = amount
            ranked_bid["_bid_index"] = index
            best_by_user[bidder_key] = ranked_bid
    return sorted(best_by_user.values(), key=lambda bid: (bid["amount"], bid["_bid_index"]), reverse=True)


def auction_leader(auction):
    ranked = auction_ranked_bidders(auction)
    return ranked[0] if ranked else None


def auction_offer_position(auction):
    try:
        return max(int(auction.get("winner_position", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def auction_current_offer(auction):
    if auction.get("payment_offer_exhausted_at"):
        return None
    ranked = auction_ranked_bidders(auction)
    position = auction_offer_position(auction)
    return ranked[position] if position < len(ranked) else None


def auction_minimum_bid(auction):
    try:
        increment = float(auction.get("min_increment", 50))
    except (TypeError, ValueError):
        increment = 50
    return round(auction_current_price(auction) + max(increment, 1), 2)


def build_auction_cards():
    """Build the shared auction view used by customers and administration."""
    cards = []
    for auction_item in AUCTIONS:
        card = dict(auction_item)
        bids = auction_item.get("bids", [])
        card["current_price"] = auction_current_price(auction_item)
        card["minimum_bid"] = auction_minimum_bid(auction_item)
        card["closed"] = auction_is_closed(auction_item)
        card["bid_count"] = len(bids) if isinstance(bids, list) else 0
        card["bids"] = list(reversed(bids)) if isinstance(bids, list) else []
        card["offer_position"] = auction_offer_position(auction_item)
        card["leader"] = auction_current_offer(auction_item) if card["closed"] else auction_leader(auction_item)
        card["winner"] = card["leader"] if card["closed"] else None
        if card["closed"] and card["offer_position"] > 0 and card["leader"]:
            card["current_price"] = card["leader"]["amount"]
        for private_field in (
            "winner_checkout_token", "winner_checkout_expires_at", "winner_notification_claimed_at",
            "winner_reminder_sent_at", "winner_reminder_claimed_at", "winner_order_id",
        ):
            card.pop(private_field, None)
        cards.append(card)
    return cards


def get_active_auction_announcements():
    """Return open auctions ordered by the closest closing time."""
    finalize_closed_auctions()
    active = [dict(item) for item in AUCTIONS if not auction_is_closed(item)]
    return sorted(
        active,
        key=lambda item: parse_local_datetime(item.get("ends_at")) or datetime.max,
    )


def build_auction_checkout_url(auction_item, checkout_token):
    auction_id = int(auction_item.get("id", 0) or 0)
    try:
        checkout_path = url_for(
            "auction_checkout", auction_id=auction_id, token=checkout_token
        )
    except RuntimeError:
        checkout_path = f"/subasta/{auction_id}/pago?token={quote(str(checkout_token), safe='')}"
    return f"{APP_BASE_URL}{checkout_path}"


def notify_auction_winner(auction_item, winner):
    if not winner or not winner.get("user_id") or not email_is_configured():
        return False
    with closing(get_users_db()) as db:
        user = db.execute("SELECT email, name FROM users WHERE id = ?", (winner["user_id"],)).fetchone()
    if not user or not is_valid_email(user["email"]):
        return False
    checkout_token = str(auction_item.get("winner_checkout_token", "")).strip()
    if not checkout_token:
        return False
    checkout_url = build_auction_checkout_url(auction_item, checkout_token)
    message = EmailMessage()
    is_runner_up_offer = auction_offer_position(auction_item) == 1
    message["Subject"] = (
        f"Oferta para ti: {auction_item.get('name', 'Artículo')}"
        if is_runner_up_offer else f"Ganaste la subasta: {auction_item.get('name', 'Artículo')}"
    )
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = user["email"]
    if EMAIL_REPLY_TO:
        message["Reply-To"] = EMAIL_REPLY_TO
    if is_runner_up_offer:
        opening = (
            f"El artículo {auction_item.get('name', 'de la subasta')} está disponible para la siguiente oferta "
            "y queremos ofrecértelo a ti."
        )
        amount_label = "El importe de tu oferta es"
    else:
        opening = f"Ganaste la subasta de {auction_item.get('name', 'este artículo')} en FR BEISSHOP."
        amount_label = "Tu puja ganadora fue de"
    message.set_content(
        f"Hola {user['name']},\n\n"
        f"{opening}\n"
        f"{amount_label} {format_mxn(winner.get('amount', 0))} MXN.\n\n"
        "Completa tus datos de entrega y realiza el pago seguro desde este enlace:\n"
        f"{checkout_url}\n\n"
        f"Tienes {AUCTION_WINNER_PAYMENT_DAYS} días para pagar. Te enviaremos un recordatorio 24 horas antes del vencimiento. "
        "Después del pago generaremos la guía de envío.\n\n"
        "FR BEISSHOP"
    )
    return _send_email(message)


def notify_auction_payment_reminder(auction_item, winner):
    if not winner or not winner.get("user_id") or not email_is_configured():
        return False
    with closing(get_users_db()) as db:
        user = db.execute("SELECT email, name FROM users WHERE id = ?", (winner["user_id"],)).fetchone()
    if not user or not is_valid_email(user["email"]):
        return False
    checkout_token = str(auction_item.get("winner_checkout_token", "")).strip()
    if not checkout_token:
        return False
    checkout_url = build_auction_checkout_url(auction_item, checkout_token)
    expires = parse_local_datetime(auction_item.get("winner_checkout_expires_at"))
    deadline_text = expires.strftime("%d/%m/%Y a las %H:%M") if expires else "en 24 horas"
    message = EmailMessage()
    message["Subject"] = f"Recordatorio: completa tu pago de subasta"
    message["From"] = formataddr(("FR BEISSHOP", SMTP_FROM))
    message["To"] = user["email"]
    if EMAIL_REPLY_TO:
        message["Reply-To"] = EMAIL_REPLY_TO
    message.set_content(
        f"Hola {user['name']},\n\n"
        f"Te recordamos que la oferta por {auction_item.get('name', 'el artículo de subasta')} sigue disponible.\n"
        f"Importe: {format_mxn(winner.get('amount', 0))} MXN.\n"
        f"Tu enlace de pago vence el {deadline_text}.\n\n"
        "Completa tus datos y el pago seguro desde este enlace:\n"
        f"{checkout_url}\n\n"
        "Si ya realizaste el pago, puedes ignorar este recordatorio.\n\n"
        "FR BEISSHOP"
    )
    return _send_email(message)


def renew_auction_checkout_session(order_id, expected_session_id, deadline):
    """Replace an expired Stripe link without ending the bidder's full payment window."""
    if not STRIPE_SECRET_KEY or not deadline:
        return False
    with AUCTIONS_LOCK:
        with closing(get_users_db()) as db:
            row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row or row["status"] != "Pago pendiente" or int(row["stock_released"] or 0):
            return False
        current_session_id = str(row["stripe_session_id"] or "").strip()
        if current_session_id != str(expected_session_id or "").strip():
            return True

        now = datetime.now()
        remaining = deadline - now
        if remaining < timedelta(minutes=30):
            return False
        expires_at = min(now + timedelta(hours=24), deadline)
        try:
            lines = get_order_lines(row)
            shipping_fee = max(float(row["shipping_fee"] or 0), 0)
            discount = max(float(row["discount"] or 0), 0)
            product_total = max(float(row["total"] or 0) - shipping_fee + discount, 0)
            checkout_session = create_stripe_checkout_session(
                order_id, row["customer_email"], lines, product_total, shipping_fee, discount,
                row["shipping_rate_id"], row["shipping_quote_id"], expires_at.timestamp(),
            )
        except Exception:
            app.logger.exception("No se pudo renovar el enlace de pago de la subasta #%s.", row["auction_id"])
            return False

        with closing(get_users_db()) as db:
            cursor = db.execute(
                "UPDATE orders SET stripe_session_id = ? WHERE id = ? AND status = 'Pago pendiente' AND stock_released = 0 AND stripe_session_id = ?",
                (checkout_session.get("id", ""), order_id, current_session_id),
            )
            db.commit()
        if not cursor.rowcount:
            try:
                import stripe
                stripe.api_key = STRIPE_SECRET_KEY
                stripe.checkout.Session.expire(checkout_session.get("id", ""))
            except Exception:
                app.logger.exception("No se pudo cerrar un enlace de pago duplicado de subasta #%s.", row["auction_id"])
            return True
    return True


def auction_offer_order_state(auction_item, now):
    """Keep an auction offer pending until its advertised deadline, refreshing Stripe links as needed."""
    try:
        order_id = int(auction_item.get("winner_order_id", 0) or 0)
    except (TypeError, ValueError):
        order_id = 0
    if not order_id:
        return "none"
    with closing(get_users_db()) as db:
        row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return "cancelled"
    status = str(row["status"] or "").strip().casefold()
    if status == "pago pendiente":
        deadline = parse_local_datetime(auction_item.get("winner_checkout_expires_at"))
        reservation = parse_local_datetime(row["stock_reserved_until"])
        if deadline and reservation != deadline:
            with closing(get_users_db()) as db:
                db.execute("UPDATE orders SET stock_reserved_until = ? WHERE id = ? AND status = 'Pago pendiente'", (deadline.isoformat(timespec="minutes"), order_id))
                db.commit()
        deadline = deadline or reservation
        stripe_session_id = str(row["stripe_session_id"] or "").strip()
        if stripe_session_id:
            try:
                import stripe
                stripe.api_key = STRIPE_SECRET_KEY
                stripe_session = stripe.checkout.Session.retrieve(stripe_session_id)
                if stripe_session.get("payment_status") in {"paid", "no_payment_required"}:
                    paid_order, _should_notify = mark_stripe_order_paid(stripe_session)
                    return "paid" if paid_order else "cancelled"
                stripe_status = str(stripe_session.get("status", ""))
                if deadline and now < deadline:
                    if stripe_status == "open":
                        session_expires_at = float(stripe_session.get("expires_at", 0) or 0)
                        if session_expires_at > time.time():
                            return "pending"
                        stripe.checkout.Session.expire(stripe_session_id)
                        renew_auction_checkout_session(order_id, stripe_session_id, deadline)
                        return "pending"
                    if stripe_status == "expired":
                        renew_auction_checkout_session(order_id, stripe_session_id, deadline)
                    return "pending"
                if stripe_status == "open":
                    stripe.checkout.Session.expire(stripe_session_id)
                elif stripe_status != "expired":
                    return "pending"
            except Exception:
                return "pending"
        elif deadline and now < deadline:
            renew_auction_checkout_session(order_id, "", deadline)
            return "pending"
        if deadline and now < deadline:
            return "pending"
        restore_order_stock(order_id)
        return "cancelled"
    if status == "cancelado":
        return "cancelled"
    return "paid"


def finalize_closed_auctions():
    """Notify auction winners, remind them before expiry, then offer once to runner-up."""
    now = datetime.now()
    now_text = now.isoformat(timespec="minutes")
    with AUCTIONS_LOCK:
        snapshots = [dict(item) for item in AUCTIONS if auction_is_closed(item)]

    for snapshot in snapshots:
        auction_id = int(snapshot.get("id", 0) or 0)
        order_state = auction_offer_order_state(snapshot, now)
        action = ""
        payload = None
        with AUCTIONS_LOCK:
            current = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
            if not current or not auction_is_closed(current) or current.get("payment_offer_exhausted_at"):
                continue
            if current.get("winner_order_id") != snapshot.get("winner_order_id"):
                continue
            if order_state == "paid":
                if not current.get("winner_payment_completed_at"):
                    current["winner_payment_completed_at"] = now_text
                    save_auctions()
                continue
            if order_state == "cancelled":
                current.pop("winner_order_id", None)

            try:
                position = auction_offer_position(current)
            except (TypeError, ValueError):
                position = 0
            ranked = auction_ranked_bidders(current)
            if position >= len(ranked):
                current["payment_offer_exhausted_at"] = now_text
                current.pop("winner_checkout_token", None)
                save_auctions()
                continue
            winner = ranked[position]
            expires = parse_local_datetime(current.get("winner_checkout_expires_at"))
            notified = bool(current.get("winner_notified_at"))

            if order_state == "pending" and expires and now >= expires:
                continue

            if notified and expires and now >= expires:
                if position == 0 and len(ranked) > 1:
                    current["winner_position"] = 1
                    current["winner_checkout_token"] = secrets.token_urlsafe(32)
                    current["winner_checkout_expires_at"] = (
                        now + timedelta(days=AUCTION_WINNER_PAYMENT_DAYS)
                    ).isoformat(timespec="minutes")
                    current.pop("winner_notified_at", None)
                    current.pop("winner_reminder_sent_at", None)
                    current.pop("winner_reminder_claimed_at", None)
                    current.pop("winner_order_id", None)
                    current.pop("winner_payment_completed_at", None)
                    current["winner_notification_claimed_at"] = now_text
                    winner = ranked[1]
                    action = "winner"
                else:
                    current["payment_offer_exhausted_at"] = now_text
                    current.pop("winner_checkout_token", None)
                save_auctions()
                if action:
                    payload = (dict(current), winner, current["winner_checkout_token"], position + 1)
            elif not notified:
                if current.get("winner_notification_claimed_at"):
                    continue
                current["winner_position"] = position
                if not current.get("winner_checkout_token"):
                    current["winner_checkout_token"] = secrets.token_urlsafe(32)
                current["winner_checkout_expires_at"] = (
                    now + timedelta(days=AUCTION_WINNER_PAYMENT_DAYS)
                ).isoformat(timespec="minutes")
                current["winner_notification_claimed_at"] = now_text
                action = "winner"
                save_auctions()
                payload = (dict(current), winner, current["winner_checkout_token"], position)
            elif (expires and timedelta(0) < (expires - now) <= timedelta(hours=AUCTION_WINNER_REMINDER_HOURS)
                  and not current.get("winner_reminder_sent_at")
                  and not current.get("winner_reminder_claimed_at")):
                current["winner_reminder_claimed_at"] = now_text
                action = "reminder"
                save_auctions()
                payload = (dict(current), winner, current.get("winner_checkout_token", ""), position)

        if not payload:
            continue
        auction_item, winner, claimed_token, claimed_position = payload
        sent = (
            notify_auction_payment_reminder(auction_item, winner)
            if action == "reminder" else notify_auction_winner(auction_item, winner)
        )
        with AUCTIONS_LOCK:
            current = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
            if (not current or current.get("winner_checkout_token") != claimed_token
                    or auction_offer_position(current) != claimed_position):
                continue
            if sent and action == "reminder":
                current["winner_reminder_sent_at"] = datetime.now().isoformat(timespec="minutes")
            elif sent:
                current["winner_notified_at"] = datetime.now().isoformat(timespec="minutes")
            if action == "reminder":
                current.pop("winner_reminder_claimed_at", None)
            else:
                current.pop("winner_notification_claimed_at", None)
            save_auctions()


auctions_migrated = False
for auction_item in AUCTIONS:
    auction_item.setdefault("bids", [])
    auction_item.setdefault("min_increment", 50)
    for _field, _default in (("package_weight_kg", 0.5), ("package_length_cm", 30), ("package_width_cm", 20), ("package_height_cm", 15)):
        if _field not in auction_item:
            auction_item[_field] = _default
            auctions_migrated = True
if auctions_migrated:
    save_auctions()


def get_order_lines(order):
    try:
        lines = json.loads(order["lines_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        lines = []
    return lines if isinstance(lines, list) else []


def get_sold_product_quantities():
    """Return paid quantities grouped by product for the sold-items view."""
    paid_statuses = ("Pagado", "En preparación", "Enviado", "Completado")
    with closing(get_users_db()) as db:
        orders = db.execute(
            "SELECT status, lines_json FROM orders WHERE status IN (?, ?, ?, ?)",
            paid_statuses,
        ).fetchall()
    sold = {}
    for order in orders:
        for line in get_order_lines(order):
            try:
                product_id = int(line.get("product_id", 0))
                quantity = int(line.get("quantity", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            if product_id > 0 and quantity > 0:
                sold[product_id] = sold.get(product_id, 0) + quantity
    return sold


PRODUCT_SECTIONS = ["B\u00e9isbol", "Softball"]
PRODUCT_CATEGORIES = [
    "Bat", "Guantes", "Grip", "Guantaletas", "Accesorios de entrenamiento", "Protecci\u00f3n", "Pelotas"
]
BAT_MEASURES_BY_SECTION = {
    "B\u00e9isbol": ["32", "32.5", "33", "33.5", "34"],
    "Softball": ["34"],
}
BAT_WEIGHTS_BY_SECTION = {
    "B\u00e9isbol": ["-3"],
    "Softball": ["-6", "-7", "-8", "-9", "-10"],
}
GLOVE_MEASURES = ["11.25", "11.50", "11.75", "12", "12.25", "12.5", "12.75"]
GUANTALETA_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
GRIP_THICKNESSES = ["0.50mm", "1.1mm", "1.5mm", "1.8 mm"]


def get_product_sections(product):
    saved_sections = product.get("sections")
    if isinstance(saved_sections, list):
        normalized_sections = [repair_mojibake(section) for section in saved_sections]
        selected = [section for section in PRODUCT_SECTIONS if section in normalized_sections]
        if selected:
            return selected
    section = repair_mojibake(product.get("section"))
    return [section] if section in PRODUCT_SECTIONS else []


def infer_product_category(product):
    searchable = " ".join(
        str(product.get(field, "")) for field in ("name", "description", "tag")
    )
    searchable = "".join(
        char for char in unicodedata.normalize("NFKD", searchable.casefold())
        if not unicodedata.combining(char)
    )
    if "guantaleta" in searchable:
        return "Guantaletas"
    if "guante" in searchable:
        return "Guantes"
    if "grip" in searchable:
        return "Grip"
    if "bate" in searchable or "bat " in searchable:
        return "Bat"
    if "pelota" in searchable:
        return "Pelotas"
    if "casco" in searchable or "proteccion" in searchable:
        return "Protecci\u00f3n"
    return "Accesorios de entrenamiento"


products_migrated = False
for product in PRODUCTS:
    old_category = product.get("category", "")
    if product.get("section") not in PRODUCT_SECTIONS:
        product["section"] = old_category if old_category in PRODUCT_SECTIONS else "B\u00e9isbol"
        products_migrated = True
    valid_sections = get_product_sections(product)
    if not valid_sections:
        valid_sections = [product["section"]]
    if product.get("sections") != valid_sections:
        product["sections"] = valid_sections
        products_migrated = True
    if product.get("section") not in valid_sections:
        product["section"] = valid_sections[0]
        products_migrated = True
    if product.get("category") not in PRODUCT_CATEGORIES:
        product["category"] = infer_product_category(product)
        products_migrated = True
    package_defaults = {
        "Bat": (1.2, 90, 10, 10),
        "Guantes": (0.5, 30, 20, 12),
        "Guantaletas": (0.3, 30, 20, 8),
        "Grip": (0.2, 20, 10, 8),
        "Protecci\u00f3n": (0.7, 35, 28, 22),
    }.get(product.get("category"), (0.5, 30, 20, 15))
    package_fields = (
        ("package_weight_kg", package_defaults[0]),
        ("package_length_cm", package_defaults[1]),
        ("package_width_cm", package_defaults[2]),
        ("package_height_cm", package_defaults[3]),
    )
    for field, default in package_fields:
        try:
            valid_value = math.isfinite(float(product.get(field))) and float(product.get(field)) > 0
        except (TypeError, ValueError):
            valid_value = False
        if not valid_value:
            product[field] = default
            products_migrated = True
if products_migrated or products_encoding_migrated or products_images_migrated or products_brand_migrated or products_bat_views_migrated:
    save_products()
if (products_stock_migrated or products_active_migrated) and not products_migrated:
    save_products()

PRODUCT_BY_ID = {product["id"]: product for product in PRODUCTS}


def get_users_db():
    connection = sqlite3.connect(USERS_DB)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            google_sub TEXT UNIQUE,
            phone TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            neighborhood TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            postal_code TEXT NOT NULL DEFAULT '',
            marketing_opt_in INTEGER NOT NULL DEFAULT 0,
            email_verified INTEGER NOT NULL DEFAULT 1,
            email_verification_token TEXT,
            email_verification_expires TEXT,
            marketing_unsubscribe_token TEXT,
            privacy_notice_version TEXT NOT NULL DEFAULT '',
            privacy_accepted_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
    if "google_sub" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
    if "reset_token" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
    if "reset_expires" not in user_columns:
        connection.execute("ALTER TABLE users ADD COLUMN reset_expires TEXT")
    for column, definition in {
        "phone": "TEXT NOT NULL DEFAULT ''",
        "address": "TEXT NOT NULL DEFAULT ''",
        "neighborhood": "TEXT NOT NULL DEFAULT ''",
        "city": "TEXT NOT NULL DEFAULT ''",
        "state": "TEXT NOT NULL DEFAULT ''",
        "postal_code": "TEXT NOT NULL DEFAULT ''",
        "marketing_opt_in": "INTEGER NOT NULL DEFAULT 0",
        "email_verified": "INTEGER NOT NULL DEFAULT 1",
        "email_verification_token": "TEXT",
        "email_verification_expires": "TEXT",
        "marketing_unsubscribe_token": "TEXT",
        "privacy_notice_version": "TEXT NOT NULL DEFAULT ''",
        "privacy_accepted_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in user_columns:
            connection.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_unique ON users(google_sub)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            neighborhood TEXT NOT NULL DEFAULT '',
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            postal_code TEXT NOT NULL,
            delivery_method TEXT NOT NULL DEFAULT 'envio',
            payment_method TEXT NOT NULL DEFAULT 'whatsapp',
            stripe_session_id TEXT NOT NULL DEFAULT '',
            lines_json TEXT NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pendiente',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )"""
    )
    order_columns = {row["name"] for row in connection.execute("PRAGMA table_info(orders)")}
    for column, definition in {
        "customer_email": "TEXT NOT NULL DEFAULT ''",
        "phone": "TEXT NOT NULL DEFAULT ''",
        "address": "TEXT NOT NULL DEFAULT ''",
        "neighborhood": "TEXT NOT NULL DEFAULT ''",
        "delivery_method": "TEXT NOT NULL DEFAULT 'envio'",
        "payment_method": "TEXT NOT NULL DEFAULT 'whatsapp'",
        "stripe_session_id": "TEXT NOT NULL DEFAULT ''",
        "stripe_payment_intent_id": "TEXT NOT NULL DEFAULT ''",
        "discount": "REAL NOT NULL DEFAULT 0",
        "coupon_code": "TEXT NOT NULL DEFAULT ''",
        "shipping_fee": "REAL NOT NULL DEFAULT 0",
        "shipping_carrier": "TEXT NOT NULL DEFAULT ''",
        "shipping_rate_id": "TEXT NOT NULL DEFAULT ''",
        "shipping_quote_id": "TEXT NOT NULL DEFAULT ''",
        "tracking_number": "TEXT NOT NULL DEFAULT ''",
        "shipping_note": "TEXT NOT NULL DEFAULT ''",
        "shipping_label_url": "TEXT NOT NULL DEFAULT ''",
        "shipping_label_urls": "TEXT NOT NULL DEFAULT '[]'",
        "skydropx_shipment_id": "TEXT NOT NULL DEFAULT ''",
        "skydropx_order_id": "TEXT NOT NULL DEFAULT ''",
        "auction_id": "INTEGER NOT NULL DEFAULT 0",
        "refunded_at": "TEXT NOT NULL DEFAULT ''",
        "stock_reserved_until": "TEXT NOT NULL DEFAULT ''",
        "stock_released": "INTEGER NOT NULL DEFAULT 0",
        "purchase_terms_version": "TEXT NOT NULL DEFAULT ''",
        "privacy_notice_version": "TEXT NOT NULL DEFAULT ''",
        "legal_accepted_at": "TEXT NOT NULL DEFAULT ''",
    }.items():
        if column not in order_columns:
            connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'percent',
            value REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            starts_at TEXT NOT NULL DEFAULT '',
            expires_at TEXT NOT NULL DEFAULT '',
            usage_limit INTEGER NOT NULL DEFAULT 0,
            used_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS product_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            user_id INTEGER,
            reviewer_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS product_reviews_product_idx ON product_reviews(product_id, approved, id DESC)"
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS admin_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            entity TEXT NOT NULL DEFAULT '',
            entity_id TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS auth_attempts (
            fingerprint TEXT PRIMARY KEY,
            attempts_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )"""
    )
    connection.commit()
    return connection


def log_admin_activity(action, entity="", entity_id="", detail=""):
    if not session.get("is_admin"):
        return
    try:
        with closing(get_users_db()) as db:
            db.execute(
                "INSERT INTO admin_activity (action, entity, entity_id, detail) VALUES (?, ?, ?, ?)",
                (str(action)[:100], str(entity)[:60], str(entity_id)[:40], str(detail)[:500]),
            )
            db.commit()
    except sqlite3.Error:
        return


def csv_download(filename, headers, rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    response = Response("\ufeff" + buffer.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def get_coupon(code):
    normalized = str(code or "").strip().upper()
    if not normalized:
        return None
    if normalized == "BIENVENIDO10":
        return {
            "code": normalized,
            "kind": "percent",
            "value": 10,
            "active": 1,
            "usage_limit": 0,
            "used_count": 0,
            "first_order_only": True,
        }
    with closing(get_users_db()) as db:
        row = db.execute("SELECT * FROM coupons WHERE code = ?", (normalized,)).fetchone()
    return dict(row) if row else None


def coupon_available_for_customer(coupon, email="", user_id=None):
    """Check customer-specific restrictions for coupons that are not generally reusable."""
    if not coupon or not coupon.get("first_order_only"):
        return True
    normalized_email = str(email or "").strip().lower()
    if not normalized_email and not user_id:
        return True
    with closing(get_users_db()) as db:
        previous_purchase = db.execute(
            """SELECT 1 FROM orders
               WHERE status IN ('Pagado', 'En preparación', 'Enviado', 'Completado', 'Reembolsado')
                 AND (lower(customer_email) = ? OR (? IS NOT NULL AND user_id = ?))
               LIMIT 1""",
            (normalized_email, user_id, user_id),
        ).fetchone()
    return previous_purchase is None


def coupon_status(coupon):
    if not coupon or not int(coupon.get("active", 0)):
        return False, "El cupón está desactivado."
    today = datetime.now().date()
    starts_at = str(coupon.get("starts_at", "")).strip()
    expires_at = str(coupon.get("expires_at", "")).strip()
    try:
        if starts_at and today < datetime.fromisoformat(starts_at).date():
            return False, "El cupón todavía no está disponible."
        if expires_at and today > datetime.fromisoformat(expires_at).date():
            return False, "El cupón ya venció."
    except ValueError:
        return False, "La vigencia del cupón no es válida."
    limit = int(coupon.get("usage_limit", 0) or 0)
    if limit and int(coupon.get("used_count", 0) or 0) >= limit:
        return False, "El cupón alcanzó su límite de usos."
    if str(coupon.get("kind", "percent")) not in {"percent", "fixed"} or float(coupon.get("value", 0)) <= 0:
        return False, "La configuración del cupón no es válida."
    return True, ""


def get_public_coupon_announcements():
    """Return all usable active coupons for the rotating storefront announcement."""
    with closing(get_users_db()) as db:
        coupons = db.execute(
            "SELECT * FROM coupons WHERE active = 1 ORDER BY id DESC LIMIT 20"
        ).fetchall()
    valid_coupons = []
    for row in coupons:
        coupon = dict(row)
        valid, _ = coupon_status(coupon)
        if valid:
            valid_coupons.append(coupon)
    return valid_coupons


def calculate_coupon_discount(coupon, subtotal):
    valid, _ = coupon_status(coupon)
    if not valid:
        return 0
    value = max(float(coupon.get("value", 0)), 0)
    if coupon.get("kind") == "fixed":
        return min(round(value, 2), max(float(subtotal), 0))
    return min(round(float(subtotal) * min(value, 100) / 100, 2), max(float(subtotal), 0))


def parse_color_list(raw_value, fallback):
    values = []
    for value in str(raw_value or "").split(","):
        cleaned = value.strip()[:30]
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values or list(fallback)


def parse_package_dimensions(form):
    """Read and validate the package data used for shipping quotations."""
    field_names = ("peso_paquete", "largo_paquete", "ancho_paquete", "alto_paquete")
    try:
        values = {field: float(form.get(field, "")) for field in field_names}
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(value) or value <= 0 for value in values.values()):
        return None
    if values["peso_paquete"] > 1000 or any(values[field] > 500 for field in field_names[1:]):
        return None
    return {
        "package_weight_kg": round(values["peso_paquete"], 3),
        "package_length_cm": round(values["largo_paquete"], 2),
        "package_width_cm": round(values["ancho_paquete"], 2),
        "package_height_cm": round(values["alto_paquete"], 2),
    }


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped_view


def user_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash("Inicia sesión para continuar.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def get_product_reviews(product_id):
    with closing(get_users_db()) as db:
        rows = db.execute(
            "SELECT reviewer_name, rating, title, body, created_at FROM product_reviews "
            "WHERE product_id = ? AND approved = 1 ORDER BY id DESC LIMIT 30",
            (product_id,),
        ).fetchall()
    reviews = [dict(row) for row in rows]
    average = round(sum(int(review.get("rating", 0) or 0) for review in reviews) / len(reviews), 1) if reviews else 0
    return reviews, average


def cart_details():
    release_expired_stock_reservations()
    cart = session.get("cart", {})
    items = []
    total = 0
    for line_id, entry in cart.items():
        try:
            if isinstance(entry, dict):
                product_id = int(entry.get("product_id", 0))
                quantity = int(entry.get("quantity", 0))
                customizations = entry.get("customizations", {})
            else:
                product_id = int(line_id)
                quantity = int(entry)
                customizations = {}
        except (TypeError, ValueError):
            continue
        product = PRODUCT_BY_ID.get(product_id)
        if product and product.get("active", True) and quantity > 0:
            subtotal = product["price"] * quantity
            items.append({
                "product": product,
                "quantity": quantity,
                "subtotal": subtotal,
                "customizations": customizations if isinstance(customizations, dict) else {},
                "custom_image": entry.get("custom_image", "") if isinstance(entry, dict) else "",
                "line_id": line_id,
            })
            total += subtotal
    return items, total


def get_cart_count(cart=None):
    count = 0
    for entry in (cart if cart is not None else session.get("cart", {})).values():
        try:
            count += int(entry.get("quantity", 0)) if isinstance(entry, dict) else int(entry)
        except (TypeError, ValueError):
            continue
    return count


@app.context_processor
def inject_cart_count():
    whatsapp_local_number = WHATSAPP_NUMBER[-10:] if len(WHATSAPP_NUMBER) >= 10 else WHATSAPP_NUMBER
    whatsapp_display_number = (
        f"{whatsapp_local_number[:3]} {whatsapp_local_number[3:6]} {whatsapp_local_number[6:]}"
        if len(whatsapp_local_number) == 10 else whatsapp_local_number
    )
    return {
        "cart_count": get_cart_count(),
        "whatsapp_enabled": bool(WHATSAPP_NUMBER),
        "whatsapp_url": f"https://wa.me/{WHATSAPP_NUMBER}?text={quote('Hola, tengo una pregunta sobre FR BEISSHOP.')}",
        "whatsapp_display_number": whatsapp_display_number,
        "online_payment_enabled": bool(STRIPE_SECRET_KEY),
        "skydropx_enabled": skydropx_is_configured(),
        "shipping_provider": "Skydropx",
        "shop_email": SHOP_EMAIL,
        "public_coupons": get_public_coupon_announcements(),
        "active_auctions": get_active_auction_announcements(),
        "current_user": {
            "name": session.get("user_name"),
            "email": session.get("user_email"),
        } if session.get("user_id") else None,
    }


@app.template_filter("mxn")
def format_mxn(value):
    return f"${value:,.0f}"


@app.template_filter("order_datetime")
def format_order_datetime(value):
    """Show order timestamps in a compact, readable Spanish format."""
    raw = str(value or "").strip()
    if not raw:
        return "Fecha no disponible"
    parsed = None
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            continue
    if not parsed:
        return raw
    months = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    )
    return f"{parsed.day} de {months[parsed.month - 1]} de {parsed.year} · {parsed:%H:%M}"


@app.template_filter("section_label")
def section_label(value):
    """Presenta las secciones deportivas con su nombre en español."""
    return {"Softball": "Sóftbol"}.get(value, value)


def normalize_search_text(value):
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def is_mexicali_postal_code(postal_code):
    """Return whether a five-digit postal code belongs to Mexicali's ranges."""
    value = str(postal_code or "").strip()
    if not re.fullmatch(r"\d{5}", value):
        return False
    number = int(value)
    # Se excluye el bloque 21400–21573, correspondiente a Tecate.
    return 21000 <= number <= 21399 or 21600 <= number <= 21980


@app.get("/")
def index():
    return render_storefront()


@app.get("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin",
        "Disallow: /login",
        "Disallow: /registro",
        "Disallow: /checkout",
        f"Sitemap: {url_for('sitemap_xml', _external=True)}",
    ]
    response = make_response("\n".join(lines) + "\n")
    response.mimetype = "text/plain"
    return response


@app.get("/sitemap.xml")
def sitemap_xml():
    static_urls = [
        url_for("index", _external=True),
        url_for("our_brand", _external=True),
        url_for("store_help", _external=True),
        url_for("about_page", _external=True),
        url_for("contact_page", _external=True),
        url_for("auction", _external=True),
        url_for("auction_rules", _external=True),
    ]
    product_urls = [
        url_for("product_detail", product_id=product.get("id"), _external=True)
        for product in PRODUCTS if product.get("active", True)
    ]
    urls = static_urls + product_urls
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml.extend(f"<url><loc>{escape(link)}</loc></url>" for link in urls)
    xml.append("</urlset>")
    response = make_response("".join(xml))
    response.mimetype = "application/xml"
    return response


def public_homepage_settings():
    try:
        return load_homepage_settings(HOMEPAGE_FILE)
    except HomeContentError:
        app.logger.exception("No se pudo leer el contenido de inicio; se muestra el diseño inicial.")
        return default_homepage_settings()


def render_storefront(home_content=None, homepage_preview=False, homepage_editing=False):
    category = "Todos" if homepage_preview or homepage_editing else repair_mojibake(request.args.get("categoria", "Todos"))
    product_category = "Todos" if homepage_preview or homepage_editing else request.args.get("tipo", "Todos")
    if product_category not in ["Todos", *PRODUCT_CATEGORIES]:
        product_category = "Todos"
    sold_view = request.args.get("vista", "") == "vendidos" and category in {"B\u00e9isbol", "Softball"}
    sold_quantities = get_sold_product_quantities()
    search_query = "" if homepage_preview or homepage_editing else request.args.get("q", "").strip()[:100]
    filtered_products = [
        product for product in PRODUCTS
        if (product.get("active", True) or sold_view)
        and (not sold_view or sold_quantities.get(product.get("id"), 0) > 0)
    ]
    if category != "Todos":
        filtered_products = [
            product for product in filtered_products
            if category in get_product_sections(product)
        ]
    if category in {"B\u00e9isbol", "Softball"}:
        filtered_products = [
            product for product in filtered_products if product.get("admin_added") is True
        ]
    if product_category != "Todos":
        filtered_products = [
            product for product in filtered_products if product.get("category") == product_category
        ]
    if search_query:
        normalized_query = normalize_search_text(search_query)
        filtered_products = [
            product for product in filtered_products
            if normalized_query in normalize_search_text(" ".join(
                str(product.get(field, ""))
                for field in ("name", "category", "tag", "description")
            ) + " " + " ".join(get_product_sections(product)))
        ]
    products_for_template = []
    for product in filtered_products:
        product_view = dict(product)
        product_view["sold_quantity"] = sold_quantities.get(product.get("id"), 0)
        products_for_template.append(product_view)
    return render_template(
        "index.html",
        products=products_for_template,
        categories=["Todos", *PRODUCT_SECTIONS],
        product_categories=PRODUCT_CATEGORIES,
        active_category=category,
        active_product_category=product_category,
        sold_view=sold_view,
        sold_count=sum(1 for product in PRODUCTS if sold_quantities.get(product.get("id"), 0) > 0),
        search_query=search_query,
        home_content=home_content if home_content is not None else public_homepage_settings()["published"],
        homepage_preview=homepage_preview,
        homepage_editing=homepage_editing,
    )


@app.get("/ayuda")
def store_help():
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}" if WHATSAPP_NUMBER else ""
    return render_template("help.html", whatsapp_url=whatsapp_url)


@app.get("/nuestra-marca")
def our_brand():
    brand_products = [
        product for product in PRODUCTS
        if product.get("active", True) and product.get("brand_featured")
    ]
    return render_template("brand.html", brand_products=brand_products)


@app.get("/nosotros")
def about_page():
    return render_template("about.html")


@app.get("/contacto")
def contact_page():
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}" if WHATSAPP_NUMBER else ""
    return render_template(
        "contact.html", whatsapp_url=whatsapp_url, shop_email=SHOP_EMAIL,
        business_legal_name=BUSINESS_LEGAL_NAME, business_rfc=BUSINESS_RFC,
        business_physical_address=BUSINESS_PHYSICAL_ADDRESS,
    )


@app.get("/privacidad")
def privacy_page():
    return render_template(
        "legal.html", page_title="Aviso de privacidad", page_kind="privacy",
        business_legal_name=BUSINESS_LEGAL_NAME, business_rfc=BUSINESS_RFC,
        business_physical_address=BUSINESS_PHYSICAL_ADDRESS,
        privacy_contact_email=SHOP_EMAIL or "frbeisshop23@gmail.com",
        privacy_contact_phone=WHATSAPP_NUMBER,
    )


@app.get("/terminos")
def terms_page():
    return render_template(
        "legal.html", page_title="T&eacute;rminos de compra", page_kind="terms",
        business_legal_name=BUSINESS_LEGAL_NAME, business_rfc=BUSINESS_RFC,
        business_physical_address=BUSINESS_PHYSICAL_ADDRESS,
        privacy_contact_email=SHOP_EMAIL or "frbeisshop23@gmail.com",
        privacy_contact_phone=WHATSAPP_NUMBER,
    )


@app.get("/cambios-devoluciones")
def returns_page():
    return render_template(
        "legal.html", page_title="Cambios y devoluciones", page_kind="returns",
        business_legal_name=BUSINESS_LEGAL_NAME, business_rfc=BUSINESS_RFC,
        business_physical_address=BUSINESS_PHYSICAL_ADDRESS,
        privacy_contact_email=SHOP_EMAIL or "frbeisshop23@gmail.com",
        privacy_contact_phone=WHATSAPP_NUMBER,
    )


@app.get("/subasta")
def auction():
    finalize_closed_auctions()
    return render_template("auction.html", auctions=build_auction_cards())


@app.get("/reglas-subasta")
def auction_rules():
    return render_template("auction_rules.html")


def auction_checkout_context(auction_item, winner, existing_order=None):
    with closing(get_users_db()) as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (winner.get("user_id"),)).fetchone()
    profile = dict(user) if user else {}
    return {
        "auction": auction_item,
        "winner": winner,
        "profile": profile,
        "existing_order": existing_order,
        "shipping_estimate": SHIPPING_ESTIMATE,
        "shipping_enabled": skydropx_is_configured(),
    }


@app.route("/subasta/<int:auction_id>/pago", methods=["GET", "POST"])
def auction_checkout(auction_id):
    """Secure winner-only checkout for a closed auction."""
    finalize_closed_auctions()
    token = request.args.get("token", "").strip()
    auction_item = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
    winner = auction_current_offer(auction_item) if auction_item else None
    if not auction_item or not winner or not auction_is_closed(auction_item):
        abort(404)
    expires = parse_local_datetime(auction_item.get("winner_checkout_expires_at"))
    if (not token or not secrets.compare_digest(token, str(auction_item.get("winner_checkout_token", "")))
            or (expires and datetime.now() > expires)):
        abort(404)
    existing_order = None
    existing_payment_url = ""
    try:
        existing_order_id = int(auction_item.get("winner_order_id", 0) or 0)
    except (TypeError, ValueError):
        existing_order_id = 0
    if existing_order_id:
        with closing(get_users_db()) as db:
            row = db.execute("SELECT * FROM orders WHERE id = ?", (existing_order_id,)).fetchone()
        existing_order = dict(row) if row else None
        if existing_order and existing_order.get("stripe_session_id") and existing_order.get("status") == "Pago pendiente":
            try:
                import stripe
                stripe.api_key = STRIPE_SECRET_KEY
                existing_payment_url = stripe.checkout.Session.retrieve(existing_order["stripe_session_id"]).get("url", "")
            except Exception:
                existing_payment_url = ""
        if existing_order and request.method == "GET":
            context = auction_checkout_context(auction_item, winner, existing_order)
            context["existing_payment_url"] = existing_payment_url
            return render_template("auction_checkout.html", **context)

    if request.method == "POST":
        if existing_order:
            flash("Ya existe un pedido para esta subasta.", "error")
            return redirect(url_for("auction_checkout", auction_id=auction_id, token=token))
        if request.form.get("legal_accepted") != "1":
            flash("Debes aceptar los términos y el aviso de privacidad para continuar.", "error")
            return render_template("auction_checkout.html", **auction_checkout_context(auction_item, winner))
        if not STRIPE_SECRET_KEY:
            flash("El pago con Stripe todavía no está configurado.", "error")
            return render_template("auction_checkout.html", **auction_checkout_context(auction_item, winner))
        name = request.form.get("nombre", "").strip()[:100]
        customer_email = request.form.get("correo", "").strip().lower()[:180]
        phone = request.form.get("telefono", "").strip()[:20]
        address = request.form.get("direccion", "").strip()[:180]
        neighborhood = request.form.get("colonia", "").strip()[:100]
        city = request.form.get("ciudad", "").strip()[:80]
        state = request.form.get("estado", "").strip()[:80]
        postal_code = request.form.get("codigo_postal", "").strip()[:5]
        delivery_method = request.form.get("metodo_entrega", "envio").strip().lower()
        if delivery_method not in {"envio", "local"}:
            delivery_method = "envio"
        is_mexicali = "mexicali" in normalize_search_text(city)
        if delivery_method == "local" and not is_mexicali:
            flash("La entrega personal solo está disponible en Mexicali.", "error")
        elif (not all((name, customer_email, phone, address, neighborhood, city, state, postal_code))
                or not is_valid_email(customer_email) or not re.fullmatch(r"[0-9]{5}", postal_code)):
            flash("Completa todos tus datos de entrega con un correo y código postal válidos.", "error")
        else:
            try:
                winning_amount = round(float(winner.get("amount", 0)), 2)
            except (TypeError, ValueError):
                winning_amount = 0
            auction_product = {
                "name": auction_item.get("name", "Artículo de subasta"),
                "price": winning_amount,
                "description": auction_item.get("description", ""),
                "package_weight_kg": auction_item.get("package_weight_kg", 0.5),
                "package_length_cm": auction_item.get("package_length_cm", 30),
                "package_width_cm": auction_item.get("package_width_cm", 20),
                "package_height_cm": auction_item.get("package_height_cm", 15),
            }
            destination = {
                "address": address, "neighborhood": neighborhood, "city": city,
                "state": state, "postal_code": postal_code,
            }
            selected_rate = None
            selected_quote_id = ""
            if delivery_method == "local":
                shipping_fee, shipping_carrier = 0, "Entrega personal"
                shipping_note = "Entrega personal el mismo día en Mexicali"
            elif skydropx_is_configured():
                try:
                    quotation = skydropx_quote([{"product": auction_product, "quantity": 1}], destination)
                    selected_quote_id = quotation["quotation_id"]
                    selected_rate = min(quotation["rates"], key=lambda rate: float(rate.get("price", 0) or 0))
                    shipping_fee = max(float(selected_rate.get("price", 0) or 0), 0)
                    shipping_carrier = str(selected_rate.get("carrier") or "Skydropx")[:100]
                    shipping_note = str(selected_rate.get("service") or "Tarifa cotizada con Skydropx")[:240]
                except RuntimeError as error:
                    flash(f"No se pudo cotizar el envío: {error}", "error")
                    return render_template("auction_checkout.html", **auction_checkout_context(auction_item, winner))
            else:
                shipping_fee, shipping_carrier = SHIPPING_ESTIMATE, "Skydropx"
                shipping_note = "Envío estimado; configura Skydropx para generar la guía automáticamente"
            order_total = winning_amount + shipping_fee
            order_line = {
                "product_id": 0,
                "auction_id": auction_id,
                "name": auction_product["name"],
                "quantity": 1,
                "unit_price": winning_amount,
                "subtotal": winning_amount,
                "description": auction_product["description"],
                "customizations": {"Subasta": f"#{auction_id}"},
                "sku": f"SUBASTA-{auction_id}",
            }
            reservation_expires = expires.isoformat(timespec="minutes")
            with AUCTIONS_LOCK, closing(get_users_db()) as db:
                current = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
                current_deadline = parse_local_datetime(current.get("winner_checkout_expires_at")) if current else None
                current_winner = auction_current_offer(current) if current else None
                if (not current or not current_winner or current.get("winner_order_id")
                        or current.get("winner_checkout_token") != token
                        or not current_deadline or datetime.now() >= current_deadline
                        or current_winner.get("user_id") != winner.get("user_id")):
                    flash("Esta subasta ya tiene un pedido generado.", "error")
                    return redirect(url_for("auction_checkout", auction_id=auction_id, token=token))
                reservation_expires = current_deadline.isoformat(timespec="minutes")
                cursor = db.execute(
                    """INSERT INTO orders
                       (user_id, customer_name, customer_email, phone, address, neighborhood, city, state,
                        postal_code, delivery_method, payment_method, lines_json, total, status,
                        shipping_fee, shipping_carrier, shipping_rate_id, shipping_quote_id, shipping_note,
                        auction_id, stock_reserved_until, stock_released)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        winner.get("user_id"), name, customer_email, phone, address, neighborhood, city, state,
                        postal_code, delivery_method, "stripe", json.dumps([order_line], ensure_ascii=False),
                        order_total, "Pago pendiente", shipping_fee, shipping_carrier,
                        selected_rate.get("id", "") if selected_rate else "", selected_quote_id, shipping_note,
                        auction_id, reservation_expires, 0,
                    ),
                )
                order_id = cursor.lastrowid
                db.execute(
                    "UPDATE orders SET purchase_terms_version = ?, privacy_notice_version = ?, legal_accepted_at = ? WHERE id = ?",
                    (PURCHASE_TERMS_VERSION, PRIVACY_NOTICE_VERSION,
                     datetime.now().isoformat(timespec="seconds"), order_id),
                )
                current["winner_order_id"] = order_id
                save_auctions()
                db.commit()
            try:
                stripe_session = create_stripe_checkout_session(
                    order_id, customer_email, [order_line], winning_amount, shipping_fee,
                    0, selected_rate.get("id", "") if selected_rate else "", selected_quote_id,
                    min(datetime.now() + timedelta(hours=24), current_deadline).timestamp(),
                )
            except Exception as error:
                with AUCTIONS_LOCK, closing(get_users_db()) as db:
                    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
                    db.commit()
                    current = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
                    if current and int(current.get("winner_order_id", 0) or 0) == order_id:
                        current.pop("winner_order_id", None)
                        save_auctions()
                flash(str(error), "error")
                return render_template("auction_checkout.html", **auction_checkout_context(auction_item, winner))
            with closing(get_users_db()) as db:
                db.execute("UPDATE orders SET stripe_session_id = ? WHERE id = ?", (stripe_session.get("id", ""), order_id))
                db.commit()
            return redirect(stripe_session.url)
    context = auction_checkout_context(auction_item, winner, existing_order)
    context["existing_payment_url"] = existing_payment_url
    return render_template("auction_checkout.html", **context)


@app.post("/subasta/<int:auction_id>/pujar")
@user_required
def place_bid(auction_id):
    if request.form.get("legal_accepted") != "1":
        flash("Acepta las reglas de subasta y el aviso de privacidad antes de pujar.", "error")
        return redirect(url_for("auction"))
    try:
        amount = round(float(request.form.get("puja", "")), 2)
    except (TypeError, ValueError):
        amount = 0
    if not math.isfinite(amount) or amount <= 0:
        flash("Escribe una cantidad válida para tu puja.", "error")
        return redirect(url_for("auction"))
    with AUCTIONS_LOCK:
        auction_item = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
        if not auction_item:
            flash("No encontramos esa subasta.", "error")
            return redirect(url_for("auction"))
        if auction_is_closed(auction_item):
            flash("Esta subasta ya terminó.", "error")
            return redirect(url_for("auction"))
        minimum_bid = auction_minimum_bid(auction_item)
        if amount < minimum_bid:
            flash(f"La puja mínima es de {format_mxn(minimum_bid)} MXN.", "error")
            return redirect(url_for("auction"))
        previous_bid = next(
            (bid for bid in reversed(auction_item.get("bids", [])) if bid.get("user_id") == session.get("user_id")),
            None,
        )
        if previous_bid and round(float(previous_bid.get("amount", 0)), 2) == amount:
            flash("Ya registramos una puja igual. Aumenta la cantidad para volver a pujar.", "error")
            return redirect(url_for("auction"))
        auction_item.setdefault("bids", []).append({
            "amount": amount,
            "user_id": session.get("user_id"),
            "user_name": session.get("user_name") or session.get("user_email", "Usuario"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rules_version": PURCHASE_TERMS_VERSION,
            "privacy_notice_version": PRIVACY_NOTICE_VERSION,
            "legal_accepted_at": datetime.now().isoformat(timespec="seconds"),
        })
        save_auctions()
    flash("Tu puja fue registrada.", "success")
    return redirect(url_for("auction"))


@app.route("/registro", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        registration_identifier = f"register:{request.remote_addr or 'unknown'}"
        if auth_is_rate_limited(registration_identifier):
            flash("Demasiados intentos de registro. Espera unos minutos e inténtalo de nuevo.", "error")
            return render_template("auth.html", mode="register", google_client_id=GOOGLE_CLIENT_ID)
        name = request.form.get("nombre", "").strip()
        email = request.form.get("correo", "").strip().lower()
        phone = request.form.get("telefono", "").strip()[:20]
        password = request.form.get("password", "")
        password_confirmation = request.form.get("password_confirmacion", "")
        marketing_opt_in = 1 if request.form.get("marketing_opt_in") == "1" else 0
        if not name or not is_valid_email(email) or len(password) < 8:
            record_auth_failure(registration_identifier)
            flash("Completa tu nombre y correo. La contraseña debe tener al menos 8 caracteres.", "error")
        elif password != password_confirmation:
            record_auth_failure(registration_identifier)
            flash("Las contraseñas no coinciden.", "error")
        elif phone and not re.fullmatch(r"[0-9 +()\-]{10,20}", phone):
            record_auth_failure(registration_identifier)
            flash("Escribe un teléfono válido o déjalo vacío.", "error")
        elif request.form.get("privacy_accepted") != "1":
            record_auth_failure(registration_identifier)
            flash("Lee y acepta el aviso de privacidad para crear tu cuenta.", "error")
        else:
            verification_token = secrets.token_urlsafe(32)
            verification_expires = (datetime.now() + timedelta(hours=24)).isoformat(timespec="minutes")
            unsubscribe_token = secrets.token_urlsafe(32)
            try:
                with closing(get_users_db()) as db:
                    cursor = db.execute(
                        "INSERT INTO users (name, email, password_hash, phone, marketing_opt_in, email_verified, email_verification_token, email_verification_expires, marketing_unsubscribe_token, privacy_notice_version, privacy_accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (name, email, generate_password_hash(password), phone, marketing_opt_in, 0,
                         verification_token, verification_expires, unsubscribe_token,
                         PRIVACY_NOTICE_VERSION, datetime.now().isoformat(timespec="seconds")),
                    )
                    user_id = cursor.lastrowid
                    db.commit()
            except sqlite3.IntegrityError:
                record_auth_failure(registration_identifier)
                flash("Ya existe una cuenta con ese correo. Inicia sesión.", "error")
            else:
                clear_auth_failures(registration_identifier)
                session["user_id"] = user_id
                session["user_name"] = name
                session["user_email"] = email
                verify_url = url_for("verify_email", token=verification_token, _external=True)
                unsubscribe_url = url_for("unsubscribe_marketing", token=unsubscribe_token, _external=True)
                verification_sent = send_email_verification_email(email, name, verify_url)
                send_welcome_email(email, name, unsubscribe_url)
                if verification_sent:
                    flash("Tu cuenta está lista. Revisa tu correo para confirmar la dirección.", "success")
                else:
                    flash("Tu cuenta está lista, pero no pudimos enviar la confirmación. Puedes solicitarla desde tu perfil.", "error")
                return redirect(url_for("account"))
    return render_template("auth.html", mode="register", google_client_id=GOOGLE_CLIENT_ID)


@app.get("/verificar-correo/<token>")
def verify_email(token):
    now = datetime.now().isoformat(timespec="minutes")
    with closing(get_users_db()) as db:
        user = db.execute(
            "SELECT id FROM users WHERE email_verification_token = ? "
            "AND email_verification_expires > ? AND email_verified = 0",
            (token, now),
        ).fetchone()
        if not user:
            flash("El enlace de confirmación no es válido o ya caducó.", "error")
            return redirect(url_for("login"))
        db.execute(
            "UPDATE users SET email_verified = 1, email_verification_token = NULL, "
            "email_verification_expires = NULL WHERE id = ?",
            (user["id"],),
        )
        db.commit()
    flash("Correo confirmado correctamente.", "success")
    return redirect(url_for("account") if session.get("user_id") == user["id"] else url_for("login"))


@app.post("/cuenta/verificar-correo")
@user_required
def resend_email_verification():
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=24)).isoformat(timespec="minutes")
    with closing(get_users_db()) as db:
        user = db.execute("SELECT id, name, email, email_verified FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not user:
            flash("No encontramos tu cuenta.", "error")
            return redirect(url_for("login"))
        if user["email_verified"]:
            flash("Tu correo ya está confirmado.", "success")
            return redirect(url_for("account"))
        db.execute(
            "UPDATE users SET email_verification_token = ?, email_verification_expires = ? WHERE id = ?",
            (token, expires, user["id"]),
        )
        db.commit()
    verify_url = url_for("verify_email", token=token, _external=True)
    if send_email_verification_email(user["email"], user["name"], verify_url):
        flash("Te enviamos un nuevo enlace de confirmación.", "success")
    else:
        flash("No pudimos enviar el correo. Revisa la configuración SMTP.", "error")
    return redirect(url_for("account"))


@app.get("/promociones/cancelar/<token>")
def unsubscribe_marketing(token):
    with closing(get_users_db()) as db:
        user = db.execute(
            "SELECT id FROM users WHERE marketing_unsubscribe_token = ?", (token,)
        ).fetchone()
        if not user:
            flash("El enlace de preferencias no es válido.", "error")
            return redirect(url_for("index"))
        db.execute("UPDATE users SET marketing_opt_in = 0 WHERE id = ?", (user["id"],))
        db.commit()
    flash("Listo: ya no recibirás promociones por correo.", "success")
    return redirect(url_for("index"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    next_url = request.args.get("next", "")
    safe_next_url = next_url if next_url.startswith("/") and not next_url.startswith("//") else ""

    if request.method == "POST":
        identifier = request.form.get("correo", "").strip()
        password = request.form.get("password", "")
        if auth_is_rate_limited(identifier):
            flash("Demasiados intentos. Espera unos minutos e inténtalo de nuevo.", "error")
            return render_template("auth.html", mode="login", google_client_id=GOOGLE_CLIENT_ID)
        if (ADMIN_USERNAME and identifier.casefold() == ADMIN_USERNAME.casefold()
                and is_admin_password_valid(password)):
            clear_auth_failures(identifier)
            session["is_admin"] = True
            return redirect(url_for("admin_menu"))
        if not is_valid_email(identifier):
            flash("Escribe un correo válido o usa el acceso de administrador.", "error")
            return render_template("auth.html", mode="login", google_client_id=GOOGLE_CLIENT_ID)
        email = identifier.lower()
        with closing(get_users_db()) as db:
            user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            clear_auth_failures(identifier)
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            flash(f"Hola, {user['name']}.", "success")
            return redirect(safe_next_url or url_for("index"))
        record_auth_failure(identifier)
        flash("El correo o la contraseña no son correctos.", "error")
    return render_template("auth.html", mode="login", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/recuperar", methods=["GET", "POST"])
def password_recovery():
    reset_url = ""
    email_sent = False
    email_delivery_failed = False
    if request.method == "POST":
        email = request.form.get("correo", "").strip().lower()
        if not is_valid_email(email):
            flash("Escribe un correo válido.", "error")
        else:
            with closing(get_users_db()) as db:
                user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if user:
                    token = secrets.token_urlsafe(32)
                    expires = (datetime.now() + timedelta(minutes=30)).isoformat(timespec="minutes")
                    db.execute(
                        "UPDATE users SET reset_token = ?, reset_expires = ? WHERE id = ?",
                        (token, expires, user["id"]),
                    )
                    db.commit()
                    reset_url = url_for("reset_password", token=token, _external=True)
                    if email_is_configured():
                        email_sent = send_password_reset_email(email, reset_url)
                        if email_sent:
                            reset_url = ""
                        else:
                            reset_url = ""
                            email_delivery_failed = True
            if email_delivery_failed:
                flash("No pudimos enviar el enlace de recuperaci\u00f3n. Revisa la configuraci\u00f3n de correo e int\u00e9ntalo de nuevo.", "error")
            elif email_sent:
                flash("Si el correo existe, recibir\u00e1s un enlace para restablecer tu contrase\u00f1a.", "success")
            elif not reset_url:
                flash("Si el correo existe, recibirás instrucciones para restablecer tu contraseña.", "success")
    return render_template(
        "password_recovery.html",
        reset_url=reset_url,
        email_enabled=email_is_configured(),
    )


@app.route("/restablecer/<token>", methods=["GET", "POST"])
def reset_password(token):
    with closing(get_users_db()) as db:
        user = db.execute(
            "SELECT id FROM users WHERE reset_token = ? AND reset_expires > ?",
            (token, datetime.now().isoformat(timespec="minutes")),
        ).fetchone()
    if not user:
        flash("El enlace de recuperación no es válido o ya expiró.", "error")
        return redirect(url_for("password_recovery"))
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmar_password", "")
        if len(password) < 8 or password != confirmation:
            flash("Las contraseñas deben coincidir y tener al menos 8 caracteres.", "error")
        else:
            with closing(get_users_db()) as db:
                db.execute(
                    "UPDATE users SET password_hash = ?, reset_token = NULL, reset_expires = NULL WHERE id = ?",
                    (generate_password_hash(password), user["id"]),
                )
                db.commit()
            flash("Contraseña actualizada. Ya puedes iniciar sesión.", "success")
            return redirect(url_for("login"))
    return render_template("password_reset.html", token=token)


@app.post("/auth/google")
def google_login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    failure_page = "login" if request.form.get("mode") == "login" else "register"
    if failure_page == "register" and request.form.get("privacy_accepted") != "1":
        flash("Lee y acepta el aviso de privacidad antes de crear tu cuenta con Google.", "error")
        return redirect(url_for("register"))
    if not GOOGLE_CLIENT_ID:
        flash("El inicio con Google todavía no está configurado en la tienda.", "error")
        return redirect(url_for(failure_page))

    credential = request.form.get("credential", "")
    if not credential:
        flash("No se recibió una credencial de Google válida. Inténtalo de nuevo.", "error")
        return redirect(url_for(failure_page))

    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        google_user = id_token.verify_oauth2_token(
            credential, GoogleRequest(), GOOGLE_CLIENT_ID
        )
    except ImportError:
        flash("Falta instalar la dependencia de inicio con Google.", "error")
        return redirect(url_for(failure_page))
    except Exception:
        flash("No pudimos validar tu cuenta de Google. Inténtalo de nuevo.", "error")
        return redirect(url_for(failure_page))

    google_sub = google_user.get("sub", "")
    email = google_user.get("email", "").strip().lower()
    name = google_user.get("name", "").strip()
    if not google_sub or not email or not google_user.get("email_verified"):
        flash("Google no confirmó una dirección de correo verificada.", "error")
        return redirect(url_for(failure_page))
    if not name:
        name = email.split("@", 1)[0]

    try:
        new_account = False
        with closing(get_users_db()) as db:
            user = db.execute(
                "SELECT * FROM users WHERE google_sub = ? OR email = ?",
                (google_sub, email),
            ).fetchone()
            if user and user["google_sub"] not in (None, google_sub):
                flash("Ese correo ya está asociado a otra cuenta de Google.", "error")
                return redirect(url_for(failure_page))
            if user:
                if user["google_sub"] is None:
                    db.execute(
                        "UPDATE users SET google_sub = ? WHERE id = ?",
                        (google_sub, user["id"]),
                    )
                user_id = user["id"]
                name = user["name"] or name
                if failure_page == "register":
                    db.execute(
                        "UPDATE users SET privacy_notice_version = ?, privacy_accepted_at = ? WHERE id = ?",
                        (PRIVACY_NOTICE_VERSION, datetime.now().isoformat(timespec="seconds"), user_id),
                    )
            else:
                unsubscribe_token = secrets.token_urlsafe(32)
                cursor = db.execute(
                    "INSERT INTO users (name, email, password_hash, google_sub, email_verified, marketing_unsubscribe_token, privacy_notice_version, privacy_accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, email, generate_password_hash(os.urandom(48).hex()), google_sub,
                     1, unsubscribe_token,
                     PRIVACY_NOTICE_VERSION if failure_page == "register" else "",
                     datetime.now().isoformat(timespec="seconds") if failure_page == "register" else ""),
                )
                user_id = cursor.lastrowid
                new_account = True
            db.commit()
    except sqlite3.IntegrityError:
        flash("No se pudo vincular esta cuenta de Google. Inténtalo de nuevo.", "error")
        return redirect(url_for(failure_page))

    session["user_id"] = user_id
    session["user_name"] = name
    session["user_email"] = email
    if new_account:
        unsubscribe_url = url_for("unsubscribe_marketing", token=unsubscribe_token, _external=True)
        send_welcome_email(email, name, unsubscribe_url)
    flash(f"Hola, {name}.", "success")
    return redirect(url_for("index"))


@app.get("/cuenta")
def account():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    with closing(get_users_db()) as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        rows = db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC",
            (session["user_id"],),
        ).fetchall()
    orders = []
    for row in rows:
        order = dict(row)
        order["lines"] = get_order_lines(row)
        orders.append(order)
    user_profile = dict(user) if user else {
        "name": session.get("user_name", ""),
        "email": session.get("user_email", ""),
        "google_sub": None,
        "phone": "",
        "address": "",
        "neighborhood": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "marketing_opt_in": 0,
        "email_verified": 1,
        "email_verification_token": None,
        "email_verification_expires": None,
        "marketing_unsubscribe_token": None,
        "created_at": "",
    }
    return render_template(
        "account.html",
        orders=orders,
        user_profile=user_profile,
        order_count=len(orders),
        total_spent=sum(float(order.get("total", 0) or 0) for order in orders),
    )


@app.get("/cuenta/datos")
@user_required
def account_data_export():
    with closing(get_users_db()) as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        rows = db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC",
            (session["user_id"],),
        ).fetchall()
    if not user:
        flash("No encontramos tu cuenta.", "error")
        return redirect(url_for("login"))
    user_data = {
        field: user[field]
        for field in (
            "id", "name", "email", "phone", "address", "neighborhood", "city", "state",
            "postal_code", "marketing_opt_in", "email_verified", "privacy_notice_version",
            "privacy_accepted_at", "created_at",
        )
        if field in user.keys()
    }
    orders = []
    for row in rows:
        order = dict(row)
        order["lines"] = get_order_lines(row)
        order.pop("lines_json", None)
        orders.append(order)
    payload = json.dumps(
        {"exported_at": datetime.now().isoformat(timespec="seconds"), "user": user_data, "orders": orders},
        ensure_ascii=False,
        indent=2,
    )
    filename = f"fr-beisshop-datos-{datetime.now():%Y-%m-%d}.json"
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/cuenta/eliminar")
@user_required
def delete_account():
    if request.form.get("confirmar", "").strip().upper() != "ELIMINAR":
        flash("Escribe ELIMINAR para confirmar el cierre de la cuenta.", "error")
        return redirect(url_for("account"))
    user_id = session["user_id"]
    with closing(get_users_db()) as db:
        db.execute("DELETE FROM orders WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM product_reviews WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_email", None)
    flash("Tu cuenta y sus datos personales fueron eliminados.", "success")
    return redirect(url_for("index"))


@app.post("/cuenta/perfil")
@user_required
def update_profile():
    name = request.form.get("nombre", "").strip()
    phone = request.form.get("telefono", "").strip()[:20]
    marketing_opt_in = 1 if request.form.get("marketing_opt_in") == "1" else 0
    address = request.form.get("direccion", "").strip()[:180]
    neighborhood = request.form.get("colonia", "").strip()[:100]
    city = request.form.get("ciudad", "").strip()[:80]
    state = request.form.get("estado", "").strip()[:80]
    postal_code = request.form.get("codigo_postal", "").strip()[:5]
    if (not name or len(name) > 100 or (phone and not re.fullmatch(r"[0-9 +()\-]{10,20}", phone))
            or (postal_code and not re.fullmatch(r"[0-9]{5}", postal_code))):
        flash("Revisa tu nombre, teléfono y código postal.", "error")
        return redirect(url_for("account"))
    with closing(get_users_db()) as db:
        db.execute(
            """UPDATE users SET name = ?, phone = ?, address = ?, neighborhood = ?,
               city = ?, state = ?, postal_code = ?, marketing_opt_in = ? WHERE id = ?""",
            (name, phone, address, neighborhood, city, state, postal_code, marketing_opt_in, session["user_id"]),
        )
        db.commit()
    session["user_name"] = name
    flash("Perfil actualizado.", "success")
    return redirect(url_for("account"))


@app.post("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_email", None)
    session.pop("is_admin", None)
    flash("Has cerrado sesión.", "success")
    return redirect(url_for("index"))


@app.get("/producto/<int:product_id>")
def product_detail(product_id):
    product = PRODUCT_BY_ID.get(product_id)
    if not product or not product.get("active", True):
        flash("No encontramos ese producto.", "error")
        return redirect(url_for("index"))
    product["views"] = product.get("views", 0) + 1
    save_products()
    reviews, review_average = get_product_reviews(product_id)
    return render_template(
        "product.html",
        product=product,
        bat_measures=BAT_MEASURES_BY_SECTION.get(
            product.get("section"), BAT_MEASURES_BY_SECTION.get("B\u00e9isbol", [])
        ),
        custom_grip_colors=product.get("custom_grip_colors") or ["Negro", "Rojo", "Azul", "Blanco"],
        reviews=reviews,
        review_average=review_average,
    )


@app.post("/producto/<int:product_id>/reseña")
@user_required
def create_product_review(product_id):
    product = PRODUCT_BY_ID.get(product_id)
    if not product or not product.get("active", True):
        flash("No encontramos ese producto.", "error")
        return redirect(url_for("index"))
    try:
        rating = int(request.form.get("calificacion", "0"))
    except (TypeError, ValueError):
        rating = 0
    title = request.form.get("titulo", "").strip()[:100]
    body = request.form.get("comentario", "").strip()[:1200]
    if rating not in range(1, 6) or len(body) < 10:
        flash("Elige una calificación y escribe un comentario de al menos 10 caracteres.", "error")
        return redirect(url_for("product_detail", product_id=product_id) + "#resenas")
    with closing(get_users_db()) as db:
        existing = db.execute(
            "SELECT id FROM product_reviews WHERE product_id = ? AND user_id = ? LIMIT 1",
            (product_id, session["user_id"]),
        ).fetchone()
        if existing:
            flash("Ya dejaste una reseña para este producto.", "error")
            return redirect(url_for("product_detail", product_id=product_id) + "#resenas")
        user = db.execute("SELECT name, email FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        reviewer_name = (user["name"] if user and user["name"] else user["email"].split("@", 1)[0] if user else "Cliente")[:80]
        db.execute(
            "INSERT INTO product_reviews (product_id, user_id, reviewer_name, rating, title, body) VALUES (?, ?, ?, ?, ?, ?)",
            (product_id, session["user_id"], reviewer_name, rating, title, body),
        )
        db.commit()
    flash("Gracias por compartir tu experiencia.", "success")
    return redirect(url_for("product_detail", product_id=product_id) + "#resenas")


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(url_for("admin_menu"))
    if request.method == "POST":
        username = request.form.get("usuario", request.form.get("username", "")).strip()
        if auth_is_rate_limited(username):
            flash("Demasiados intentos. Espera unos minutos e inténtalo de nuevo.", "error")
            return render_template("admin_login.html")
        if (ADMIN_USERNAME and username.casefold() == ADMIN_USERNAME.casefold()
                and is_admin_password_valid(request.form.get("password", ""))):
            clear_auth_failures(username)
            session["is_admin"] = True
            return redirect(url_for("admin_menu"))
        record_auth_failure(username)
        flash("El usuario o la contraseña no son correctos.", "error")
    return render_template("admin_login.html")


def homepage_submission(content):
    """Validate every reference and upload before saving the homepage draft."""
    hero_uploads = [upload for upload in request.files.getlist("hero_images") if upload.filename]
    if len(content["hero"]["images"]) + len(hero_uploads) > HOME_CONTENT_LIMITS["hero_images"]:
        raise HomeContentError("La portada admite hasta 5 fotos. Quita alguna antes de agregar otra.")
    try:
        new_alts = json.loads(request.form.get("new_hero_alts", "[]"))
        order = json.loads(request.form.get("hero_image_order", "[]"))
    except (ValueError, TypeError) as error:
        raise HomeContentError("No se pudo leer el orden de las fotos. Vuelve a seleccionarlas.") from error
    if not isinstance(new_alts, list) or len(new_alts) != len(hero_uploads):
        raise HomeContentError("Revisa las descripciones de las fotos nuevas.")
    if any(not isinstance(alt, str) or len(alt) > 180 or re.search(r"[\x00-\x1f\x7f]", alt) for alt in new_alts):
        raise HomeContentError("Cada descripción de foto admite hasta 180 caracteres.")
    existing = {f"existing:{photo['id']}": photo for photo in content["hero"]["images"]}
    expected = set(existing) | {f"new:{index}" for index in range(len(hero_uploads))}
    if not isinstance(order, list) or any(not isinstance(token, str) for token in order) or len(order) != len(expected) or set(order) != expected:
        raise HomeContentError("El orden de las fotos está incompleto. Revisa la portada antes de guardar.")

    section_uploads = []
    section_ids = {block["id"] for block in content["sections"]}
    announcement_uploads = []
    announcement_ids = {item["id"] for item in content["announcements"]}
    allowed_upload_fields = {"hero_images"}
    allowed_upload_fields.update(f"section_image_{block_id}" for block_id in section_ids)
    allowed_upload_fields.update(f"announcement_image_{announcement_id}" for announcement_id in announcement_ids)
    for field in request.files:
        if field not in allowed_upload_fields:
            raise HomeContentError("Una foto no corresponde a una sección del editor. Revisa los cambios.")
    for block in content["sections"]:
        uploads = [upload for upload in request.files.getlist(f"section_image_{block['id']}") if upload.filename]
        if len(uploads) > 1:
            raise HomeContentError("Cada bloque admite una foto.")
        if uploads:
            section_uploads.append((block, uploads[0]))
    for announcement in content["announcements"]:
        uploads = [upload for upload in request.files.getlist(f"announcement_image_{announcement['id']}") if upload.filename]
        if len(uploads) > 1:
            raise HomeContentError("Cada anuncio admite una foto.")
        if uploads:
            announcement_uploads.append((announcement, uploads[0]))

    references = [photo["url"] for photo in content["hero"]["images"]]
    references.extend(block["image_url"] for block in content["sections"] if block["image_url"])
    references.extend(item["image_url"] for item in content["announcements"] if item["image_url"])
    for reference in references:
        # normalize_home_content already limits these to UUID filenames in uploads.
        if not (UPLOAD_FOLDER / reference.rsplit("/", 1)[-1]).is_file():
            raise HomeContentError("Una foto guardada ya no está disponible. Quítala o vuelve a subirla.")

    section_offset = len(hero_uploads)
    announcement_offset = section_offset + len(section_uploads)
    uploaded_urls = save_product_images(hero_uploads + [upload for _, upload in section_uploads] + [upload for _, upload in announcement_uploads])
    for index, image_url in enumerate(uploaded_urls[:len(hero_uploads)]):
        existing[f"new:{index}"] = {"id": uuid4().hex, "url": image_url, "alt": new_alts[index].strip() or content["hero"]["title"]}
    content["hero"]["images"] = [existing[token] for token in order]
    for (block, _), image_url in zip(section_uploads, uploaded_urls[len(hero_uploads):]):
        block["image_url"] = image_url
    for (announcement, _), image_url in zip(announcement_uploads, uploaded_urls[announcement_offset:]):
        announcement["image_url"] = image_url
    return normalize_home_content(content)


@app.route("/admin/inicio", methods=["GET", "POST"])
@admin_required
def admin_homepage():
    errors = []
    status_code = 200
    try:
        settings = load_homepage_settings(HOMEPAGE_FILE)
    except HomeContentError as error:
        settings = default_homepage_settings()
        errors.append(str(error))
        status_code = 503
    content = copy.deepcopy(settings["draft"])
    if request.method == "POST" and not errors:
        try:
            action = request.form.get("accion", "")
            if action not in {"save_draft", "preview", "publish"}:
                raise HomeContentError("Elige guardar borrador, vista previa o publicar cambios.")
            content_json = request.form.get("content_json", "")
            if len(content_json) > 64000:
                raise HomeContentError("El contenido es demasiado largo. Revisa los textos del inicio.")
            try:
                parsed = json.loads(content_json)
            except (ValueError, TypeError) as error:
                raise HomeContentError("No se recibieron los cambios. Recarga el editor e inténtalo de nuevo.") from error
            content = normalize_home_content(parsed)
            content = homepage_submission(content)
            settings = save_homepage_settings(HOMEPAGE_FILE, content, publish=action == "publish")
            log_admin_activity("Inicio publicado" if action == "publish" else "Borrador de inicio guardado", "inicio", "principal")
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                response = jsonify(content=content, status={"updated_at": settings["updated_at"], "published_at": settings["published_at"]}, published=action == "publish")
                response.headers["Cache-Control"] = "no-store"
                return response
            if action == "preview":
                return redirect(url_for("admin_homepage_preview"))
            flash("La página de inicio ya muestra tus cambios." if action == "publish" else "Borrador guardado. Puedes revisarlo antes de publicarlo.", "success")
            return redirect(url_for("admin_homepage"))
        except ValueError as error:
            errors.append(str(error))
            status_code = 400
        except OSError:
            app.logger.exception("No se pudo guardar la página de inicio.")
            errors.append("No se pudo guardar el inicio. Tus cambios publicados se conservan; inténtalo de nuevo.")
            status_code = 503
    if request.method == "POST" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        response = jsonify(errors=errors)
        response.status_code = status_code
        response.headers["Cache-Control"] = "no-store"
        return response
    response = app.make_response((render_template(
        "admin_homepage.html", home_content=content, home_limits=HOME_CONTENT_LIMITS,
        home_status={"updated_at": settings["updated_at"], "published_at": settings["published_at"]},
        has_unpublished_changes=content != settings["published"], homepage_errors=errors,
    ), status_code))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/admin/inicio/vista-previa")
@admin_required
def admin_homepage_preview():
    try:
        settings = load_homepage_settings(HOMEPAGE_FILE)
    except HomeContentError as error:
        flash(str(error), "error")
        return redirect(url_for("admin_homepage"))
    response = app.make_response(render_storefront(settings["draft"], homepage_preview=True))
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.post("/admin/inicio/lienzo")
@admin_required
def admin_homepage_canvas():
    """Render unsaved visual edits without publishing or writing uploaded files."""
    try:
        if request.content_length and request.content_length > 96000:
            raise HomeContentError("El contenido es demasiado largo. Revisa los textos del inicio.")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise HomeContentError("No se recibieron los datos de la vista previa.")
        content = normalize_home_content(payload.get("content"))
        response = app.make_response(render_storefront(content, homepage_editing=True))
    except HomeContentError as error:
        response = jsonify(error=str(error))
        response.status_code = 400
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.get("/admin/menu")
@admin_required
def admin_menu():
    deleted_count = len(prune_deleted_products())
    disabled_count = sum(not product.get("active", True) for product in PRODUCTS)
    with closing(get_users_db()) as db:
        pending_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN ('Pendiente', 'Pago pendiente')"
        ).fetchone()[0]
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        recent_activity = db.execute(
            "SELECT action, entity, entity_id, detail, created_at FROM admin_activity ORDER BY id DESC LIMIT 8"
        ).fetchall()
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        month_prefix = datetime.now().strftime("%Y-%m")
        today_revenue = db.execute(
            "SELECT COALESCE(SUM(total), 0) FROM orders WHERE status NOT IN ('Cancelado', 'Reembolsado') AND created_at LIKE ?",
            (f"{today_prefix}%",),
        ).fetchone()[0]
        month_revenue = db.execute(
            "SELECT COALESCE(SUM(total), 0) FROM orders WHERE status NOT IN ('Cancelado', 'Reembolsado') AND created_at LIKE ?",
            (f"{month_prefix}%",),
        ).fetchone()[0]
        recent_rows = db.execute("SELECT id, customer_name, total, status, created_at FROM orders ORDER BY id DESC LIMIT 5").fetchall()
    low_stock = sorted(
        [product for product in PRODUCTS if int(product.get("stock", 0) or 0) <= LOW_STOCK_THRESHOLD],
        key=lambda product: int(product.get("stock", 0) or 0),
    )
    category_totals = {}
    with closing(get_users_db()) as db:
        sales_rows = db.execute("SELECT lines_json, status FROM orders WHERE status NOT IN ('Cancelado', 'Reembolsado')").fetchall()
    for row in sales_rows:
        for line in get_order_lines(row):
            product = PRODUCT_BY_ID.get(int(line.get("product_id", 0)))
            category = product.get("category", "Otros") if product else "Otros"
            category_totals[category] = category_totals.get(category, 0) + float(line.get("subtotal", 0) or 0)
    max_category_total = max(category_totals.values(), default=1)
    sales_by_category = [
        {"name": category, "total": total, "width": max(round(total / max_category_total * 100), 4)}
        for category, total in sorted(category_totals.items(), key=lambda pair: pair[1], reverse=True)
    ]
    return render_template(
        "admin_menu.html",
        total_products=len(PRODUCTS),
        baseball_products=sum("B\u00e9isbol" in get_product_sections(product) for product in PRODUCTS),
        softball_products=sum("Softball" in get_product_sections(product) for product in PRODUCTS),
        auction_count=len(AUCTIONS),
        pending_orders=pending_orders,
        user_count=user_count,
        today_revenue=today_revenue,
        month_revenue=month_revenue,
        low_stock=low_stock,
        recent_orders=recent_rows,
        sales_by_category=sales_by_category,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
        stripe_enabled=bool(STRIPE_SECRET_KEY),
        stripe_webhook_enabled=bool(STRIPE_WEBHOOK_SECRET),
        email_enabled=email_is_configured(),
        shipping_enabled=skydropx_is_configured(),
        production_mode=IS_PRODUCTION,
        deleted_count=deleted_count,
        disabled_count=disabled_count,
    )


@app.route("/admin/marca", methods=["GET", "POST"])
@admin_required
def admin_brand():
    if request.method == "POST":
        if request.form.get("accion") == "agregar":
            name = request.form.get("nombre", "").strip()
            description = request.form.get("descripcion", "").strip()
            try:
                price = float(request.form.get("precio", ""))
            except (TypeError, ValueError):
                price = 0
            image_upload_invalid = False
            try:
                images = save_product_images([request.files.get("imagen_archivo")])
            except ValueError as error:
                flash(str(error), "error")
                images = []
                image_upload_invalid = True
            if image_upload_invalid or not name or not description or price <= 0:
                flash("Completa la imagen, el nombre, el precio y la descripción del producto.", "error")
                return redirect(url_for("admin_brand"))
            product_id = max((int(product.get("id", 0)) for product in PRODUCTS), default=0) + 1
            fallback_image = url_for("static", filename="logo.png")
            product = {
                "id": product_id,
                "name": name,
                "category": "Accesorios de entrenamiento",
                "section": "Béisbol",
                "sections": ["Béisbol"],
                "price": price,
                "stock": 10,
                "package_weight_kg": 0.5,
                "package_length_cm": 30,
                "package_width_cm": 20,
                "package_height_cm": 15,
                "description": description,
                "tag": "Nuestra marca",
                "images": images or [fallback_image],
                "image": images[0] if images else fallback_image,
                "brand_featured": True,
                "views": 0,
                "admin_added": True,
                "active": True,
            }
            PRODUCTS.append(product)
            PRODUCT_BY_ID[product_id] = product
            save_products()
            log_admin_activity("Producto agregado a Nuestra marca", "producto", product_id, name)
            flash("Producto agregado a Nuestra marca.", "success")
            return redirect(url_for("admin_brand"))
        selected_ids = set()
        for value in request.form.getlist("productos"):
            try:
                selected_ids.add(int(value))
            except (TypeError, ValueError):
                continue
        for product in PRODUCTS:
            product["brand_featured"] = product.get("id") in selected_ids
        save_products()
        flash("Productos de Nuestra marca actualizados.", "success")
        return redirect(url_for("admin_brand"))
    return render_template("admin_brand.html", products=PRODUCTS)


@app.route("/admin/correo", methods=["GET", "POST"])
@admin_required
def admin_email_settings():
    """Configure transactional email from the protected admin panel."""
    refresh_email_config()
    if request.method == "POST":
        action = request.form.get("accion")
        if action == "welcome":
            recipient = request.form.get("welcome_email", "").strip().lower()
            name = request.form.get("welcome_name", "").strip()[:120]
            if not is_valid_email(recipient):
                flash("Escribe una dirección de correo válida.", "error")
            elif send_welcome_email(recipient, name):
                flash("Correo de bienvenida enviado correctamente.", "success")
            else:
                flash("No se pudo enviar el correo de bienvenida. Revisa que el correo esté activado y la configuración SMTP guardada.", "error")
            return redirect(url_for("admin_email_settings"))
        if action in {"verification_test", "recovery_test"}:
            recipient = request.form.get("flow_email", "").strip().lower()
            if not is_valid_email(recipient):
                flash("Escribe una dirección de correo válida.", "error")
            elif action == "verification_test":
                verify_url = url_for("verify_email", token=secrets.token_urlsafe(24), _external=True)
                if send_email_verification_email(recipient, "deportista", verify_url):
                    flash("Prueba de confirmación enviada correctamente.", "success")
                else:
                    flash("No se pudo enviar la prueba de confirmación. Revisa la configuración SMTP.", "error")
            else:
                reset_url = url_for("reset_password", token=secrets.token_urlsafe(24), _external=True)
                if send_password_reset_email(recipient, reset_url):
                    flash("Prueba de recuperación enviada correctamente.", "success")
                else:
                    flash("No se pudo enviar la prueba de recuperación. Revisa la configuración SMTP.", "error")
            return redirect(url_for("admin_email_settings"))
        if action == "test":
            recipient = request.form.get("test_email", "").strip().lower()
            if send_test_email(recipient):
                flash("Correo de prueba enviado correctamente.", "success")
            elif SMTP_HOST.lower() == "smtp.gmail.com":
                flash("No se pudo enviar. Verifica que uses una contraseña de aplicación de Google de 16 caracteres y que la verificación en 2 pasos esté activada.", "error")
            else:
                flash("No se pudo enviar el correo de prueba. Revisa el servidor SMTP y el destinatario.", "error")
            return redirect(url_for("admin_email_settings"))
        host = request.form.get("smtp_host", "").strip()[:180]
        user = request.form.get("smtp_user", "").strip()[:180]
        sender = request.form.get("smtp_from", "").strip()[:180]
        reply_to = request.form.get("email_reply_to", "").strip()[:180]
        shop_email = request.form.get("shop_email", "").strip()[:180]
        password = request.form.get("smtp_password", "")
        if host.lower() == "smtp.gmail.com":
            password = "".join(password.split())
        try:
            port = int(request.form.get("smtp_port", "587"))
        except (TypeError, ValueError):
            port = 587
        if port < 1 or port > 65535:
            flash("El puerto SMTP no es válido.", "error")
            return redirect(url_for("admin_email_settings"))
        saved_password = SMTP_PASSWORD if not password else password
        config = {
            "smtp_host": host,
            "smtp_port": port,
            "smtp_user": user,
            "smtp_password": saved_password,
            "smtp_from": sender,
            "email_reply_to": reply_to,
            "shop_email": shop_email,
            "email_notifications": request.form.get("email_notifications") == "1",
        }
        try:
            EMAIL_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            refresh_email_config()
        except OSError:
            flash("No pudimos guardar la configuración de correo.", "error")
            return redirect(url_for("admin_email_settings"))
        flash("Configuración de correo guardada.", "success")
        return redirect(url_for("admin_email_settings"))
    return render_template(
        "admin_email.html",
        email_enabled=email_is_configured(),
        smtp_host=SMTP_HOST,
        smtp_port=SMTP_PORT,
        smtp_user=SMTP_USER,
        smtp_from=SMTP_FROM,
        email_reply_to=EMAIL_REPLY_TO,
        shop_email=SHOP_EMAIL,
    )


@app.route("/admin/google", methods=["GET", "POST"])
@admin_required
def admin_google_settings():
    """Configure the Google Identity Services client used by login and signup."""
    global GOOGLE_CLIENT_ID
    if request.method == "POST":
        client_id = request.form.get("client_id", "").strip()[:300]
        if client_id and not re.fullmatch(r"[0-9A-Za-z._-]+\.apps\.googleusercontent\.com", client_id):
            flash("El Client ID de Google no tiene un formato válido.", "error")
            return redirect(url_for("admin_google_settings"))
        try:
            GOOGLE_CONFIG_FILE.write_text(
                json.dumps({"client_id": client_id}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            GOOGLE_CLIENT_ID = client_id
        except OSError:
            flash("No pudimos guardar la configuración de Google.", "error")
            return redirect(url_for("admin_google_settings"))
        flash("Configuración de Google guardada." if client_id else "Inicio con Google desactivado.", "success")
        return redirect(url_for("admin_google_settings"))
    return render_template("admin_google.html", google_client_id=GOOGLE_CLIENT_ID)


@app.route("/admin/envios", methods=["GET", "POST"])
@admin_required
def admin_shipping_settings():
    """Configure the Skydropx quote integration from the protected admin panel."""
    refresh_shipping_config()
    if request.method == "POST":
        if request.form.get("accion") == "test":
            try:
                skydropx_access_token()
            except Exception as error:
                flash(f"No se pudo conectar con Skydropx: {error}", "error")
            else:
                flash("Conexión con Skydropx comprobada.", "success")
            return redirect(url_for("admin_shipping_settings"))

        api_base = request.form.get("api_base", "").strip().rstrip("/")
        client_id = request.form.get("client_id", "").strip()[:240]
        client_secret = request.form.get("client_secret", "")
        country = request.form.get("country", "MX").strip().upper()[:2] or "MX"
        postal_code = request.form.get("postal_code", "").strip()[:10]
        origin_state = request.form.get("origin_state", "").strip()[:120]
        origin_city = request.form.get("origin_city", "").strip()[:120]
        origin_neighborhood = request.form.get("origin_neighborhood", "").strip()[:120]
        origin_address = request.form.get("origin_address", "").strip()[:180]
        origin_phone = request.form.get("origin_phone", "").strip()[:20]
        carriers = request.form.get("carriers", "").strip()[:240]
        if not api_base.startswith(("http://", "https://")):
            flash("La dirección de la API de Skydropx no es válida.", "error")
            return redirect(url_for("admin_shipping_settings"))
        if postal_code and not re.fullmatch(r"[0-9]{5}", postal_code):
            flash("El código postal de origen debe tener 5 números.", "error")
            return redirect(url_for("admin_shipping_settings"))
        saved_secret = SKYDROPX_CLIENT_SECRET if not client_secret else client_secret
        config = {
            "skydropx_api_base": api_base or "https://api-pro.skydropx.com",
            "skydropx_client_id": client_id,
            "skydropx_client_secret": saved_secret,
            "skydropx_origin_country": country,
            "skydropx_origin_postal_code": postal_code,
            "skydropx_origin_state": origin_state,
            "skydropx_origin_city": origin_city,
            "skydropx_origin_neighborhood": origin_neighborhood,
            "skydropx_origin_address": origin_address,
            "skydropx_origin_phone": origin_phone,
            "skydropx_requested_carriers": carriers,
        }
        try:
            SHIPPING_CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            refresh_shipping_config()
        except OSError:
            flash("No pudimos guardar la configuración de Skydropx.", "error")
            return redirect(url_for("admin_shipping_settings"))
        flash("Configuración de Skydropx guardada.", "success")
        return redirect(url_for("admin_shipping_settings"))
    return render_template(
        "admin_shipping.html",
        shipping_enabled=skydropx_is_configured(),
        api_base=SKYDROPX_API_BASE,
        client_id=SKYDROPX_CLIENT_ID,
        country=SKYDROPX_ORIGIN.get("country_code", "MX"),
        postal_code=SKYDROPX_ORIGIN.get("postal_code", ""),
        origin_state=SKYDROPX_ORIGIN.get("area_level1", ""),
        origin_city=SKYDROPX_ORIGIN.get("area_level2", ""),
        origin_neighborhood=SKYDROPX_ORIGIN.get("area_level3", ""),
        origin_address=SKYDROPX_ORIGIN_ADDRESS,
        origin_phone=SKYDROPX_ORIGIN_PHONE,
        carriers=", ".join(SKYDROPX_REQUESTED_CARRIERS),
    )


@app.route("/admin/subasta", methods=["GET", "POST"])
@admin_required
def admin_auction():
    finalize_closed_auctions()
    if request.method == "POST":
        name = request.form.get("nombre", "").strip()
        description = request.form.get("descripcion", "").strip()
        ends_at = request.form.get("termina_en", "").strip()
        image_upload_invalid = False
        try:
            image = save_product_image(request.files.get("imagen_archivo")) or ""
        except ValueError as error:
            flash(str(error), "error")
            image = ""
            image_upload_invalid = True
        try:
            price = float(request.form.get("precio", ""))
        except ValueError:
            price = 0
        try:
            min_increment = float(request.form.get("incremento", "50"))
        except ValueError:
            min_increment = 0
        package_dimensions = parse_package_dimensions(request.form)

        if (image_upload_invalid or not name or price <= 0 or min_increment <= 0
                or not description or not ends_at or not parse_local_datetime(ends_at)
                or not package_dimensions):
            flash("Completa el artículo, precio, descripción y final de la subasta.", "error")
        else:
            auction_id = max((int(item.get("id", 0)) for item in AUCTIONS), default=0) + 1
            AUCTIONS.insert(0, {
                "id": auction_id,
                "name": name,
                "price": price,
                "min_increment": min_increment,
                "description": description,
                "image": image or url_for("static", filename="logo.png"),
                "ends_at": ends_at,
                **package_dimensions,
            })
            save_auctions()
            log_admin_activity("Artículo agregado", "subasta", auction_id, f"{name} · cierre {ends_at}")
            flash("Artículo agregado a la subasta.", "success")
            return redirect(url_for("admin_auction"))
    return render_template("admin_auction.html", auctions=build_auction_cards())


@app.get("/admin/subasta/datos")
@admin_required
def admin_auction_data():
    """Return live auction data for the administrator dashboard."""
    finalize_closed_auctions()
    return jsonify({
        "auctions": build_auction_cards(),
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    })


@app.post("/admin/subasta/<int:auction_id>/eliminar")
@admin_required
def delete_auction(auction_id):
    before = len(AUCTIONS)
    AUCTIONS[:] = [item for item in AUCTIONS if int(item.get("id", 0)) != auction_id]
    if len(AUCTIONS) != before:
        save_auctions()
        log_admin_activity("Artículo retirado", "subasta", auction_id, "Subasta eliminada del catálogo")
        flash("Artículo retirado de la subasta.", "success")
    else:
        flash("No encontramos ese artículo de subasta.", "error")
    return redirect(url_for("admin_auction"))


@app.route("/admin/subasta/<int:auction_id>/editar", methods=["GET", "POST"])
@admin_required
def edit_auction(auction_id):
    auction_item = next((item for item in AUCTIONS if int(item.get("id", 0)) == auction_id), None)
    if not auction_item:
        flash("No encontramos ese artículo de subasta.", "error")
        return redirect(url_for("admin_auction"))
    if request.method == "POST":
        name = request.form.get("nombre", "").strip()
        description = request.form.get("descripcion", "").strip()
        ends_at = request.form.get("termina_en", "").strip()
        try:
            price = float(request.form.get("precio", ""))
        except ValueError:
            price = 0
        try:
            min_increment = float(request.form.get("incremento", ""))
        except ValueError:
            min_increment = 0
        package_dimensions = parse_package_dimensions(request.form)
        image_upload_invalid = False
        try:
            image = save_product_image(request.files.get("imagen_archivo")) or auction_item.get("image")
        except ValueError as error:
            flash(str(error), "error")
            image = auction_item.get("image")
            image_upload_invalid = True
        if (image_upload_invalid or not name or not description or price <= 0
                or min_increment <= 0 or not parse_local_datetime(ends_at) or not package_dimensions):
            flash("Completa los datos de la subasta con valores válidos.", "error")
        else:
            auction_item.update(
                name=name, price=price, description=description,
                ends_at=ends_at, min_increment=min_increment,
                image=image or url_for("static", filename="logo.png"),
                **package_dimensions,
            )
            save_auctions()
            log_admin_activity("Subasta editada", "subasta", auction_id, f"{name} · cierre {ends_at}")
            flash("Subasta actualizada.", "success")
            return redirect(url_for("admin_auction"))
    return render_template(
        "admin_auction.html",
        auctions=build_auction_cards(),
        auction=auction_item,
        editing=True,
    )


@app.get("/admin/pedidos")
@admin_required
def admin_orders():
    with closing(get_users_db()) as db:
        rows = db.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    orders = []
    status_counts = {}
    for row in rows:
        order = dict(row)
        order["lines"] = get_order_lines(row)
        orders.append(order)
        status_counts[order.get("status", "Pendiente")] = status_counts.get(order.get("status", "Pendiente"), 0) + 1
    order_statuses = ["Todos", "Pago pendiente", "Pagado", "En preparación", "Enviado", "Completado", "Cancelado", "Reembolsado"]
    return render_template(
        "admin_orders.html", orders=orders, status_counts=status_counts,
        order_statuses=order_statuses,
    )


@app.route("/admin/promociones", methods=["GET", "POST"])
@admin_required
def admin_coupons():
    if request.method == "POST":
        code = request.form.get("codigo", "").strip().upper()
        kind = request.form.get("tipo", "percent").strip()
        starts_at = request.form.get("inicia", "").strip()
        expires_at = request.form.get("termina", "").strip()
        try:
            value = float(request.form.get("valor", ""))
        except (TypeError, ValueError):
            value = 0
        try:
            usage_limit = max(int(request.form.get("limite", "0") or 0), 0)
        except (TypeError, ValueError):
            usage_limit = -1
        dates_valid = all(not value or parse_local_datetime(value) for value in (starts_at, expires_at))
        if (code == "BIENVENIDO10" or not re.fullmatch(r"[A-Z0-9_-]{3,32}", code) or kind not in {"percent", "fixed"}
                or value <= 0 or (kind == "percent" and value > 100) or usage_limit < 0 or not dates_valid):
            flash("Revisa el código, el valor y la vigencia del cupón.", "error")
        else:
            try:
                with closing(get_users_db()) as db:
                    db.execute(
                        "INSERT INTO coupons (code, kind, value, starts_at, expires_at, usage_limit) VALUES (?, ?, ?, ?, ?, ?)",
                        (code, kind, value, starts_at, expires_at, usage_limit),
                    )
                    db.commit()
                log_admin_activity("Cupón creado", "promoción", code, f"{kind} · valor {value}")
                flash("Cupón creado.", "success")
                return redirect(url_for("admin_coupons"))
            except sqlite3.IntegrityError:
                flash("Ya existe un cupón con ese código.", "error")
    with closing(get_users_db()) as db:
        coupons = db.execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
    return render_template("admin_coupons.html", coupons=coupons)


@app.post("/admin/promociones/<int:coupon_id>/activar")
@admin_required
def toggle_coupon(coupon_id):
    with closing(get_users_db()) as db:
        db.execute("UPDATE coupons SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (coupon_id,))
        db.commit()
    log_admin_activity("Cupón actualizado", "promoción", coupon_id, "Se cambió su estado")
    flash("Estado del cupón actualizado.", "success")
    return redirect(url_for("admin_coupons"))


@app.post("/admin/promociones/<int:coupon_id>/eliminar")
@admin_required
def delete_coupon(coupon_id):
    with closing(get_users_db()) as db:
        cursor = db.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))
        db.commit()
    if cursor.rowcount:
        log_admin_activity("Cupón eliminado", "promoción", coupon_id, "Promoción eliminada")
    flash("Cupón eliminado." if cursor.rowcount else "No encontramos ese cupón.", "success" if cursor.rowcount else "error")
    return redirect(url_for("admin_coupons"))


@app.get("/admin/pagos")
@admin_required
def admin_payments():
    payments = []
    with closing(get_users_db()) as db:
        rows = db.execute(
            "SELECT * FROM orders WHERE payment_method = 'stripe' ORDER BY id DESC LIMIT 50"
        ).fetchall()
    stripe_module = None
    if STRIPE_SECRET_KEY:
        try:
            import stripe as stripe_module
            stripe_module.api_key = STRIPE_SECRET_KEY
        except ImportError:
            stripe_module = None
    payment_groups = {"processing": [], "paid": [], "refunded": []}
    for row in rows:
        payment = dict(row)
        payment["stripe_status"] = "Procesando"
        payment["payment_intent"] = payment.get("stripe_payment_intent_id", "")
        stripe_payment_status = "unpaid"
        if stripe_module and payment.get("stripe_session_id"):
            try:
                session_object = stripe_module.checkout.Session.retrieve(payment["stripe_session_id"])
                stripe_payment_status = str(session_object.get("payment_status", "unpaid")).lower()
                payment["payment_intent"] = session_object.get("payment_intent", "") or payment["payment_intent"]
            except Exception:
                stripe_payment_status = "unpaid"
        if payment.get("refunded_at") or payment.get("status") == "Reembolsado":
            payment["payment_group"] = "refunded"
            payment["payment_group_label"] = "Reembolsado"
            payment["stripe_status"] = "Reembolsado"
        elif stripe_payment_status == "paid" or payment.get("status") in {"Pagado", "Enviado", "Completado"} or "prepar" in str(payment.get("status", "")).lower():
            payment["payment_group"] = "paid"
            payment["payment_group_label"] = "Pagado"
            payment["stripe_status"] = "Pagado"
        else:
            payment["payment_group"] = "processing"
            payment["payment_group_label"] = "Procesando"
            payment["stripe_status"] = "Procesando"
        payments.append(payment)
        payment_groups[payment["payment_group"]].append(payment)
    return render_template(
        "admin_payments.html",
        payments=payments,
        payment_groups=payment_groups,
        stripe_enabled=bool(stripe_module),
    )


@app.post("/admin/pagos/<int:order_id>/reembolsar")
@admin_required
def refund_payment(order_id):
    with closing(get_users_db()) as db:
        order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order or order["payment_method"] != "stripe":
        flash("No encontramos un pago de Stripe para ese pedido.", "error")
        return redirect(url_for("admin_payments"))
    if order["status"] == "Reembolsado":
        flash("Ese pedido ya fue reembolsado.", "error")
        return redirect(url_for("admin_payments"))
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        payment_intent = order["stripe_payment_intent_id"]
        if not payment_intent and order["stripe_session_id"]:
            payment_intent = stripe.checkout.Session.retrieve(order["stripe_session_id"]).get("payment_intent")
        if not payment_intent:
            raise RuntimeError("Stripe no devolvió el PaymentIntent de este pedido.")
        stripe.Refund.create(payment_intent=payment_intent)
    except Exception as error:
        flash(f"No se pudo crear el reembolso en Stripe: {error}", "error")
        return redirect(url_for("admin_payments"))
    with closing(get_users_db()) as db:
        db.execute(
            "UPDATE orders SET status = 'Reembolsado', refunded_at = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="minutes"), order_id),
        )
        db.commit()
    restore_order_stock(order_id, final_status="Reembolsado")
    log_admin_activity("Pago reembolsado", "pedido", order_id, "Reembolso solicitado en Stripe")
    flash("Reembolso creado en Stripe.", "success")
    return redirect(url_for("admin_payments"))


@app.post("/admin/pedidos/<int:order_id>/estado")
@admin_required
def update_order_status(order_id):
    allowed_statuses = {"Pendiente", "Pago pendiente", "Pagado", "En preparación", "Enviado", "Completado", "Cancelado", "Reembolsado"}
    status = request.form.get("estado", "").strip()
    carrier = request.form.get("transportista", "").strip()[:80]
    tracking_number = request.form.get("guia", "").strip()[:120]
    shipping_note = request.form.get("nota_envio", "").strip()[:240]
    if status not in allowed_statuses:
        flash("Estado de pedido no válido.", "error")
        return redirect(url_for("admin_orders"))
    with closing(get_users_db()) as db:
        previous = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        cursor = db.execute(
            "UPDATE orders SET status = ?, shipping_carrier = ?, tracking_number = ?, shipping_note = ? WHERE id = ?",
            (status, carrier, tracking_number, shipping_note, order_id),
        )
        updated = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        db.commit()
    if status == "Cancelado" and previous and previous["status"] != "Cancelado":
        restore_order_stock(order_id)
    if cursor.rowcount and updated and (
        not previous
        or previous["status"] != status
        or previous["shipping_carrier"] != carrier
        or previous["tracking_number"] != tracking_number
        or previous["shipping_note"] != shipping_note
    ):
        send_order_status_update(dict(updated), previous["status"] if previous else "")
        log_admin_activity("Pedido actualizado", "pedido", order_id, f"Estado: {status}")
    flash("Pedido actualizado." if cursor.rowcount else "No encontramos ese pedido.", "success" if cursor.rowcount else "error")
    return redirect(url_for("admin_orders"))


@app.post("/admin/pedidos/<int:order_id>/guia")
@admin_required
def create_order_shipping_label(order_id):
    with closing(get_users_db()) as db:
        row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        flash("No encontramos ese pedido.", "error")
        return redirect(url_for("admin_orders"))
    order, error = create_skydropx_shipment(dict(row))
    if order.get("shipping_label_url"):
        flash("La guía de envío se generó correctamente.", "success")
    elif order.get("skydropx_shipment_id") and str(order.get("shipping_note", "")).startswith("Envío creado"):
        flash("La guía se creó correctamente; Skydropx está terminando de generar la etiqueta.", "success")
    else:
        flash(error or "No se pudo generar la guía. Revisa la configuración de Skydropx.", "error")
    return redirect(url_for("admin_orders"))


@app.get("/admin/usuarios")
@admin_required
def admin_users():
    with closing(get_users_db()) as db:
        users = db.execute(
            """SELECT u.id, u.name, u.email, u.google_sub, u.created_at,
                      COUNT(o.id) AS order_count, COALESCE(SUM(o.total), 0) AS total_spent
               FROM users u LEFT JOIN orders o ON o.user_id = u.id
               GROUP BY u.id ORDER BY u.id DESC"""
        ).fetchall()
    return render_template("admin_users.html", users=users)


@app.get("/admin/usuarios/<int:user_id>")
@admin_required
def admin_user_detail(user_id):
    with closing(get_users_db()) as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash("No encontramos ese usuario.", "error")
            return redirect(url_for("admin_users"))
        rows = db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    orders = []
    for row in rows:
        order = dict(row)
        order["lines"] = get_order_lines(row)
        orders.append(order)
    return render_template("admin_user_detail.html", user=user, orders=orders)


@app.post("/admin/usuarios/<int:user_id>/eliminar")
@admin_required
def delete_user(user_id):
    with closing(get_users_db()) as db:
        cursor = db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        db.commit()
    if cursor.rowcount:
        log_admin_activity("Usuario eliminado", "usuario", user_id, "Cuenta eliminada desde administración")
    flash("Usuario eliminado." if cursor.rowcount else "No encontramos ese usuario.", "success" if cursor.rowcount else "error")
    return redirect(url_for("admin_users"))


@app.get("/admin/reportes")
@admin_required
def admin_reports():
    with closing(get_users_db()) as db:
        order_stats = db.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(total), 0) AS revenue FROM orders WHERE status != 'Cancelado'"
        ).fetchone()
        pending_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN ('Pendiente', 'Pago pendiente')"
        ).fetchone()[0]
        user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_stock = sum(max(int(product.get("stock", 0)), 0) for product in PRODUCTS)
    bid_count = sum(len(item.get("bids", [])) for item in AUCTIONS if isinstance(item.get("bids", []), list))
    most_viewed = max(PRODUCTS, key=lambda product: product.get("views", 0), default=None)
    return render_template(
        "admin_reports.html",
        total_orders=order_stats["total"], revenue=order_stats["revenue"],
        pending_orders=pending_orders, user_count=user_count,
        total_products=len(PRODUCTS), total_stock=total_stock,
        auction_count=len(AUCTIONS), bid_count=bid_count, most_viewed=most_viewed,
        recent_activity=recent_activity,
    )


@app.get("/admin/pedidos/exportar")
@admin_required
def export_orders():
    with closing(get_users_db()) as db:
        rows = db.execute(
            "SELECT id, created_at, customer_name, customer_email, phone, city, state, postal_code, delivery_method, payment_method, total, status, tracking_number, lines_json FROM orders ORDER BY id DESC"
        ).fetchall()
    return csv_download(
        "fr-beisshop-pedidos.csv",
        ["Pedido", "Fecha", "Cliente", "Correo", "Teléfono", "Ciudad", "Estado", "C.P.", "Entrega", "Pago", "Total MXN", "Estado del pedido", "Guía", "Productos"],
        [tuple(row) for row in rows],
    )


@app.get("/admin/actividad")
@admin_required
def admin_activity():
    with closing(get_users_db()) as db:
        activity = db.execute(
            "SELECT action, entity, entity_id, detail, created_at FROM admin_activity ORDER BY id DESC LIMIT 200"
        ).fetchall()
    return render_template("admin_activity.html", activity=activity)


@app.get("/admin/actividad/exportar")
@admin_required
def export_admin_activity():
    with closing(get_users_db()) as db:
        rows = db.execute(
            "SELECT action, entity, entity_id, detail, created_at FROM admin_activity ORDER BY id DESC"
        ).fetchall()
    return csv_download(
        "fr-beisshop-actividad-admin.csv",
        ["Acción", "Elemento", "ID", "Detalle", "Fecha"],
        [tuple(row) for row in rows],
    )


@app.get("/admin/respaldo")
@admin_required
def admin_backup():
    with closing(get_users_db()) as db:
        orders = [dict(row) for row in db.execute("SELECT * FROM orders ORDER BY id").fetchall()]
        users = [dict(row) for row in db.execute("SELECT id, name, email, google_sub, phone, address, neighborhood, city, state, postal_code, created_at FROM users ORDER BY id").fetchall()]
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "products": PRODUCTS,
        "auctions": AUCTIONS,
        "homepage": public_homepage_settings(),
        "orders": orders,
        "users": users,
    }
    response = Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype="application/json; charset=utf-8")
    response.headers["Content-Disposition"] = 'attachment; filename="fr-beisshop-respaldo.json"'
    return response


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    active_admin_section = request.args.get("seccion", "Todos").strip()
    if active_admin_section not in ["Todos", *PRODUCT_SECTIONS]:
        active_admin_section = "Todos"
    active_admin_category = request.args.get("tipo", "Todos").strip()
    if active_admin_category not in ["Todos", *PRODUCT_CATEGORIES]:
        active_admin_category = "Todos"
    if request.method == "POST":
        name = request.form.get("nombre", "").strip()
        submitted_category = request.form.get("categoria", "").strip()
        brand_category_selected = submitted_category == "__nuestra_marca__"
        category = "Accesorios de entrenamiento" if brand_category_selected else submitted_category
        brand_destination_selected = request.form.get("seccion", "").strip() == "__nuestra_marca__"
        if category == "Grip":
            selected_sections = [
                section for section in PRODUCT_SECTIONS
                if section in request.form.getlist("secciones")
            ]
        else:
            requested_section = request.form.get("seccion", "").strip()
            if requested_section == "__nuestra_marca__":
                requested_section = "Béisbol"
            selected_sections = [requested_section] if requested_section in PRODUCT_SECTIONS else []
        section = selected_sections[0] if selected_sections else ""
        description = request.form.get("descripcion", "").strip()
        tag = "Nuestra marca" if brand_category_selected else category
        brand_featured = brand_category_selected or brand_destination_selected or request.form.get("mostrar_en_marca") == "1"
        measure = request.form.get("medida", "").strip()
        bat_measure = measure
        bat_weight = request.form.get("peso", "").strip()
        grip_thickness = request.form.get("grosor", "").strip()
        guantaleta_size = request.form.get("talla", "").strip()
        customizable = category == "Bat" and request.form.get("personalizable") == "1"
        wood_colors = parse_color_list(request.form.get("colores_bat"), ["Natural", "Negro", "Rojo", "Azul", "Rosa"]) if customizable else []
        custom_grip_colors = parse_color_list(request.form.get("colores_grip"), ["Negro", "Rojo", "Azul", "Blanco"]) if customizable else []
        needs_bat_details = category == "Bat"
        needs_glove_measure = category == "Guantes"
        needs_grip_thickness = category == "Grip"
        needs_guantaleta_size = category == "Guantaletas"
        image_upload_invalid = False
        try:
            images = save_product_images(request.files.getlist("imagen_archivo"))
        except ValueError as error:
            flash(str(error), "error")
            images = []
            image_upload_invalid = True
        try:
            price = float(request.form.get("precio", ""))
        except ValueError:
            price = 0
        try:
            stock = int(request.form.get("stock", ""))
        except ValueError:
            stock = -1
        package_dimensions = parse_package_dimensions(request.form)

        if (image_upload_invalid or not name or category not in PRODUCT_CATEGORIES
                or not selected_sections or price <= 0 or stock < 0 or not package_dimensions
                or (needs_glove_measure and measure not in GLOVE_MEASURES)
                or (needs_grip_thickness and grip_thickness not in GRIP_THICKNESSES)
                or (needs_guantaleta_size and guantaleta_size not in GUANTALETA_SIZES)
                or (needs_bat_details and (
                    bat_measure not in BAT_MEASURES_BY_SECTION.get(section, [])
                    or bat_weight not in BAT_WEIGHTS_BY_SECTION.get(section, [])
                ))):
            flash("Completa nombre, categoría, sección, precio y datos válidos del paquete.", "error")
        else:
            product_id = max((product["id"] for product in PRODUCTS), default=0) + 1
            product = {
                "id": product_id,
                "name": name,
                "category": category,
                "section": section,
                "sections": selected_sections,
                "price": price,
                "stock": stock,
                **package_dimensions,
                "description": description or "Producto disponible en FR BEISSHOP.",
                "tag": tag,
                "brand_featured": brand_featured,
                "bat_measure": bat_measure if needs_bat_details else "",
                "bat_weight": bat_weight if needs_bat_details else "",
                "glove_measure": measure if needs_glove_measure else "",
                "grip_thickness": grip_thickness if needs_grip_thickness else "",
                "guantaleta_size": guantaleta_size if needs_guantaleta_size else "",
                "customizable": customizable,
                "wood_colors": wood_colors,
                "custom_grip_colors": custom_grip_colors,
                "images": images or [url_for("static", filename="logo.png")],
                "image": images[0] if images else url_for("static", filename="logo.png"),
                "views": 0,
                "admin_added": True,
                "active": True,
            }
            PRODUCTS.append(product)
            PRODUCT_BY_ID[product_id] = product
            save_products()
            if brand_category_selected or brand_destination_selected:
                log_admin_activity("Producto agregado a Nuestra marca", "producto", product_id, f"{name} · stock {stock}")
                flash("Producto agregado a Nuestra marca.", "success")
            else:
                log_admin_activity("Producto agregado", "producto", product_id, f"{name} · stock {stock}")
                flash("Producto agregado a la tienda.", "success")
            return redirect(url_for("admin"))
    most_viewed = max(PRODUCTS, key=lambda product: product.get("views", 0), default=None)
    admin_products = [
        product for product in PRODUCTS
        if product.get("active", True)
        and (active_admin_section == "Todos"
        or active_admin_section in get_product_sections(product)
        )
    ]
    admin_products = [
        product for product in admin_products
        if active_admin_category == "Todos"
        or product.get("category") == active_admin_category
    ]
    disabled_products = sorted(
        [product for product in PRODUCTS if not product.get("active", True)],
        key=lambda product: str(product.get("name", "")).casefold(),
    )
    return render_template(
        "admin.html",
        products=admin_products,
        disabled_products=disabled_products,
        deleted_products=deleted_products_for_admin(),
        active_admin_section=active_admin_section,
        active_admin_category=active_admin_category,
        categories=PRODUCT_CATEGORIES,
        sections=PRODUCT_SECTIONS,
        glove_measures=GLOVE_MEASURES,
        guantaleta_sizes=GUANTALETA_SIZES,
        grip_thicknesses=GRIP_THICKNESSES,
        most_viewed=most_viewed,
    )


@app.post("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("index"))


@app.route("/admin/producto/<int:product_id>/editar", methods=["GET", "POST"])
@admin_required
def edit_product(product_id):
    product = PRODUCT_BY_ID.get(product_id)
    if not product:
        flash("No encontramos ese producto.", "error")
        return redirect(url_for("admin"))
    gallery_images = product_gallery_options(product)

    if request.method == "POST":
        name = request.form.get("nombre", "").strip()
        category = request.form.get("categoria", "").strip()
        if category == "Grip":
            selected_sections = [
                section for section in PRODUCT_SECTIONS
                if section in request.form.getlist("secciones")
            ]
        else:
            requested_section = request.form.get("seccion", "").strip()
            selected_sections = [requested_section] if requested_section in PRODUCT_SECTIONS else []
        section = selected_sections[0] if selected_sections else ""
        description = request.form.get("descripcion", "").strip()
        brand_featured = request.form.get("mostrar_en_marca") == "1"
        measure = request.form.get("medida", "").strip()
        bat_measure = measure
        bat_weight = request.form.get("peso", "").strip()
        grip_thickness = request.form.get("grosor", "").strip()
        guantaleta_size = request.form.get("talla", "").strip()
        customizable = category == "Bat" and request.form.get("personalizable") == "1"
        wood_colors = parse_color_list(request.form.get("colores_bat"), ["Natural", "Negro", "Rojo", "Azul", "Rosa"]) if customizable else []
        custom_grip_colors = parse_color_list(request.form.get("colores_grip"), ["Negro", "Rojo", "Azul", "Blanco"]) if customizable else []
        needs_bat_details = category == "Bat"
        needs_glove_measure = category == "Guantes"
        needs_grip_thickness = category == "Grip"
        needs_guantaleta_size = category == "Guantaletas"
        image_upload_invalid = False
        delete_image_invalid = False
        bat_view_upload_invalid = False
        bat_views = dict(product.get("bat_views") or {})
        if customizable:
            for view_key in CUSTOM_BAT_VIEW_LABELS:
                if request.form.get(f"eliminar_bat_view_{view_key}") == "1":
                    bat_views.pop(view_key, None)
                selected_existing_view = request.form.get(f"bat_view_existing_{view_key}", "").strip()
                if selected_existing_view:
                    existing_images = set(gallery_images)
                    if selected_existing_view in existing_images:
                        bat_views[view_key] = selected_existing_view
                    else:
                        flash(f"La foto seleccionada para {CUSTOM_BAT_VIEW_LABELS[view_key]} no es válida.", "error")
                        bat_view_upload_invalid = True
                upload = request.files.get(f"bat_view_{view_key}")
                if upload and upload.filename:
                    try:
                        saved_view = save_product_image(upload)
                        if saved_view:
                            bat_views[view_key] = saved_view
                    except ValueError as error:
                        flash(f"{CUSTOM_BAT_VIEW_LABELS[view_key]}: {error}", "error")
                        bat_view_upload_invalid = True
        else:
            bat_views = {}
        existing_product_images = [
            str(image).strip()
            for image in (product.get("images") or [])
            if str(image).strip()
        ]
        requested_deleted_images = {
            str(image).strip()
            for image in request.form.getlist("eliminar_imagen")
            if str(image).strip()
        }
        gallery_field_present = "galeria_imagenes" in request.form
        requested_gallery_images = [
            str(image).strip()
            for image in request.form.getlist("galeria_imagenes")
            if str(image).strip()
        ]
        unknown_gallery_images = set(requested_gallery_images) - set(gallery_images)
        if gallery_field_present and unknown_gallery_images:
            flash("Una o más fotos seleccionadas no son válidas. Recarga la página e inténtalo de nuevo.", "error")
            delete_image_invalid = True
        selected_gallery_images = []
        for image in requested_gallery_images:
            if image not in selected_gallery_images and image in gallery_images:
                selected_gallery_images.append(image)
        unknown_deleted_images = requested_deleted_images - set(existing_product_images)
        if unknown_deleted_images:
            flash("Una o más fotos seleccionadas ya no están disponibles. Recarga la página e inténtalo de nuevo.", "error")
            delete_image_invalid = True
        remaining_product_images = [
            image for image in existing_product_images
            if image not in requested_deleted_images
        ]
        removed_product_images = set()
        uploaded_images = []
        try:
            uploaded_images = save_product_images(request.files.getlist("imagen_archivo"))
            if gallery_field_present:
                # La galería se administra desde el selector: respeta el orden de los
                # elementos, permite quitar fotos y agrega las nuevas al final.
                images = selected_gallery_images + [
                    image for image in uploaded_images
                    if image not in selected_gallery_images
                ]
                if not images:
                    flash("Conserva al menos una foto del producto o sube una nueva.", "error")
                    delete_image_invalid = True
                    images = existing_product_images or [product.get("image", url_for("static", filename="logo.png"))]
                removed_product_images = set(gallery_images) - set(images)
            elif uploaded_images:
                # Compatibilidad con formularios antiguos: las fotos nuevas reemplazan la galería.
                images = uploaded_images
                removed_product_images = set(existing_product_images)
            elif requested_deleted_images and not remaining_product_images:
                flash("Conserva al menos una foto del producto. Puedes subir una nueva antes de eliminar la última.", "error")
                delete_image_invalid = True
                images = existing_product_images or [product.get("image", url_for("static", filename="logo.png"))]
            else:
                images = remaining_product_images or existing_product_images or [product.get("image", url_for("static", filename="logo.png"))]
                removed_product_images = requested_deleted_images
        except ValueError as error:
            flash(str(error), "error")
            images = existing_product_images or [product.get("image", url_for("static", filename="logo.png"))]
            image_upload_invalid = True
        if removed_product_images:
            bat_views = {
                key: value for key, value in bat_views.items()
                if value and value not in removed_product_images
            }
        try:
            price = float(request.form.get("precio", ""))
        except ValueError:
            price = 0
        try:
            stock = int(request.form.get("stock", ""))
        except ValueError:
            stock = -1
        package_dimensions = parse_package_dimensions(request.form)

        if (image_upload_invalid or delete_image_invalid or bat_view_upload_invalid or not name or category not in PRODUCT_CATEGORIES
                or not selected_sections or price <= 0 or stock < 0 or not package_dimensions
                or (needs_glove_measure and measure not in GLOVE_MEASURES)
                or (needs_grip_thickness and grip_thickness not in GRIP_THICKNESSES)
                or (needs_guantaleta_size and guantaleta_size not in GUANTALETA_SIZES)
                or (needs_bat_details and (
                    bat_measure not in BAT_MEASURES_BY_SECTION.get(section, [])
                    or bat_weight not in BAT_WEIGHTS_BY_SECTION.get(section, [])
                ))):
            flash("Completa nombre, categoría, sección, precio y datos válidos del paquete.", "error")
        else:
            product.update(
                name=name,
                category=category,
                section=section,
                sections=selected_sections,
                price=price,
                stock=stock,
                **package_dimensions,
                description=description or "Producto disponible en FR BEISSHOP.",
                brand_featured=brand_featured,
                bat_measure=bat_measure if needs_bat_details else "",
                bat_weight=bat_weight if needs_bat_details else "",
                glove_measure=measure if needs_glove_measure else "",
                grip_thickness=grip_thickness if needs_grip_thickness else "",
                guantaleta_size=guantaleta_size if needs_guantaleta_size else "",
                customizable=customizable,
                wood_colors=wood_colors,
                custom_grip_colors=custom_grip_colors,
                bat_views=bat_views,
                images=images,
                image=images[0] if images else url_for("static", filename="logo.png"),
            )
            save_products()
            log_admin_activity("Producto editado", "producto", product_id, f"{name} · stock {stock}")
            if requested_deleted_images and not uploaded_images:
                flash(f"Producto actualizado. Se eliminaron {len(requested_deleted_images)} foto(s) de la galería.", "success")
            else:
                flash("Producto actualizado.", "success")
            return redirect(url_for("admin"))

    return render_template(
        "admin_edit.html",
        product=product,
        categories=PRODUCT_CATEGORIES,
        sections=PRODUCT_SECTIONS,
        glove_measures=GLOVE_MEASURES,
        guantaleta_sizes=GUANTALETA_SIZES,
        grip_thicknesses=GRIP_THICKNESSES,
        bat_view_labels=CUSTOM_BAT_VIEW_LABELS,
        gallery_images=gallery_images,
        selected_product_sections=get_product_sections(product),
    )


@app.post("/admin/producto/<int:product_id>/eliminar")
@admin_required
def delete_product(product_id):
    product = PRODUCT_BY_ID.pop(product_id, None)
    if product:
        deleted_at = datetime.now()
        DELETED_PRODUCTS[:] = [
            entry for entry in DELETED_PRODUCTS
            if int(entry.get("product", {}).get("id", -1)) != product_id
        ]
        DELETED_PRODUCTS.append({
            "product": copy.deepcopy(product),
            "deleted_at": deleted_at.isoformat(timespec="seconds"),
            "expires_at": (deleted_at + timedelta(days=DELETED_PRODUCTS_RETENTION_DAYS)).isoformat(timespec="seconds"),
        })
        PRODUCTS.remove(product)
        save_products()
        save_deleted_products()
        log_admin_activity("Producto eliminado", "producto", product_id, product.get("name", ""))
        flash("Producto eliminado de la tienda.", "success")
    else:
        flash("No encontramos ese producto.", "error")
    return redirect(url_for("admin"))


@app.post("/admin/producto-papelera/<int:product_id>/restaurar")
@admin_required
def restore_deleted_product(product_id):
    prune_deleted_products()
    entry_index = next(
        (
            index for index, entry in enumerate(DELETED_PRODUCTS)
            if int(entry.get("product", {}).get("id", -1)) == product_id
        ),
        None,
    )
    if entry_index is None:
        flash("El producto ya no está disponible en la papelera.", "error")
        return redirect(url_for("admin", _anchor="papelera"))
    if product_id in PRODUCT_BY_ID:
        flash("No se puede restaurar porque ya existe un producto con ese identificador.", "error")
        return redirect(url_for("admin", _anchor="papelera"))

    product = copy.deepcopy(DELETED_PRODUCTS[entry_index].get("product", {}))
    normalize_product_images(product)
    product.setdefault("views", 0)
    product.setdefault("stock", 0)
    product.setdefault("active", True)
    product.setdefault("brand_featured", False)
    PRODUCTS.append(product)
    PRODUCT_BY_ID[product_id] = product
    DELETED_PRODUCTS.pop(entry_index)
    save_products()
    save_deleted_products()
    log_admin_activity("Producto restaurado", "producto", product_id, product.get("name", ""))
    flash("Producto restaurado en el catálogo.", "success")
    return redirect(url_for("admin", _anchor="productos"))


@app.post("/admin/producto-papelera/<int:product_id>/eliminar-definitivamente")
@admin_required
def permanently_delete_deleted_product(product_id):
    prune_deleted_products()
    with PRODUCTS_LOCK:
        entry_index = next(
            (
                index for index, entry in enumerate(DELETED_PRODUCTS)
                if int(entry.get("product", {}).get("id", -1)) == product_id
            ),
            None,
        )
        if entry_index is None:
            flash("El producto ya no está disponible en la papelera.", "error")
            return redirect(url_for("admin", _anchor="papelera"))

        entry = DELETED_PRODUCTS.pop(entry_index)
        save_deleted_products()

    product = entry.get("product", {})
    log_admin_activity(
        "Producto eliminado definitivamente",
        "producto",
        product_id,
        product.get("name", ""),
    )
    flash("Producto eliminado definitivamente de la papelera.", "success")
    return redirect(url_for("admin", _anchor="papelera"))


@app.post("/admin/producto/<int:product_id>/estado")
@admin_required
def toggle_product_status(product_id):
    product = PRODUCT_BY_ID.get(product_id)
    if not product:
        flash("No encontramos ese producto.", "error")
        return redirect(url_for("admin"))
    product["active"] = not product.get("active", True)
    save_products()
    log_admin_activity("Producto actualizado", "producto", product_id, "Activado" if product["active"] else "Desactivado")
    flash(
        "Producto activado en la tienda." if product["active"] else "Producto desactivado de la tienda.",
        "success",
    )
    return redirect(url_for("admin"))


@app.post("/carrito/agregar/<int:product_id>")
def add_to_cart(product_id):
    ajax_request = request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"

    def finish(message, category="success", target=None, status=200):
        if ajax_request:
            return jsonify({
                "ok": status < 400,
                "message": message,
                "category": category,
                "cart_count": get_cart_count(),
                "continue_url": target or request.referrer or url_for("index"),
                "cart_url": url_for("cart"),
            }), status
        flash(message, category)
        return redirect(target or request.referrer or url_for("index"))

    if product_id not in PRODUCT_BY_ID or not PRODUCT_BY_ID[product_id].get("active", True):
        return finish("No encontramos ese producto.", "error", url_for("index"), 404)

    product = PRODUCT_BY_ID[product_id]
    try:
        stock = max(int(product.get("stock", 0)), 0)
    except (TypeError, ValueError):
        stock = 0
    if stock <= 0:
        return finish("Este producto está agotado.", "error", status=400)
    cart = session.get("cart", {})
    if product.get("customizable"):
        measure = request.form.get("medida", "").strip()
        grip_enabled = request.form.get("usar_grip") == "1"
        grip_color = request.form.get("color_grip", "").strip()
        logo_color = request.form.get("logo_color", "Plateado").strip() or "Plateado"
        bat_color = request.form.get("color_bat", "").strip()
        bat_handle_color = request.form.get("color_bat_handle", "").strip() or "Natural"
        personal_name = request.form.get("nombre_personalizado", "").strip()
        player_number = request.form.get("numero", "").strip()
        valid_grip_colors = set(product.get("custom_grip_colors") or ["Negro", "Rojo", "Azul", "Blanco"])
        valid_logo_colors = {"Blanco", "Plateado", "Dorado", "Negro"}
        valid_bat_colors = set(product.get("wood_colors") or [])
        if (measure not in BAT_MEASURES_BY_SECTION.get("B\u00e9isbol", [])
                or (grip_enabled and grip_color not in valid_grip_colors)
                or logo_color not in valid_logo_colors
                or (valid_bat_colors and bat_color not in valid_bat_colors)
                or (valid_bat_colors and bat_handle_color not in valid_bat_colors)
                or len(personal_name) > 18
                or (player_number and (not player_number.isdigit() or len(player_number) > 2))):
            return finish("Revisa la medida y las opciones de personalización del bat.", "error", url_for("product_detail", product_id=product_id), 400)

        customizations = {
            "Medida": f'{measure} pulgadas',
            "Grip": grip_color if grip_enabled else "Sin grip",
            "Color del logo": logo_color,
        }
        if valid_bat_colors:
            customizations["Color principal"] = bat_color
            customizations["Color del mango"] = bat_handle_color
        if personal_name:
            customizations["Nombre"] = personal_name
        if player_number:
            customizations["Número"] = player_number
        line_id = f"{product_id}-{uuid4().hex}"
        custom_image = save_custom_bat_preview(request.form.get("bat_preview_image", ""))
        cart[line_id] = {
            "product_id": product_id,
            "quantity": 1,
            "customizations": customizations,
            "custom_image": custom_image,
        }
        session["cart"] = cart
        return finish("Bat personalizado agregado al carrito.", "success", url_for("cart"))

    key = str(product_id)
    existing_quantity = cart.get(key, 0)
    if isinstance(existing_quantity, dict):
        existing_quantity = existing_quantity.get("quantity", 0)
    try:
        next_quantity = int(existing_quantity) + 1
    except (TypeError, ValueError):
        next_quantity = 1
    if next_quantity > stock:
        return finish(f"Solo quedan {stock} unidades disponibles.", "error", status=400)
    cart[key] = next_quantity
    session["cart"] = cart
    return finish("Producto agregado al carrito.", "success", request.referrer or url_for("index"))


@app.post("/carrito/actualizar")
def update_cart():
    cart = session.get("cart", {})
    for line_id in list(cart):
        if request.form.get(f"quitar-{line_id}") == "1":
            cart.pop(line_id, None)
            continue
        try:
            quantity = int(request.form.get(f"cantidad-{line_id}", 0))
        except ValueError:
            quantity = 0
        entry = cart[line_id]
        try:
            product_id = int(entry.get("product_id", 0)) if isinstance(entry, dict) else int(line_id)
        except (TypeError, ValueError):
            product_id = 0
        if (quantity <= 0 or product_id not in PRODUCT_BY_ID
                or not PRODUCT_BY_ID[product_id].get("active", True)):
            cart.pop(line_id, None)
        elif isinstance(entry, dict):
            entry["quantity"] = min(quantity, 99)
        else:
            cart[line_id] = min(quantity, 99)
    session["cart"] = cart
    return redirect(url_for("cart"))


@app.post("/carrito/cupon")
def apply_coupon():
    code = request.form.get("codigo", "").strip().upper()
    if not code:
        session.pop("coupon_code", None)
        flash("Cupón eliminado del carrito.", "success")
        return redirect(url_for("cart"))
    coupon = get_coupon(code)
    valid, message = coupon_status(coupon)
    if not valid:
        session.pop("coupon_code", None)
        flash(message or "No encontramos un cupón válido con ese código.", "error")
    elif not coupon_available_for_customer(
        coupon, session.get("user_email", ""), session.get("user_id")
    ):
        session.pop("coupon_code", None)
        flash("El código BIENVENIDO10 solo es válido en la primera compra.", "error")
    else:
        session["coupon_code"] = code
        flash("Cupón aplicado al carrito.", "success")
    return redirect(url_for("cart"))


@app.get("/carrito")
def cart():
    items, total = cart_details()
    coupon = get_coupon(session.get("coupon_code"))
    if coupon and not coupon_available_for_customer(
        coupon, session.get("user_email", ""), session.get("user_id")
    ):
        session.pop("coupon_code", None)
        flash("El código BIENVENIDO10 solo es válido en la primera compra.", "error")
        coupon = None
    discount = calculate_coupon_discount(coupon, total)
    if coupon and not discount and total:
        valid, _ = coupon_status(coupon)
        if not valid:
            session.pop("coupon_code", None)
            coupon = None
    checkout_profile = {}
    if session.get("user_id"):
        with closing(get_users_db()) as db:
            profile_row = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        checkout_profile = dict(profile_row) if profile_row else {}
    return render_template(
        "cart.html", items=items, total=total, discount=discount,
        coupon=coupon, shipping_estimate=SHIPPING_ESTIMATE, checkout_profile=checkout_profile,
    )


@app.get("/checkout")
def checkout():
    items, total = cart_details()
    if not items:
        flash("Tu carrito está vacío.", "error")
        return redirect(url_for("cart"))
    coupon = get_coupon(session.get("coupon_code"))
    if coupon and not coupon_available_for_customer(
        coupon, session.get("user_email", ""), session.get("user_id")
    ):
        session.pop("coupon_code", None)
        flash("El código BIENVENIDO10 solo es válido en la primera compra.", "error")
        coupon = None
    discount = calculate_coupon_discount(coupon, total)
    if coupon and not discount and total:
        valid, _ = coupon_status(coupon)
        if not valid:
            session.pop("coupon_code", None)
            coupon = None
    checkout_profile = {}
    if session.get("user_id"):
        with closing(get_users_db()) as db:
            profile_row = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        checkout_profile = dict(profile_row) if profile_row else {}
    return render_template(
        "checkout.html", items=items, total=total, discount=discount,
        coupon=coupon, shipping_estimate=SHIPPING_ESTIMATE, checkout_profile=checkout_profile,
    )


@app.post("/api/envio/cotizar")
def quote_shipping():
    """Return Skydropx rates for the current cart without exposing credentials."""
    items, _ = cart_details()
    if not items:
        return jsonify({"error": "Tu carrito está vacío."}), 400
    payload = request.get_json(silent=True) or {}
    destination = {
        "address": str(payload.get("address", "")).strip(),
        "neighborhood": str(payload.get("neighborhood", "")).strip(),
        "city": str(payload.get("city", "")).strip(),
        "state": str(payload.get("state", "")).strip(),
        "postal_code": str(payload.get("postal_code", "")).strip(),
    }
    if is_mexicali_postal_code(destination["postal_code"]):
        session.pop("skydropx_quote", None)
        return jsonify({"provider": "Entrega personal", "local": True, "rates": []})
    try:
        quotation = skydropx_quote(items, destination)
    except RuntimeError as error:
        return jsonify({"provider": "Skydropx", "error": str(error), "configured": skydropx_is_configured()}), 502
    session["skydropx_quote"] = {
        "quotation_id": quotation["quotation_id"],
        "rates": quotation["rates"],
        "destination": destination,
        "expires_at": time.time() + 24 * 60 * 60,
    }
    return jsonify({"provider": "Skydropx", "quotation_id": quotation["quotation_id"], "rates": quotation["rates"]})


@app.get("/pago/stripe/exito")
def stripe_success():
    session_id = request.args.get("session_id", "").strip()
    if not STRIPE_SECRET_KEY or not session_id:
        flash("No pudimos confirmar el pago de Stripe.", "error")
        return redirect(url_for("cart"))
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        stripe_session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        flash("No pudimos confirmar el pago de Stripe.", "error")
        return redirect(url_for("cart"))
    if stripe_session.get("payment_status") != "paid":
        flash("Stripe todavía no ha confirmado el pago.", "error")
        return redirect(url_for("cart"))
    try:
        order, should_notify = mark_stripe_order_paid(stripe_session)
    except Exception:
        # El cobro puede estar confirmado aunque falle una tarea secundaria
        # (por ejemplo, una cotización de envío o una notificación). No
        # devolvemos una página 500: dejamos el pedido pendiente de revisión
        # y mostramos una ruta clara para continuar.
        app.logger.exception("No se pudo completar el cierre del pedido después del pago de Stripe.")
        flash("El pago fue recibido, pero estamos terminando de preparar tu pedido. Escríbenos por WhatsApp para confirmar el folio.", "success")
        fallback_order_id = request.args.get("order_id", "")
        fallback_message = quote(
            f"Hola, mi pedido #{fallback_order_id} fue pagado y quiero confirmar el folio."
        )
        fallback_whatsapp = (
            f"https://wa.me/{WHATSAPP_NUMBER}?text={fallback_message}"
            if WHATSAPP_NUMBER else ""
        )
        return render_template(
            "order_ready.html", whatsapp_url=fallback_whatsapp, order_id=fallback_order_id,
            delivery_method="envio", is_local_delivery=False, payment_method="stripe",
            payment_url="", payment_confirmed=True,
            customer_email=session.get("user_email", ""), shipping_fee=0, shipping_carrier="",
            shipping_label_url="",
        ), 200
    if not order:
        flash("No encontramos el pedido asociado al pago.", "error")
        return redirect(url_for("index"))
    if should_notify:
        try:
            notify_paid_order(order, "stripe")
        except Exception:
            app.logger.exception("El pago del pedido #%s se confirmó, pero falló el proceso de notificaciones.", order.get("id"))
    whatsapp_url = ""
    if WHATSAPP_NUMBER:
        payment_message = quote(f"Hola, mi pedido #{order['id']} ya fue pagado con Stripe.")
        whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={payment_message}"
    return render_template(
        "order_ready.html", whatsapp_url=whatsapp_url, order_id=order["id"],
        delivery_method=order.get("delivery_method", "envio"),
        is_local_delivery=order.get("delivery_method") == "local",
        payment_method="stripe", payment_url="",
        payment_confirmed=True, customer_email=order.get("customer_email", ""),
        shipping_fee=order.get("shipping_fee", 0), shipping_carrier=order.get("shipping_carrier", ""),
        shipping_label_url=order.get("shipping_label_url", ""),
        order_lines=get_order_lines(order),
    )


@app.get("/pago/stripe/cancelado")
def stripe_cancelled():
    try:
        order_id = int(request.args.get("order_id", "0"))
    except (TypeError, ValueError):
        order_id = 0
    # Returning from Stripe does not prove that the Checkout Session expired.
    # Keep its reservation until the signed expiration webhook confirms it.
    return render_template("stripe_cancelled.html", order_id=order_id)


@app.post("/webhooks/stripe")
def stripe_webhook():
    if not STRIPE_WEBHOOK_SECRET:
        return "Stripe webhook no configurado", 503
    try:
        import stripe
        payload = request.get_data(as_text=True)
        event = stripe.Webhook.construct_event(
            payload, request.headers.get("Stripe-Signature", ""), STRIPE_WEBHOOK_SECRET
        )
    except ImportError:
        return "Stripe no instalado", 503
    except Exception:
        return "Firma de Stripe no válida", 400
    event_type = event.get("type", "")
    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        session_object = event.get("data", {}).get("object", {})
        if event_type == "checkout.session.completed" and session_object.get("payment_status") not in {"paid", "no_payment_required"}:
            return "", 200
        order, should_notify = mark_stripe_order_paid(session_object)
        if order and should_notify:
            try:
                notify_paid_order(order, "stripe")
            except Exception:
                app.logger.exception("El pago del pedido #%s se confirmó, pero falló el proceso de notificaciones.", order.get("id"))
    elif event_type == "checkout.session.expired":
        session_object = event.get("data", {}).get("object", {})
        metadata = session_object.get("metadata", {}) if isinstance(session_object, dict) else {}
        order_id = metadata.get("order_id") or (session_object.get("client_reference_id") if isinstance(session_object, dict) else "")
        try:
            order_id = int(order_id)
            with closing(get_users_db()) as db:
                order_row = db.execute("SELECT auction_id FROM orders WHERE id = ?", (order_id,)).fetchone()
            if order_row and int(order_row["auction_id"] or 0):
                # Auction offers last three days; renew the 24-hour Stripe link
                # while the offer is still valid, then release it at the deadline.
                finalize_closed_auctions()
            else:
                restore_order_stock(order_id)
        except (TypeError, ValueError):
            pass
    return "", 200


@app.post("/pedido")
def place_order():
    items, total = cart_details()
    coupon = get_coupon(session.get("coupon_code"))
    discount = calculate_coupon_discount(coupon, total)
    if coupon and not coupon_status(coupon)[0]:
        session.pop("coupon_code", None)
        coupon = None
        discount = 0
    if not items:
        flash("Tu carrito está vacío.", "error")
        return redirect(url_for("index"))
    if request.form.get("legal_accepted") != "1":
        flash("Debes aceptar los términos de compra y el aviso de privacidad para continuar.", "error")
        return redirect(url_for("checkout"))

    name = request.form.get("nombre", "").strip()
    customer_email = request.form.get("correo", "").strip().lower() or session.get("user_email", "")
    if coupon and not coupon_available_for_customer(
        coupon, customer_email, session.get("user_id")
    ):
        session.pop("coupon_code", None)
        flash("El código BIENVENIDO10 solo es válido en la primera compra.", "error")
        return redirect(url_for("cart"))
    phone = request.form.get("telefono", "").strip()
    address = request.form.get("direccion", "").strip()
    neighborhood = request.form.get("colonia", "").strip()
    city = request.form.get("ciudad", "").strip()
    state = request.form.get("estado", "").strip()
    postal_code = request.form.get("codigo_postal", "").strip()[:5]
    delivery_method = request.form.get("metodo_entrega", "envio").strip().lower()
    payment_method = "stripe"
    is_mexicali = is_mexicali_postal_code(postal_code)
    # El código postal decide el método para evitar una selección incorrecta.
    delivery_method = "local" if is_mexicali else "envio"
    if not STRIPE_SECRET_KEY:
        flash("El pago con Stripe todavía no está configurado. Inténtalo más tarde.", "error")
        return redirect(url_for("cart"))
    if not re.fullmatch(r"[0-9]{5}", postal_code):
        flash("Ingresa un código postal válido de 5 números.", "error")
        return redirect(url_for("cart"))
    if not all((name, customer_email, phone, address, neighborhood, city, state, postal_code)) or not is_valid_email(customer_email):
        flash("Completa todos tus datos de entrega para preparar el pedido.", "error")
        return redirect(url_for("cart"))

    destination = {
        "address": address,
        "neighborhood": neighborhood,
        "city": city,
        "state": state,
        "postal_code": postal_code,
    }
    selected_rate_id = request.form.get("skydropx_rate_id", "").strip()
    selected_rate = None
    saved_quote = session.get("skydropx_quote", {})
    if delivery_method != "local" and selected_rate_id and isinstance(saved_quote, dict):
        saved_destination = saved_quote.get("destination") if isinstance(saved_quote.get("destination"), dict) else {}
        same_destination = all(
            str(saved_destination.get(field, "")).strip().casefold() == str(destination[field]).strip().casefold()
            for field in destination
        )
        if float(saved_quote.get("expires_at", 0) or 0) > time.time() and same_destination:
            selected_rate = next(
                (rate for rate in saved_quote.get("rates", [])
                 if isinstance(rate, dict) and str(rate.get("id", "")) == selected_rate_id),
                None,
            )
    selected_quote_id = ""
    if selected_rate and isinstance(saved_quote, dict):
        selected_quote_id = str(saved_quote.get("quotation_id", "")).strip()[:120]
    if delivery_method == "local":
        shipping_fee = 0
        shipping_carrier = "Entrega personal"
        shipping_note = "Entrega personal el mismo día en Mexicali"
    elif selected_rate:
        shipping_fee = max(float(selected_rate.get("price", SHIPPING_ESTIMATE) or SHIPPING_ESTIMATE), 0)
        shipping_carrier = str(selected_rate.get("carrier") or "Skydropx")[:100]
        shipping_note = str(selected_rate.get("service") or "Tarifa cotizada con Skydropx")[:240]
    else:
        # El servidor vuelve a cotizar si el navegador no pudo conservar la
        # tarifa seleccionada. Así el pedido nunca cobra un estimado cuando
        # Skydropx está activo y la guía siempre recibe un rate_id válido.
        if delivery_method != "local" and skydropx_is_configured():
            try:
                quotation = skydropx_quote(items, destination)
                rates = [rate for rate in quotation.get("rates", []) if isinstance(rate, dict)]
                selected_rate = min(rates, key=lambda rate: float(rate.get("price", 0) or 0)) if rates else None
            except Exception as error:
                flash(f"No pudimos calcular el costo exacto del envío: {error}", "error")
                return redirect(url_for("checkout"))
            if not selected_rate or not str(selected_rate.get("id", "")).strip():
                flash("Skydropx no devolvió una tarifa válida para ese destino.", "error")
                return redirect(url_for("checkout"))
            selected_rate_id = str(selected_rate.get("id", "")).strip()[:120]
            selected_quote_id = str(quotation.get("quotation_id", "")).strip()[:120]
            session["skydropx_quote"] = {
                "quotation_id": selected_quote_id,
                "rates": rates,
                "destination": destination,
                "expires_at": time.time() + 24 * 60 * 60,
            }
            shipping_fee = max(float(selected_rate.get("price", 0) or 0), 0)
            shipping_carrier = str(selected_rate.get("carrier") or "Skydropx")[:100]
            shipping_note = str(selected_rate.get("service") or "Tarifa cotizada con Skydropx")[:240]
        else:
            shipping_fee = SHIPPING_ESTIMATE
            shipping_carrier = "Skydropx"
            shipping_note = "Envío estimado; cotización detallada pendiente"
    order_total = max(total - discount, 0) + shipping_fee
    release_expired_stock_reservations()
    reserved, unavailable_product = reserve_order_stock(items)
    if not reserved:
        flash(f"No hay suficientes existencias de {unavailable_product}.", "error")
        return redirect(url_for("cart"))

    order_lines = []
    order_line_records = []
    for item in items:
        product = item["product"]
        sections_label = " y ".join(get_product_sections(product))
        specifications = []
        if product.get("bat_measure") and product.get("bat_weight"):
            specifications.append(f"medida {product['bat_measure']} in, peso {product['bat_weight']}")
        if product.get("glove_measure"):
            specifications.append(f"medida de guante {product['glove_measure']} in")
        if product.get("guantaleta_size"):
            specifications.append(f"talla de guantaleta {product['guantaleta_size']}")
        if product.get("grip_thickness"):
            specifications.append(f"grosor {product['grip_thickness']}")
        customizations = item.get("customizations", {})
        specifications.extend(f"{label.lower()}: {value}" for label, value in customizations.items())
        specification_text = f" ({'; '.join(specifications)})" if specifications else ""
        order_lines.append(
            f"- {item['quantity']} x {product['name']} [{product['category']} / {sections_label}]"
            f"{specification_text} ({format_mxn(item['subtotal'])} MXN)"
        )
        order_line_records.append({
            "product_id": product["id"],
            "name": product["name"],
            "category": product.get("category", ""),
            "customizable": bool(product.get("customizable")),
            "quantity": item["quantity"],
            "unit_price": product["price"],
            "subtotal": item["subtotal"],
            "description": product.get("description", ""),
            "customizations": customizations,
            "custom_image": item.get("custom_image", ""),
        })

    initial_status = "Pago pendiente" if payment_method == "stripe" else "Pendiente"
    reservation_expires = (datetime.now() + timedelta(hours=24)).isoformat(timespec="minutes")
    with closing(get_users_db()) as db:
        if session.get("user_id"):
            db.execute(
                """UPDATE users SET name = ?, phone = ?, address = ?, neighborhood = ?,
                   city = ?, state = ?, postal_code = ? WHERE id = ?""",
                (name, phone, address, neighborhood, city, state, postal_code, session["user_id"]),
            )
        cursor = db.execute(
            """INSERT INTO orders
               (user_id, customer_name, customer_email, phone, address, neighborhood, city, state,
                postal_code, delivery_method, payment_method, lines_json, total, status,
                discount, coupon_code, shipping_fee, shipping_carrier, shipping_rate_id,
                shipping_quote_id, shipping_note, stock_reserved_until, stock_released)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.get("user_id"), name, customer_email, phone, address, neighborhood,
                city, state, postal_code, delivery_method, payment_method,
                json.dumps(order_line_records, ensure_ascii=False), order_total, initial_status,
                discount, coupon.get("code", "") if coupon else "", shipping_fee,
                shipping_carrier, selected_rate_id[:120] if selected_rate else "",
                selected_quote_id, shipping_note,
                reservation_expires, 0,
            ),
        )
        order_id = cursor.lastrowid
        db.execute(
            "UPDATE orders SET purchase_terms_version = ?, privacy_notice_version = ?, legal_accepted_at = ? WHERE id = ?",
            (PURCHASE_TERMS_VERSION, PRIVACY_NOTICE_VERSION,
             datetime.now().isoformat(timespec="seconds"), order_id),
        )
        db.commit()

    if payment_method == "stripe":
        try:
            stripe_session = create_stripe_checkout_session(
                order_id, customer_email, order_line_records, total, shipping_fee, discount,
                selected_rate_id if selected_rate else "", selected_quote_id,
            )
        except Exception as error:
            restore_order_stock(order_id)
            flash(str(error), "error")
            return redirect(url_for("cart"))
        with closing(get_users_db()) as db:
            db.execute(
                "UPDATE orders SET stripe_session_id = ? WHERE id = ?",
                (stripe_session.get("id", ""), order_id),
            )
            db.commit()
        session["cart"] = {}
        session.pop("skydropx_quote", None)
        return redirect(stripe_session.url)
    message = "\n".join(
        [
            "Hola, quiero hacer este pedido en FR BEISSHOP:",
            *order_lines,
            f"Total de productos: {format_mxn(total)} MXN",
            f"Pago preferido: {payment_method}",
            f"Nombre: {name}",
            f"Teléfono: {phone}",
            f"Dirección: {address}, colonia {neighborhood}",
            f"Destino: {city}, {state}, C.P. {postal_code}",
            "Entrega: entrega personal el mismo día en Mexicali" if delivery_method == "local" else "Entrega: envío a domicilio; confirmar costo y tiempo según el código postal",
            "¿Me pueden confirmar el costo y tiempo de envío para este código postal?",
            "También quisiera conocer las formas de pago disponibles antes de confirmar.",
        ]
    )
    whatsapp_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(message)}" if WHATSAPP_NUMBER else ""
    session["cart"] = {}
    send_order_confirmation(order_id, customer_email, name, order_total, order_line_records, payment_method)
    return render_template(
        "order_ready.html", whatsapp_url=whatsapp_url, order_id=order_id,
        delivery_method=delivery_method, is_local_delivery=delivery_method == "local",
        payment_method=payment_method, payment_url="", customer_email=customer_email,
        shipping_fee=shipping_fee, shipping_carrier=shipping_carrier,
        order_lines=order_line_records,
    )


def auction_notification_worker():
    """Run auction email deadlines in the local single-process server."""
    while True:
        time.sleep(60)
        try:
            with app.app_context():
                finalize_closed_auctions()
        except Exception:
            app.logger.exception("No se pudo procesar una notificación de subasta.")


if __name__ == "__main__":
    if os.environ.get("FLASK_DEBUG", "0").strip().lower() not in {"1", "true", "yes"}:
        threading.Thread(target=auction_notification_worker, name="auction-notifications", daemon=True).start()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")







