#!/usr/bin/env python3
"""Scraper/exportador simple para busquedas de Mercado Libre.

Usa endpoints publicos de Mercado Libre para obtener resultados de busqueda y
guardarlos en CSV o JSON. No requiere dependencias externas.
"""

from __future__ import annotations

import argparse
import csv
import html
import os
import re
import json
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen


API_BASE = "https://api.mercadolibre.com"
DEFAULT_SITE = "MLA"
MAX_PAGE_SIZE = 50


@dataclass(frozen=True)
class SearchOptions:
    query: str
    site: str
    limit: int
    mode: str
    token: str | None
    condition: str | None
    min_price: Decimal | None
    max_price: Decimal | None
    free_shipping: bool
    include_details: bool
    delay: float


def parse_price(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"Precio invalido: {value}") from exc


def request_url(url: str, token: str | None = None, retries: int = 3) -> bytes:
    headers = {
        "Accept": "text/html,application/json",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)
    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=25) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            detail = f": {body}" if body else ""
            raise RuntimeError(f"Error HTTP {exc.code} consultando {url}{detail}") from exc
        except URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            raise RuntimeError(f"No se pudo consultar {url}: {exc.reason}") from exc

    raise RuntimeError(f"No se pudo consultar {url}")


def request_json(
    path: str,
    params: dict[str, Any] | None = None,
    token: str | None = None,
    retries: int = 3,
) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return json.loads(request_url(url, token=token, retries=retries).decode("utf-8"))


