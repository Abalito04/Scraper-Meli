#!/usr/bin/env python3
"""Web app deployable para Railway."""

from __future__ import annotations

import csv
import io
import json
import os
import secrets
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from flask import Flask, Response, redirect, render_template_string, request, session, url_for

from scraper_meli import SearchOptions, exchange_authorization_code, refresh_access_token, run_search


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

USER_STATE: dict[str, dict[str, Any]] = {}

SITES = {
    "MLA": "Argentina",
    "MLB": "Brasil",
    "MLM": "Mexico",
    "MLC": "Chile",
    "MCO": "Colombia",
    "MLU": "Uruguay",
    "MPE": "Peru",
}

HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scraper Mercado Libre</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #182230;
      --muted: #667085;
      --border: #d7dde5;
      --blue: #3483fa;
      --blue-dark: #2968c8;
      --green: #067647;
      --red: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    main { max-width: 1240px; margin: 0 auto; padding: 28px 18px 44px; }
    header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; margin-bottom: 18px; }
    h1 { margin: 0; font-size: 30px; line-height: 1.15; }
    p { margin: 6px 0 0; color: var(--muted); }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(220px, 2fr) repeat(5, minmax(120px, 1fr));
      gap: 12px;
      align-items: end;
    }
    label { display: grid; gap: 6px; font-size: 13px; color: #344054; font-weight: 700; }
    input, select {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px;
      min-height: 40px;
      font-size: 14px;
      background: #fff;
      color: var(--text);
    }
    .checks { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
    .checks label { display: inline-flex; grid-auto-flow: column; align-items: center; gap: 6px; font-weight: 600; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; align-items: center; }
    button, .button {
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      background: var(--blue);
      color: white;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      min-height: 40px;
    }
    button:hover, .button:hover { background: var(--blue-dark); }
    .button.secondary, button.secondary { background: #eef4ff; color: #1849a9; }
    .button.secondary:hover, button.secondary:hover { background: #dbeafe; }
    .status {
      margin: 14px 0;
      padding: 10px 12px;
      border-radius: 6px;
      background: #eef4ff;
      color: #1849a9;
      font-weight: 700;
    }
    .status.error { background: #fef3f2; color: var(--red); }
    .status.ok { background: #ecfdf3; color: var(--green); }
    .toolbar { display: flex; gap: 10px; justify-content: space-between; align-items: center; margin: 16px 0 10px; }
    .table-wrap { overflow: auto; border: 1px solid var(--border); border-radius: 8px; background: #fff; }
    table { border-collapse: collapse; width: 100%; min-width: 1080px; }
    th, td { border-bottom: 1px solid #edf1f5; padding: 10px 9px; text-align: left; font-size: 13px; vertical-align: top; }
    th { background: #edf1f5; color: #344054; position: sticky; top: 0; }
    td a { color: #1849a9; font-weight: 700; }
    .muted { color: var(--muted); }
    .token { font-size: 13px; font-weight: 700; color: {{ '#067647' if connected else '#b42318' }}; }
    @media (max-width: 900px) {
      header { display: block; }
      .grid { grid-template-columns: 1fr; }
      .toolbar { display: block; }
      .toolbar .actions { margin-top: 10px; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Scraper Mercado Libre</h1>
      <p>Busca publicaciones, filtra resultados y exporta CSV o JSON.</p>
    </div>
    <div>
      <div class="token">{{ 'Cuenta conectada' if connected else 'Sin cuenta conectada' }}</div>
      <div class="actions">
        <a class="button secondary" href="{{ url_for('login') }}">Login Meli</a>
        {% if connected %}
          <a class="button secondary" href="{{ url_for('refresh') }}">Renovar token</a>
          <a class="button secondary" href="{{ url_for('logout') }}">Salir</a>
        {% endif %}
      </div>
    </div>
  </header>

  {% if message %}
    <div class="status {{ message_kind }}">{{ message }}</div>
  {% endif %}

  <section class="panel">
    <form method="post" action="{{ url_for('search') }}">
      <div class="grid">
        <label>Busqueda
          <input name="query" value="{{ form.query }}" placeholder="iphone 15" required>
        </label>
        <label>Pais
          <select name="site">
            {% for site_id, site_name in sites.items() %}
              <option value="{{ site_id }}" {% if form.site == site_id %}selected{% endif %}>{{ site_name }} ({{ site_id }})</option>
            {% endfor %}
          </select>
        </label>
        <label>Modo
          <select name="mode">
            {% for mode in ['auto', 'api', 'html'] %}
              <option value="{{ mode }}" {% if form.mode == mode %}selected{% endif %}>{{ mode }}</option>
            {% endfor %}
          </select>
        </label>
        <label>Limite
          <input name="limit" type="number" min="1" max="500" value="{{ form.limit }}">
        </label>
        <label>Precio min.
          <input name="min_price" value="{{ form.min_price }}">
        </label>
        <label>Precio max.
          <input name="max_price" value="{{ form.max_price }}">
        </label>
      </div>
      <div class="actions">
        <label>Condicion
          <select name="condition">
            <option value="" {% if not form.condition %}selected{% endif %}>Todas</option>
            <option value="new" {% if form.condition == 'new' %}selected{% endif %}>Nuevo</option>
            <option value="used" {% if form.condition == 'used' %}selected{% endif %}>Usado</option>
          </select>
        </label>
        <div class="checks">
          <label><input type="checkbox" name="free_shipping" {% if form.free_shipping %}checked{% endif %}> Envio gratis</label>
          <label><input type="checkbox" name="details" {% if form.details %}checked{% endif %}> Traer detalle</label>
        </div>
        <button type="submit">Buscar</button>
      </div>
    </form>
  </section>

  <div class="toolbar">
    <div class="muted">{{ rows|length }} resultados{% if source %} · fuente {{ source|upper }}{% endif %}</div>
    <div class="actions">
      <a class="button secondary" href="{{ url_for('export', output_format='csv') }}">Exportar CSV</a>
      <a class="button secondary" href="{{ url_for('export', output_format='json') }}">Exportar JSON</a>
    </div>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Titulo</th>
          <th>Precio</th>
          <th>Moneda</th>
          <th>Condicion</th>
          <th>Vendedor</th>
          <th>Vendidos</th>
          <th>Envio</th>
          <th>Ubicacion</th>
          <th>Link</th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr>
            <td>{{ row.title }}</td>
            <td>{{ row.price }}</td>
            <td>{{ row.currency_id }}</td>
            <td>{{ row.condition }}</td>
            <td>{{ row.seller }}</td>
            <td>{{ row.sold_quantity }}</td>
            <td>{{ 'Gratis' if row.free_shipping in [true, 'True', 'true', 'Si'] else '' }}</td>
            <td>{{ row.state }} {{ row.city }}</td>
            <td>{% if row.permalink %}<a href="{{ row.permalink }}" target="_blank" rel="noreferrer">Abrir</a>{% endif %}</td>
          </tr>
        {% else %}
          <tr><td colspan="9" class="muted">Todavia no hay resultados.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</main>
</body>
</html>
"""


def get_state() -> dict[str, Any]:
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(24)
        session["sid"] = sid
    return USER_STATE.setdefault(
        sid,
        {
            "rows": [],
            "source": "",
            "access_token": os.getenv("MELI_ACCESS_TOKEN", ""),
            "refresh_token": "",
            "form": default_form(),
        },
    )


def default_form() -> dict[str, Any]:
    return {
        "query": "",
        "site": "MLA",
        "mode": "auto",
        "limit": "50",
        "condition": "",
        "min_price": "",
        "max_price": "",
        "free_shipping": False,
        "details": False,
    }


def parse_decimal(value: str, label: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} debe ser un numero valido.") from exc


def build_options(form: dict[str, Any], token: str | None) -> SearchOptions:
    query = str(form["query"]).strip()
    if not query:
        raise ValueError("Escribi una busqueda.")
    limit = int(form["limit"])
    if limit < 1:
        raise ValueError("El limite debe ser mayor a 0.")
    min_price = parse_decimal(str(form["min_price"]), "Precio minimo")
    max_price = parse_decimal(str(form["max_price"]), "Precio maximo")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("El precio minimo no puede ser mayor al maximo.")
    return SearchOptions(
        query=query,
        site=str(form["site"]),
        limit=limit,
        mode=str(form["mode"]),
        token=token,
        condition=str(form["condition"]) or None,
        min_price=min_price,
        max_price=max_price,
        free_shipping=bool(form["free_shipping"]),
        include_details=bool(form["details"]),
        delay=0.25,
    )


def request_form() -> dict[str, Any]:
    form = default_form()
    form.update(
        {
            "query": request.form.get("query", "").strip(),
            "site": request.form.get("site", "MLA"),
            "mode": request.form.get("mode", "auto"),
            "limit": request.form.get("limit", "50"),
            "condition": request.form.get("condition", ""),
            "min_price": request.form.get("min_price", ""),
            "max_price": request.form.get("max_price", ""),
            "free_shipping": "free_shipping" in request.form,
            "details": "details" in request.form,
        }
    )
    return form


def render(message: str = "", message_kind: str = "") -> str:
    state = get_state()
    return render_template_string(
        HTML,
        rows=state["rows"],
        source=state["source"],
        sites=SITES,
        form=state["form"],
        connected=bool(state.get("access_token")),
        message=message,
        message_kind=message_kind,
    )


def public_base_url() -> str:
    configured = os.getenv("MELI_REDIRECT_URI", "")
    if configured:
        return configured.rsplit("/callback", 1)[0].rstrip("/")
    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if railway_domain:
        return f"https://{railway_domain}".rstrip("/")
    return request.url_root.rstrip("/")


def redirect_uri() -> str:
    configured = os.getenv("MELI_REDIRECT_URI", "")
    if configured:
        return configured
    return f"{public_base_url()}/callback"


@app.get("/")
def index() -> str:
    return render()


@app.post("/search")
def search() -> str:
    state = get_state()
    form = request_form()
    state["form"] = form
    try:
        options = build_options(form, state.get("access_token") or None)
        rows, source = run_search(options)
        state["rows"] = rows
        state["source"] = source
    except Exception as exc:
        return render(str(exc), "error")
    return render(f"{len(state['rows'])} resultados cargados.", "ok")


@app.get("/login")
def login() -> Response:
    client_id = os.getenv("MELI_CLIENT_ID", "")
    if not client_id:
        return Response("Falta configurar MELI_CLIENT_ID en Railway.", status=500)
    state_value = secrets.token_urlsafe(24)
    session["oauth_state"] = state_value
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "state": state_value,
    }
    return redirect(f"https://auth.mercadolibre.com.ar/authorization?{urlencode(params)}")


@app.get("/callback")
def callback() -> str:
    expected_state = session.get("oauth_state")
    received_state = request.args.get("state")
    if expected_state and received_state != expected_state:
        return render("El estado OAuth no coincide. Volve a intentar el login.", "error")
    if request.args.get("error"):
        return render(f"Mercado Libre rechazo el login: {request.args['error']}", "error")

    code = request.args.get("code", "")
    client_id = os.getenv("MELI_CLIENT_ID", "")
    client_secret = os.getenv("MELI_CLIENT_SECRET", "")
    if not code or not client_id or not client_secret:
        return render("Faltan datos para completar el login.", "error")

    try:
        token_data = exchange_authorization_code(client_id, client_secret, code, redirect_uri())
    except Exception as exc:
        return render(str(exc), "error")

    state = get_state()
    state["access_token"] = str(token_data.get("access_token") or "")
    state["refresh_token"] = str(token_data.get("refresh_token") or "")
    return render("Cuenta conectada correctamente.", "ok")


@app.get("/refresh")
def refresh() -> str:
    state = get_state()
    refresh_token_value = state.get("refresh_token") or os.getenv("MELI_REFRESH_TOKEN", "")
    client_id = os.getenv("MELI_CLIENT_ID", "")
    client_secret = os.getenv("MELI_CLIENT_SECRET", "")
    if not client_id or not client_secret or not refresh_token_value:
        return render("Falta refresh token o credenciales para renovar.", "error")
    try:
        token_data = refresh_access_token(client_id, client_secret, refresh_token_value)
    except Exception as exc:
        return render(str(exc), "error")
    state["access_token"] = str(token_data.get("access_token") or "")
    state["refresh_token"] = str(token_data.get("refresh_token") or refresh_token_value)
    return render("Token renovado correctamente.", "ok")


@app.get("/logout")
def logout() -> Response:
    state = get_state()
    state["access_token"] = ""
    state["refresh_token"] = ""
    return redirect(url_for("index"))


@app.get("/export/<output_format>")
def export(output_format: str) -> Response:
    state = get_state()
    rows = state.get("rows") or []
    if output_format == "json":
        payload = json.dumps(rows, indent=2, ensure_ascii=False)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=resultados_meli.json"},
        )

    output = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else []
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    if fieldnames:
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=resultados_meli.csv"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
