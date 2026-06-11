#!/usr/bin/env python3
"""Interfaz grafica para el scraper de Mercado Libre."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from scraper_meli import SearchOptions, exchange_authorization_code, refresh_access_token, run_search, write_csv, write_json


SITES = {
    "Argentina (MLA)": "MLA",
    "Brasil (MLB)": "MLB",
    "Mexico (MLM)": "MLM",
    "Chile (MLC)": "MLC",
    "Colombia (MCO)": "MCO",
    "Uruguay (MLU)": "MLU",
    "Peru (MPE)": "MPE",
}

COLUMNS = [
    ("title", "Titulo", 360),
    ("price", "Precio", 95),
    ("currency_id", "Moneda", 70),
    ("condition", "Condicion", 85),
    ("seller", "Vendedor", 150),
    ("sold_quantity", "Vendidos", 80),
    ("free_shipping", "Envio gratis", 95),
    ("state", "Provincia", 120),
    ("city", "Ciudad", 120),
    ("permalink", "Link", 280),
]


class MeliScraperApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Scraper Mercado Libre")
        self.geometry("1180x720")
        self.minsize(940, 620)

        self.rows: list[dict[str, Any]] = []
        self.result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.auth_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.query_var = tk.StringVar()
        self.site_var = tk.StringVar(value="Argentina (MLA)")
        self.mode_var = tk.StringVar(value="auto")
        self.limit_var = tk.StringVar(value="50")
        self.condition_var = tk.StringVar(value="Todas")
        self.min_price_var = tk.StringVar()
        self.max_price_var = tk.StringVar()
        self.token_var = tk.StringVar(value=os.getenv("MELI_ACCESS_TOKEN", ""))
        self.refresh_token_var = tk.StringVar()
        self.client_id_var = tk.StringVar()
        self.client_secret_var = tk.StringVar()
        self.redirect_uri_var = tk.StringVar(value="http://localhost:8080/callback")
        self.free_shipping_var = tk.BooleanVar(value=False)
        self.details_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Listo para buscar.")

        self.configure(bg="#f4f6f8")
        self._configure_style()
        self._build_layout()
        self.after(120, self._poll_queue)
        self.after(160, self._poll_auth_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6f8")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabel", background="#f4f6f8", foreground="#202124", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background="#ffffff")
        style.configure("Title.TLabel", background="#f4f6f8", foreground="#111827", font=("Segoe UI", 18, "bold"))
        style.configure("Muted.TLabel", background="#f4f6f8", foreground="#5f6b7a", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7))
        style.configure("Primary.TButton", background="#3483fa", foreground="#ffffff", borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#2968c8"), ("disabled", "#9bbff8")])
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 9), background="#ffffff", fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#edf1f5", foreground="#344054")

    def _build_layout(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=tk.X, pady=(0, 14))
        ttk.Label(header, text="Scraper Mercado Libre", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Busca publicaciones, revisa los resultados y exportalos en CSV o JSON.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(3, 0))

        form = ttk.Frame(root, style="Panel.TFrame", padding=16)
        form.pack(fill=tk.X)
        for index in range(8):
            form.columnconfigure(index, weight=1)

        self._label(form, "Busqueda", 0, 0)
        query_entry = ttk.Entry(form, textvariable=self.query_var, font=("Segoe UI", 11))
        query_entry.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(0, 10), pady=(4, 12))
        query_entry.bind("<Return>", lambda _event: self.start_search())

        self._label(form, "Pais", 0, 3)
        ttk.Combobox(form, textvariable=self.site_var, values=list(SITES.keys()), state="readonly").grid(
            row=1, column=3, sticky="ew", padx=(0, 10), pady=(4, 12)
        )

        self._label(form, "Modo", 0, 4)
        ttk.Combobox(form, textvariable=self.mode_var, values=["auto", "api", "html"], state="readonly").grid(
            row=1, column=4, sticky="ew", padx=(0, 10), pady=(4, 12)
        )

        self._label(form, "Limite", 0, 5)
        ttk.Spinbox(form, from_=1, to=500, textvariable=self.limit_var, width=8).grid(
            row=1, column=5, sticky="ew", padx=(0, 10), pady=(4, 12)
        )

        search_button = ttk.Button(form, text="Buscar", style="Primary.TButton", command=self.start_search)
        search_button.grid(row=1, column=6, sticky="ew", padx=(0, 10), pady=(4, 12))
        self.search_button = search_button

        clear_button = ttk.Button(form, text="Limpiar", command=self.clear_results)
        clear_button.grid(row=1, column=7, sticky="ew", pady=(4, 12))

        self._label(form, "Condicion", 2, 0)
        ttk.Combobox(
            form,
            textvariable=self.condition_var,
            values=["Todas", "Nuevo", "Usado"],
            state="readonly",
        ).grid(row=3, column=0, sticky="ew", padx=(0, 10), pady=(4, 0))

        self._label(form, "Precio minimo", 2, 1)
        ttk.Entry(form, textvariable=self.min_price_var).grid(row=3, column=1, sticky="ew", padx=(0, 10), pady=(4, 0))

        self._label(form, "Precio maximo", 2, 2)
        ttk.Entry(form, textvariable=self.max_price_var).grid(row=3, column=2, sticky="ew", padx=(0, 10), pady=(4, 0))

        self._label(form, "Token", 2, 3)
        ttk.Entry(form, textvariable=self.token_var, show="*").grid(
            row=3, column=3, columnspan=2, sticky="ew", padx=(0, 10), pady=(4, 0)
        )

        ttk.Checkbutton(form, text="Envio gratis", variable=self.free_shipping_var).grid(
            row=3, column=5, sticky="w", padx=(0, 10), pady=(4, 0)
        )
        ttk.Checkbutton(form, text="Traer detalle", variable=self.details_var).grid(
            row=3, column=6, sticky="w", padx=(0, 10), pady=(4, 0)
        )
        ttk.Button(form, text="Login Meli", command=self.open_login_window).grid(
            row=3, column=7, sticky="ew", pady=(4, 0)
        )

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=12)
        ttk.Button(actions, text="Exportar CSV", command=lambda: self.export_results("csv")).pack(side=tk.LEFT)
        ttk.Button(actions, text="Exportar JSON", command=lambda: self.export_results("json")).pack(side=tk.LEFT, padx=8)
        ttk.Button(actions, text="Abrir publicacion", command=self.open_selected).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=190)
        self.progress.pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Label(actions, textvariable=self.status_var, style="Muted.TLabel").pack(side=tk.RIGHT)

        table_frame = ttk.Frame(root, style="Panel.TFrame", padding=1)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.table = ttk.Treeview(table_frame, columns=[column[0] for column in COLUMNS], show="headings")
        for key, heading, width in COLUMNS:
            self.table.heading(key, text=heading)
            self.table.column(key, width=width, minwidth=60, anchor=tk.W)
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.bind("<Double-1>", lambda _event: self.open_selected())

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.table.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    def _label(self, parent: ttk.Frame, text: str, row: int, column: int) -> None:
        ttk.Label(parent, text=text, style="Panel.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 10))

    def open_login_window(self) -> None:
        window = tk.Toplevel(self)
        window.title("Login Mercado Libre")
        window.geometry("620x330")
        window.resizable(False, False)
        window.configure(bg="#f4f6f8")
        window.transient(self)
        window.grab_set()

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Conectar cuenta de Mercado Libre", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        fields = [
            ("App ID / Client ID", self.client_id_var, ""),
            ("Client Secret", self.client_secret_var, "*"),
            ("Redirect URI", self.redirect_uri_var, ""),
        ]
        for row_index, (label, variable, show) in enumerate(fields, start=1):
            ttk.Label(frame, text=label).grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=6)
            ttk.Entry(frame, textvariable=variable, show=show).grid(row=row_index, column=1, sticky="ew", pady=6)

        ttk.Label(
            frame,
            text="El Redirect URI debe estar cargado exactamente igual en tu app del DevCenter.",
            style="Muted.TLabel",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 12))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Autorizar en Mercado Libre", style="Primary.TButton", command=self.start_oauth_login).pack(
            side=tk.LEFT
        )
        ttk.Button(buttons, text="Renovar token", command=self.refresh_token).pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="Cerrar", command=window.destroy).pack(side=tk.RIGHT)

        ttk.Label(frame, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(16, 0)
        )

    def start_oauth_login(self) -> None:
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()
        redirect_uri = self.redirect_uri_var.get().strip()
        if not client_id or not client_secret or not redirect_uri:
            messagebox.showwarning("Login Mercado Libre", "Completa App ID, Client Secret y Redirect URI.")
            return

        parsed = urlparse(redirect_uri)
        if parsed.hostname not in {"localhost", "127.0.0.1"}:
            messagebox.showwarning(
                "Login Mercado Libre",
                "Usa un Redirect URI local, por ejemplo http://localhost:8080/callback.",
            )
            return

        self.status_var.set("Abriendo Mercado Libre para autorizar...")
        threading.Thread(
            target=self._oauth_worker,
            args=(client_id, client_secret, redirect_uri),
            daemon=True,
        ).start()

    def _oauth_worker(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        try:
            code = self._wait_for_oauth_code(client_id, redirect_uri)
            token_data = exchange_authorization_code(client_id, client_secret, code, redirect_uri)
            self.auth_queue.put(("success", token_data))
        except Exception as exc:
            self.auth_queue.put(("error", str(exc)))

    def _wait_for_oauth_code(self, client_id: str, redirect_uri: str) -> str:
        parsed = urlparse(redirect_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8080
        callback_path = parsed.path or "/callback"
        result: dict[str, str] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(handler_self) -> None:  # noqa: N802
                request_path = urlparse(handler_self.path)
                params = parse_qs(request_path.query)
                if request_path.path != callback_path:
                    handler_self.send_response(404)
                    handler_self.end_headers()
                    return
                if "error" in params:
                    result["error"] = params["error"][0]
                elif "code" in params:
                    result["code"] = params["code"][0]
                handler_self.send_response(200)
                handler_self.send_header("Content-Type", "text/html; charset=utf-8")
                handler_self.end_headers()
                handler_self.wfile.write(
                    b"<html><body><h2>Autorizacion recibida.</h2><p>Ya podes volver a la app.</p></body></html>"
                )

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        server = HTTPServer((host, port), CallbackHandler)
        server.timeout = 120
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        }
        auth_url = f"https://auth.mercadolibre.com.ar/authorization?{urlencode(params)}"
        webbrowser.open(auth_url)
        server.handle_request()
        server.server_close()

        if "error" in result:
            raise RuntimeError(f"Mercado Libre rechazo la autorizacion: {result['error']}")
        if "code" not in result:
            raise RuntimeError("No se recibio el codigo de autorizacion. Revisa el Redirect URI y volve a intentar.")
        return result["code"]

    def refresh_token(self) -> None:
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()
        refresh_token = self.refresh_token_var.get().strip()
        if not client_id or not client_secret or not refresh_token:
            messagebox.showwarning(
                "Renovar token",
                "Para renovar necesitas App ID, Client Secret y un refresh token obtenido con Login Meli.",
            )
            return
        self.status_var.set("Renovando token...")
        threading.Thread(
            target=self._refresh_worker,
            args=(client_id, client_secret, refresh_token),
            daemon=True,
        ).start()

    def _refresh_worker(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        try:
            token_data = refresh_access_token(client_id, client_secret, refresh_token)
            self.auth_queue.put(("success", token_data))
        except Exception as exc:
            self.auth_queue.put(("error", str(exc)))

    def parse_decimal(self, value: str, field_name: str) -> Decimal | None:
        value = value.strip()
        if not value:
            return None
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} debe ser un numero valido.") from exc

    def build_options(self) -> SearchOptions:
        query = self.query_var.get().strip()
        if not query:
            raise ValueError("Escribi una busqueda.")

        try:
            limit = int(self.limit_var.get())
        except ValueError as exc:
            raise ValueError("El limite debe ser un numero entero.") from exc
        if limit < 1:
            raise ValueError("El limite debe ser mayor a 0.")

        min_price = self.parse_decimal(self.min_price_var.get(), "Precio minimo")
        max_price = self.parse_decimal(self.max_price_var.get(), "Precio maximo")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ValueError("El precio minimo no puede ser mayor que el maximo.")

        condition_map = {"Todas": None, "Nuevo": "new", "Usado": "used"}
        return SearchOptions(
            query=query,
            site=SITES[self.site_var.get()],
            limit=limit,
            mode=self.mode_var.get(),
            token=self.token_var.get().strip() or None,
            condition=condition_map[self.condition_var.get()],
            min_price=min_price,
            max_price=max_price,
            free_shipping=self.free_shipping_var.get(),
            include_details=self.details_var.get(),
            delay=0.25,
        )

    def start_search(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            options = self.build_options()
        except ValueError as exc:
            messagebox.showwarning("Datos incompletos", str(exc))
            return

        self.clear_results()
        self.status_var.set("Buscando publicaciones...")
        self.search_button.configure(state=tk.DISABLED)
        self.progress.start(12)
        self.worker = threading.Thread(target=self._search_worker, args=(options,), daemon=True)
        self.worker.start()

    def _search_worker(self, options: SearchOptions) -> None:
        try:
            rows, source = run_search(options)
            self.result_queue.put(("success", (rows, source)))
        except Exception as exc:
            self.result_queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            kind, payload = self.result_queue.get_nowait()
        except queue.Empty:
            self.after(120, self._poll_queue)
            return

        self.progress.stop()
        self.search_button.configure(state=tk.NORMAL)
        if kind == "success":
            rows, source = payload
            self.rows = rows
            self.render_rows()
            source_label = "API" if source == "api" else "HTML"
            self.status_var.set(f"{len(rows)} resultados cargados. Fuente: {source_label}.")
            if not rows:
                messagebox.showinfo(
                    "Sin resultados",
                    "No se encontraron publicaciones. Si Mercado Libre mostro una verificacion, proba con token o modo API.",
                )
        else:
            self.status_var.set("No se pudo completar la busqueda.")
            messagebox.showerror("Error", str(payload))

        self.after(120, self._poll_queue)

    def _poll_auth_queue(self) -> None:
        try:
            kind, payload = self.auth_queue.get_nowait()
        except queue.Empty:
            self.after(160, self._poll_auth_queue)
            return

        if kind == "success":
            token_data = payload
            access_token = str(token_data.get("access_token") or "")
            refresh_token = str(token_data.get("refresh_token") or "")
            if access_token:
                self.token_var.set(access_token)
            if refresh_token:
                self.refresh_token_var.set(refresh_token)
            self.status_var.set("Cuenta conectada. Token cargado en la interfaz.")
            messagebox.showinfo("Login Mercado Libre", "Cuenta conectada correctamente.")
        else:
            self.status_var.set("No se pudo conectar la cuenta.")
            messagebox.showerror("Login Mercado Libre", str(payload))

        self.after(160, self._poll_auth_queue)

    def render_rows(self) -> None:
        for row in self.rows:
            values = [self.format_cell(row.get(key, "")) for key, _heading, _width in COLUMNS]
            self.table.insert("", tk.END, values=values)

    def format_cell(self, value: Any) -> str:
        if value is True:
            return "Si"
        if value is False:
            return "No"
        return "" if value is None else str(value)

    def clear_results(self) -> None:
        self.rows = []
        for item_id in self.table.get_children():
            self.table.delete(item_id)
        self.status_var.set("Listo para buscar.")

    def selected_row(self) -> dict[str, Any] | None:
        selection = self.table.selection()
        if not selection:
            return None
        index = self.table.index(selection[0])
        if index < 0 or index >= len(self.rows):
            return None
        return self.rows[index]

    def open_selected(self) -> None:
        row = self.selected_row()
        if not row:
            messagebox.showinfo("Abrir publicacion", "Selecciona una fila primero.")
            return
        permalink = str(row.get("permalink") or "")
        if not permalink:
            messagebox.showinfo("Abrir publicacion", "La publicacion seleccionada no tiene link.")
            return
        webbrowser.open(permalink)

    def export_results(self, output_format: str) -> None:
        if not self.rows:
            messagebox.showinfo("Exportar", "No hay resultados para exportar.")
            return
        extension = ".json" if output_format == "json" else ".csv"
        filetypes = [("JSON", "*.json")] if output_format == "json" else [("CSV", "*.csv")]
        output = filedialog.asksaveasfilename(
            title="Guardar resultados",
            defaultextension=extension,
            filetypes=filetypes + [("Todos los archivos", "*.*")],
            initialfile=f"resultados_meli{extension}",
        )
        if not output:
            return
        path = Path(output)
        try:
            if output_format == "json":
                write_json(self.rows, path)
            else:
                write_csv(self.rows, path)
        except Exception as exc:
            messagebox.showerror("Exportar", f"No se pudo guardar el archivo:\n{exc}")
            return
        self.status_var.set(f"Resultados exportados en {path.name}.")
        messagebox.showinfo("Exportar", "Archivo guardado correctamente.")


def main() -> None:
    app = MeliScraperApp()
    app.mainloop()


if __name__ == "__main__":
    main()