def post_form_json(path: str, data: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    body = urlencode(data).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "scraper-meli-local/1.0",
    }
    request = Request(url, data=body, headers=headers, method="POST")

    for attempt in range(1, retries + 1):
        try:
            with urlopen(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            detail = f": {body_text}" if body_text else ""
            raise RuntimeError(f"Error HTTP {exc.code} consultando {url}{detail}") from exc
        except URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            raise RuntimeError(f"No se pudo consultar {url}: {exc.reason}") from exc

    raise RuntimeError(f"No se pudo consultar {url}")


def exchange_authorization_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    return post_form_json(
        "/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict[str, Any]:
    return post_form_json(
        "/oauth/token",
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )


def build_search_params(options: SearchOptions, offset: int, page_size: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": options.query,
        "offset": offset,
        "limit": page_size,
    }
    if options.condition:
        params["condition"] = options.condition
    if options.min_price is not None or options.max_price is not None:
        low = "" if options.min_price is None else str(options.min_price)
        high = "" if options.max_price is None else str(options.max_price)
        params["price"] = f"{low}-{high}"
    if options.free_shipping:
        params["shipping_cost"] = "free"
    return params


def fetch_search_results(options: SearchOptions) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0

    while len(items) < options.limit:
        page_size = min(MAX_PAGE_SIZE, options.limit - len(items))
        params = build_search_params(options, offset, page_size)
        try:
            payload = request_json(f"/sites/{options.site}/search", params, token=options.token)
        except RuntimeError as exc:
            if options.token and "Error HTTP 403" in str(exc):
                payload = request_json(f"/sites/{options.site}/search", params)
            else:
                raise
        results = payload.get("results", [])
        if not results:
            break

        for item in results:
            items.append(item)
            if len(items) >= options.limit:
                break

        offset += len(results)
        paging = payload.get("paging", {})
        total = int(paging.get("total", 0) or 0)
        if offset >= total:
            break
        if options.delay:
            time.sleep(options.delay)

    return items


def fetch_item_details(item_id: str, delay: float, token: str | None = None) -> dict[str, Any]:
    if delay:
        time.sleep(delay)
    return request_json(f"/items/{item_id}", token=token)


def site_domain(site: str) -> str:
    domains = {
        "MLA": "mercadolibre.com.ar",
        "MLB": "mercadolivre.com.br",
        "MLM": "mercadolibre.com.mx",
        "MLC": "mercadolibre.cl",
        "MCO": "mercadolibre.com.co",
        "MLU": "mercadolibre.com.uy",
        "MPE": "mercadolibre.com.pe",
    }
    return domains.get(site.upper(), "mercadolibre.com.ar")


def html_search_url(options: SearchOptions) -> str:
    url = f"https://listado.{site_domain(options.site)}/{quote_plus(options.query).replace('+', '-')}"
    params: dict[str, Any] = {}
    if options.condition:
        params["ITEM_CONDITION"] = "2230284" if options.condition == "new" else "2230581"
    if options.min_price is not None or options.max_price is not None:
        low = "" if options.min_price is None else str(options.min_price)
        high = "" if options.max_price is None else str(options.max_price)
        params["price"] = f"{low}-{high}"
    if options.free_shipping:
        params["shipping_cost"] = "free"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def decode_html_entities(value: str) -> str:
    return html.unescape(value).strip()


def extract_json_ld_items(document: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(document):
        raw_json = decode_html_entities(match.group(1))
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            item_list = candidate.get("itemListElement") or []
            for entry in item_list:
                item = entry.get("item") if isinstance(entry, dict) else None
                if not isinstance(item, dict):
                    continue
                offers = item.get("offers") or {}
                rows.append(
                    {
                        "id": "",
                        "title": item.get("name", ""),
                        "price": offers.get("price", ""),
                        "currency_id": offers.get("priceCurrency", ""),
                        "condition": "",
                        "available_quantity": "",
                        "sold_quantity": "",
                        "permalink": item.get("url", ""),
                        "thumbnail": item.get("image", ""),
                        "seller_id": "",
                        "seller": "",
                        "category_id": "",
                        "official_store_id": "",
                        "listing_type_id": "",
                        "accepts_mercadopago": "",
                        "free_shipping": "",
                        "shipping_mode": "",
                        "installments_quantity": "",
                        "installments_amount": "",
                        "state": "",
                        "city": "",
                        "attributes": "{}",
                    }
                )
    return rows


def extract_regex_items(document: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    card_pattern = re.compile(
        r'<li[^>]+class=["\'][^"\']*ui-search-layout__item[^"\']*["\'][^>]*>(.*?)</li>',
        re.IGNORECASE | re.DOTALL,
    )
    for card in card_pattern.findall(document):
        link_match = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', card, re.IGNORECASE)
        title_match = re.search(
            r'class=["\'][^"\']*ui-search-item__title[^"\']*["\'][^>]*>(.*?)</',
            card,
            re.IGNORECASE | re.DOTALL,
        )
        price_fraction = re.search(
            r'class=["\'][^"\']*andes-money-amount__fraction[^"\']*["\'][^>]*>(.*?)</',
            card,
            re.IGNORECASE | re.DOTALL,
        )
        if not link_match or not title_match:
            continue
        rows.append(
            {
                "id": "",
                "title": decode_html_entities(re.sub(r"<.*?>", "", title_match.group(1))),
                "price": decode_html_entities(re.sub(r"<.*?>", "", price_fraction.group(1))) if price_fraction else "",
                "currency_id": "",
                "condition": "",
                "available_quantity": "",
                "sold_quantity": "",
                "permalink": decode_html_entities(link_match.group(1)),
                "thumbnail": "",
                "seller_id": "",
                "seller": "",
                "category_id": "",
                "official_store_id": "",
                "listing_type_id": "",
                "accepts_mercadopago": "",
                "free_shipping": "Envio gratis" in decode_html_entities(card),
                "shipping_mode": "",
                "installments_quantity": "",
                "installments_amount": "",
                "state": "",
                "city": "",
                "attributes": "{}",
            }
        )
    return rows


def fetch_html_results(options: SearchOptions) -> list[dict[str, Any]]:
    document = request_url(html_search_url(options)).decode("utf-8", errors="replace")
    if "suspicious-traffic" in document or "captcha" in document.lower():
        raise RuntimeError(
            "Mercado Libre devolvio una pagina de verificacion en vez de resultados. "
            "Esto suele pasar por bloqueo anti-bot del hosting o de la IP."
        )
    rows = extract_json_ld_items(document)
    if not rows:
        rows = extract_regex_items(document)
    return rows[: options.limit]


def get_seller_name(item: dict[str, Any]) -> str:
    seller = item.get("seller") or {}
    return str(seller.get("nickname") or seller.get("id") or "")


def get_seller_id(item: dict[str, Any]) -> str:
    seller = item.get("seller") or {}
    return str(seller.get("id") or "")


def get_first_picture(item: dict[str, Any]) -> str:
    thumbnail = item.get("thumbnail")
    if thumbnail:
        return str(thumbnail)
    pictures = item.get("pictures") or []
    if pictures:
        return str((pictures[0] or {}).get("url") or "")
    return ""


def normalize_item(item: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    source = detail or item
    shipping = source.get("shipping") or {}
    installments = source.get("installments") or {}
    address = source.get("address") or {}

    attributes = {}
    for attr in source.get("attributes") or []:
        name = attr.get("name")
        value = attr.get("value_name")
        if name and value:
            attributes[name] = value

    return {
        "id": source.get("id", item.get("id", "")),
        "title": source.get("title", item.get("title", "")),
        "price": source.get("price", item.get("price", "")),
        "currency_id": source.get("currency_id", item.get("currency_id", "")),
        "condition": source.get("condition", item.get("condition", "")),
        "available_quantity": source.get("available_quantity", item.get("available_quantity", "")),
        "sold_quantity": source.get("sold_quantity", item.get("sold_quantity", "")),
        "permalink": source.get("permalink", item.get("permalink", "")),
        "thumbnail": get_first_picture(source),
        "seller_id": get_seller_id(source),
        "seller": get_seller_name(source),
        "category_id": source.get("category_id", item.get("category_id", "")),
        "official_store_id": source.get("official_store_id", item.get("official_store_id", "")),
        "listing_type_id": source.get("listing_type_id", item.get("listing_type_id", "")),
        "accepts_mercadopago": source.get("accepts_mercadopago", item.get("accepts_mercadopago", "")),
        "free_shipping": shipping.get("free_shipping", ""),
        "shipping_mode": shipping.get("mode", ""),
        "installments_quantity": installments.get("quantity", ""),
        "installments_amount": installments.get("amount", ""),
        "state": address.get("state_name", ""),
        "city": address.get("city_name", ""),
        "attributes": json.dumps(attributes, ensure_ascii=False),
    }


def enrich_items(
    items: list[dict[str, Any]],
    include_details: bool,
    delay: float,
    token: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        detail = None
        if include_details and item.get("id"):
            try:
                detail = fetch_item_details(str(item["id"]), delay, token=token)
            except RuntimeError as exc:
                print(f"Aviso: no se pudo traer detalle de {item['id']}: {exc}", file=sys.stderr)
        rows.append(normalize_item(item, detail))
        print(f"{index}/{len(items)} {item.get('id', '')} {item.get('title', '')}", file=sys.stderr)
    return rows


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else list(normalize_item({}).keys())
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(rows, file, indent=2, ensure_ascii=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Busca publicaciones de Mercado Libre y exporta resultados.",
    )
    parser.add_argument("query", help="Busqueda, por ejemplo: notebook gamer")
    parser.add_argument("-o", "--output", default="resultados_meli.csv", help="Archivo de salida CSV o JSON")
    parser.add_argument("--format", choices=["csv", "json"], help="Formato de salida. Por defecto se infiere por extension")
    parser.add_argument("--site", default=DEFAULT_SITE, help="Sitio de Mercado Libre, por ejemplo MLA, MLB, MLM, MLC")
    parser.add_argument("--mode", choices=["auto", "api", "html"], default="auto", help="Fuente de datos")
    parser.add_argument("--token", help="Access token de Mercado Libre. Tambien puede usarse MELI_ACCESS_TOKEN")
    parser.add_argument("--limit", type=int, default=50, help="Cantidad maxima de resultados")
    parser.add_argument("--condition", choices=["new", "used"], help="Filtrar por condicion")
    parser.add_argument("--min-price", type=parse_price, help="Precio minimo")
    parser.add_argument("--max-price", type=parse_price, help="Precio maximo")
    parser.add_argument("--free-shipping", action="store_true", help="Solo publicaciones con envio gratis")
    parser.add_argument("--details", action="store_true", help="Traer detalle de cada publicacion")
    parser.add_argument("--delay", type=float, default=0.25, help="Pausa entre consultas para no saturar el servicio")
    return parser


def infer_format(output: Path, explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format
    if output.suffix.lower() == ".json":
        return "json"
    return "csv"


def run_search(options: SearchOptions) -> tuple[list[dict[str, Any]], str]:
    rows, source, _warning = run_search_detailed(options)
    return rows, source


def run_search_detailed(options: SearchOptions) -> tuple[list[dict[str, Any]], str, str]:
    if options.mode == "html":
        return fetch_html_results(options), "html", ""

    try:
        items = fetch_search_results(options)
        rows = enrich_items(items, options.include_details, options.delay, token=options.token)
        return rows, "api", ""
    except RuntimeError as api_error:
        if options.mode == "api":
            raise
        try:
            rows = fetch_html_results(options)
        except RuntimeError as html_error:
            raise RuntimeError(f"API fallo: {api_error}. Fallback HTML fallo: {html_error}") from html_error
        return rows, "html", f"API fallo: {api_error}. Se uso fallback HTML."


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit debe ser mayor a 0")
    if args.delay < 0:
        parser.error("--delay no puede ser negativo")
    if args.min_price is not None and args.max_price is not None and args.min_price > args.max_price:
        parser.error("--min-price no puede ser mayor que --max-price")

    options = SearchOptions(
        query=args.query,
        site=args.site.upper(),
        limit=args.limit,
        mode=args.mode,
        token=args.token or os.getenv("MELI_ACCESS_TOKEN"),
        condition=args.condition,
        min_price=args.min_price,
        max_price=args.max_price,
        free_shipping=args.free_shipping,
        include_details=args.details,
        delay=args.delay,
    )

    try:
        rows, source = run_search(options)
        if options.mode == "auto" and source == "html":
            print("Aviso: la API no respondio correctamente; se uso scraping HTML.", file=sys.stderr)
        output = Path(args.output)
        output_format = infer_format(output, args.format)
        if output_format == "json":
            write_json(rows, output)
        else:
            write_csv(rows, output)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Listo: {len(rows)} resultados guardados en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
