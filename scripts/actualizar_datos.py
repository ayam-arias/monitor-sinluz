# -*- coding: utf-8 -*-
"""
Monitor de Cortes de Luz — Ian Arias (@ayam-arias)
https://github.com/ayam-arias · https://www.linkedin.com/in/ian-arias/

Consulta la API de la SEC y genera:
  - data/actual.json    : snapshot por comuna/region + total nacional
  - data/historial.json : serie temporal acumulada (7 dias)

v2 (2026-07): endurecido para GitHub Actions.
  - Soporta relay HTTPS (SEC_BASE) para evitar el bloqueo de IPs de runner.
  - Reintentos con backoff y diagnostico de red explicito (DNS / TCP / HTTP).
  - Modo fail-safe: si la API no responde NO sobreescribe datos ni falla el job.
  - Zona horaria real America/Santiago (DST), no offset fijo.
"""

import json
import os
import socket
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    TZ_CHILE = ZoneInfo("America/Santiago")
except Exception:  # fallback defensivo
    TZ_CHILE = timezone(timedelta(hours=-4))

# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------
# SEC_BASE permite apuntar a un relay (Cloudflare Worker / Apps Script) que
# reenvia la peticion a apps.sec.cl desde una IP no bloqueada.
SEC_BASE = os.environ.get("SEC_BASE", "https://apps.sec.cl").rstrip("/")
RELAY_TOKEN = os.environ.get("SEC_RELAY_TOKEN", "")
STRICT = os.environ.get("STRICT", "false").lower() == "true"
TIMEOUT = int(os.environ.get("SEC_TIMEOUT", "20"))
REINTENTOS = int(os.environ.get("SEC_REINTENTOS", "3"))

RUTA_POR_FECHA = "/INTONLINEv1/ClientesAfectados/GetPorFecha"
RUTA_NACIONAL = "/INTONLINEv1/ClientesAfectados/GetClientesNacional"

DIAS_HISTORIAL = 7
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")

HEADERS_COMUNES = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": "https://apps.sec.cl",
    "Referer": "https://apps.sec.cl/INTONLINEv1/index.aspx",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}
if RELAY_TOKEN:
    HEADERS_COMUNES["X-Relay-Token"] = RELAY_TOKEN

# Alias entre nomenclatura de la SEC y el geojson de comunas (verificados)
ALIAS = {
    "PAIGUANO": "PAIHUANO",
    "PUNITAGUI": "PUNITAQUI",
    "LACALERA": "CALERA",
}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


def resumen(msg: str) -> None:
    """Escribe en el Job Summary de GitHub Actions si esta disponible."""
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(ch for ch in s.upper() if ch.isalnum())


