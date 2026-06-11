# Scraper Mercado Libre

Scraper/exportador simple para buscar publicaciones de Mercado Libre y guardar los resultados en CSV o JSON.

La implementacion usa endpoints publicos de Mercado Libre en vez de parsear HTML. Eso suele ser mas estable, mas rapido y menos fragil ante cambios visuales del sitio.

## Requisitos

- Python 3.10 o superior
- No requiere instalar paquetes

## Uso rapido

Abrir la interfaz grafica:

```powershell
python .\gui_meli.py
```

Tambien se puede abrir con doble clic en `iniciar_interfaz.bat`.

Desde la ventana se puede buscar, aplicar filtros, abrir una publicacion seleccionada y exportar los resultados en CSV o JSON.

## Login con Mercado Libre

La interfaz tiene un boton `Login Meli` para autorizar tu cuenta sin copiar el token a mano.

Pasos:

1. Entra al DevCenter de Mercado Libre y crea una aplicacion.
2. En la aplicacion, agrega este Redirect URI:

```text
http://localhost:8080/callback
```

3. Abri `iniciar_interfaz.bat`.
4. Toca `Login Meli`.
5. Completa `App ID / Client ID`, `Client Secret` y deja el Redirect URI igual al configurado.
6. Toca `Autorizar en Mercado Libre`.
7. Se abre el navegador, aceptas permisos y volves a la app.

La app recibe el `access_token` y lo carga en el campo `Token`. El token queda en memoria mientras la ventana esta abierta; no se guarda en disco.

## Subir a Railway

Para Railway se usa la app web `app.py`, no la interfaz de escritorio `gui_meli.py`.

Archivos importantes para deploy:

- `app.py`: app web Flask.
- `requirements.txt`: dependencias.
- `Procfile`: comando de arranque.
- `.python-version`, `runtime.txt` y `nixpacks.toml`: fijan Python 3.12 para evitar errores de build con Python 3.13.
- `scraper_meli.py`: motor de busqueda.

Variables de entorno recomendadas en Railway:

```text
SECRET_KEY=una_clave_larga_aleatoria
MELI_CLIENT_ID=tu_app_id
MELI_CLIENT_SECRET=tu_client_secret
MELI_REDIRECT_URI=https://tu-dominio-de-railway.up.railway.app/callback
```

Cuando Railway te de el dominio HTTPS, copia esa URL y agregale `/callback`. Esa direccion exacta tambien tiene que estar cargada en la app de Mercado Libre DevCenter.

Ejemplo:

```text
https://scraper-meli-production.up.railway.app/callback
```

En Railway:

1. Subi este proyecto a GitHub.
2. En Railway, crea un proyecto desde ese repo.
3. Configura las variables de entorno.
4. Deploy.
5. En Mercado Libre DevCenter, agrega el Redirect URI HTTPS de Railway.
6. Entra a tu web y toca `Login Meli`.

Si Railway muestra un error como `no precompiled python found for core:python@3.13.14`, asegurate de haber subido `.python-version`, `runtime.txt` y `nixpacks.toml`. Esos archivos fuerzan Python 3.12.11.

Uso por consola:

```powershell
python .\scraper_meli.py "iphone 15" --limit 30 --output resultados.csv
```

Si Mercado Libre bloquea consultas anonimas a la API, se puede pasar un access token:

```powershell
python .\scraper_meli.py "iphone 15" --token "TU_ACCESS_TOKEN" --limit 30
```

O dejarlo en una variable de entorno:

```powershell
$env:MELI_ACCESS_TOKEN="TU_ACCESS_TOKEN"
python .\scraper_meli.py "iphone 15" --limit 30
```

Exportar JSON:

```powershell
python .\scraper_meli.py "notebook gamer" --limit 20 --output notebooks.json --format json
```

Filtrar publicaciones nuevas, con envio gratis y rango de precio:

```powershell
python .\scraper_meli.py "auriculares bluetooth" --condition new --free-shipping --min-price 10000 --max-price 80000 --limit 50
```

Traer detalle adicional por publicacion:

```powershell
python .\scraper_meli.py "silla gamer" --limit 10 --details --output sillas.csv
```

Forzar el modo HTML publico:

```powershell
python .\scraper_meli.py "iphone" --mode html --limit 10
```

Por defecto `--mode auto` intenta primero la API y, si falla, prueba HTML. El modo HTML puede devolver una pagina de verificacion si Mercado Libre detecta trafico automatizado; en ese caso no habra resultados para extraer.

## Sitios disponibles

El sitio se indica con `--site`. Algunos ejemplos:

- `MLA`: Argentina
- `MLB`: Brasil
- `MLM`: Mexico
- `MLC`: Chile
- `MCO`: Colombia
- `MLU`: Uruguay

Ejemplo para Mexico:

```powershell
python .\scraper_meli.py "laptop" --site MLM --limit 25
```

## Columnas exportadas

El CSV/JSON incluye, entre otros campos:

- ID, titulo, precio, moneda y condicion
- Link de la publicacion
- vendedor, tienda oficial y categoria
- cantidad disponible y vendida
- envio gratis, modo de envio y cuotas
- ubicacion aproximada
- atributos del producto en formato JSON

## Buenas practicas

- Usar `--delay` para dejar una pausa entre consultas, especialmente con `--details`.
- Mantener limites razonables de resultados.
- Revisar los terminos de uso de Mercado Libre si se planea automatizar consultas intensivas o comerciales.