def diagnostico_red(url_base: str) -> list[str]:
    """Distingue bloqueo DNS / TCP / TLS / HTTP. Nunca lanza excepcion."""
    host = url_base.split("//", 1)[-1].split("/", 1)[0]
    lineas = [f"Host objetivo: {host}"]
    try:
        ips = sorted({i[4][0] for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
        lineas.append(f"DNS OK -> {', '.join(ips)}")
    except Exception as e:
        lineas.append(f"DNS FALLA -> {type(e).__name__}: {e}")
        return lineas
    t0 = time.time()
    try:
        with socket.create_connection((host, 443), timeout=10) as sock:
            lineas.append(f"TCP 443 OK ({time.time() - t0:.1f}s)")
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                lineas.append(f"TLS OK -> {ssock.version()}")
    except socket.timeout:
        lineas.append(
            f"TCP 443 TIMEOUT tras {time.time() - t0:.1f}s "
            "-> paquetes descartados (firewall del destino filtra el rango de IP del runner)"
        )
    except Exception as e:
        lineas.append(f"TCP/TLS FALLA -> {type(e).__name__}: {e}")
    return lineas


def construir_url(ruta: str) -> str:
    """Apps Script no admite rutas: se traduce a ?ruta=<metodo>."""
    if "script.google" in SEC_BASE:
        sep = "&" if "?" in SEC_BASE else "?"
        return f"{SEC_BASE}{sep}ruta={ruta.rsplit('/', 1)[-1]}"
    return SEC_BASE + ruta


def post_json(ruta: str, payload: dict | None, timeout: int = TIMEOUT):
    url = construir_url(ruta)
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(url, data=data, headers=HEADERS_COMUNES, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        crudo = r.read().decode("utf-8", errors="replace")
    if not crudo.strip():
        raise ValueError("respuesta vacia")
    return json.loads(crudo)


def post_json_reintentos(ruta: str, payload: dict | None):
    ultimo = None
    for intento in range(1, REINTENTOS + 1):
        try:
            return post_json(ruta, payload)
        except urllib.error.HTTPError as e:
            cuerpo = ""
            try:
                cuerpo = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            ultimo = f"HTTP {e.code} {e.reason} | {cuerpo}"
        except urllib.error.URLError as e:
            ultimo = f"URLError: {e.reason}"
        except Exception as e:
            ultimo = f"{type(e).__name__}: {e}"
        log(f"  intento {intento}/{REINTENTOS} fallido en {ruta} -> {ultimo}")
        if intento < REINTENTOS:
            time.sleep(3 * intento)
    raise RuntimeError(ultimo or "error desconocido")


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------
def consultar_por_fecha(fecha: datetime):
    payload = {"anho": fecha.year, "mes": fecha.month, "dia": fecha.day, "hora": fecha.hour}
    return post_json_reintentos(RUTA_POR_FECHA, payload)


def consultar_nacional():
    data = post_json_reintentos(RUTA_NACIONAL, None)
    if isinstance(data, list) and data:
        return int(data[0].get("CLIENTES", 0))
    return 0


# --------------------------------------------------------------------------
# Proceso principal
# --------------------------------------------------------------------------
def procesar(registros, clientes_pais, ahora_utc):
    comunas, regiones = {}, {}
    for r in registros:
        n_com = (r.get("NOMBRE_COMUNA") or "").strip()
        n_reg = (r.get("NOMBRE_REGION") or "").strip()
        cli = int(r.get("CLIENTES_AFECTADOS") or 0)
        if not n_com:
            continue
        clave_com = ALIAS.get(norm(n_com), norm(n_com))
        clave_reg = norm(n_reg)
        comunas[clave_com] = {
            "comuna": n_com,
            "region": n_reg,
            "region_key": clave_reg,
            "clientes": cli,
        }
        rg = regiones.setdefault(clave_reg, {"region": n_reg, "clientes": 0})
        rg["clientes"] += cli

    total = sum(c["clientes"] for c in comunas.values())
    actual = {
        "actualizado_utc": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fuente": SEC_BASE,
        "total": total,
        "clientes_pais": clientes_pais,
        "regiones": regiones,
        "comunas": comunas,
    }
    return actual, total, regiones, comunas


def escribir(actual, total, regiones, ahora_utc):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "actual.json"), "w", encoding="utf-8") as f:
        json.dump(actual, f, ensure_ascii=False, separators=(",", ":"))

    hist_path = os.path.join(DATA_DIR, "historial.json")
    historial = {"puntos": []}
    if os.path.exists(hist_path):
        try:
            with open(hist_path, encoding="utf-8") as f:
                historial = json.load(f)
        except Exception:
            pass

    historial.setdefault("puntos", []).append({
        "t": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total,
        "reg": {k: v["clientes"] for k, v in regiones.items() if v["clientes"] > 0},
    })

    limite = ahora_utc - timedelta(days=DIAS_HISTORIAL, hours=2)
    historial["puntos"] = [
        p for p in historial["puntos"]
        if datetime.strptime(p["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= limite
    ]
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, separators=(",", ":"))


def main():
    ahora_utc = datetime.now(timezone.utc)
    ahora_cl = ahora_utc.astimezone(TZ_CHILE)
    modo = "RELAY" if "apps.sec.cl" not in SEC_BASE else "DIRECTO"
    log(f"Origen de datos: {SEC_BASE}  [{modo}]  hora Chile: {ahora_cl:%Y-%m-%d %H:%M}")

    try:
        registros = consultar_por_fecha(ahora_cl)
        clientes_pais = consultar_nacional()
    except Exception as e:
        diag = diagnostico_red(SEC_BASE)
        log("\n=== DIAGNOSTICO DE RED ===")
        for l in diag:
            log("  " + l)
        resumen(
            "### Sin datos de la SEC\n\n"
            f"- Origen: `{SEC_BASE}` ({modo})\n"
            f"- Error: `{e}`\n"
            "- Diagnostico:\n"
            + "".join(f"  - {l}\n" for l in diag)
            + "\nDatos previos conservados (no se sobreescribio `data/`).\n"
        )
        if STRICT:
            log("\nSTRICT=true -> job marcado como fallido.")
            sys.exit(1)
        log("\nFail-safe: se conservan los datos previos y el job termina en verde.")
        sys.exit(0)

    actual, total, regiones, comunas = procesar(registros, clientes_pais, ahora_utc)

    # Guarda de calidad: no publicar un cero sospechoso si la API devolvio vacio
    if not comunas:
        log("La API respondio sin comunas. Se conservan los datos previos.")
        resumen("### La API SEC respondio sin registros; datos previos conservados.\n")
        sys.exit(0)

    escribir(actual, total, regiones, ahora_utc)
    msg = (
        f"OK · {total:,} clientes sin suministro de {clientes_pais:,} · "
        f"{len(comunas)} comunas · {len(regiones)} regiones"
    ).replace(",", ".")
    log(msg)
    resumen(f"### {msg}\n")


if __name__ == "__main__":
    main()
