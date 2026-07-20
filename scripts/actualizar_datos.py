# -*- coding: utf-8 -*-
"""
Monitor de Cortes de Luz — Ian Arias (@ayam-arias)
Consulta la API real de la SEC (verificada por ingenieria inversa del sitio
www.sec.cl/interrupciones-en-linea) y genera:
  - data/actual.json    : snapshot por comuna/region + total nacional
  - data/historial.json : serie temporal acumulada (7 dias)

Ejecutado cada hora por GitHub Actions.
"""

import json
import os
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_URL = "https://apps.sec.cl/INTONLINEv1/ClientesAfectados"
URL_POR_FECHA = f"{BASE_URL}/GetPorFecha"
URL_NACIONAL = f"{BASE_URL}/GetClientesNacional"

TZ_CHILE = timezone(timedelta(hours=-4))  # referencial; SEC opera en hora de Chile
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


# Alias entre nomenclatura de la SEC y el geojson de comunas (verificados)
ALIAS = {
    "PAIGUANO": "PAIHUANO",
    "PUNITAGUI": "PUNITAQUI",
    "LACALERA": "CALERA",
}


def norm(s: str) -> str:
    """Normaliza nombres: mayusculas, sin tildes ni signos."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(ch for ch in s.upper() if ch.isalnum())


def post_json(url: str, payload: dict | None, timeout: int = 30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(url, data=data, headers=HEADERS_COMUNES, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def consultar_por_fecha(fecha: datetime):
    payload = {
        "anho": fecha.year,
        "mes": fecha.month,
        "dia": fecha.day,
        "hora": fecha.hour,
    }
    return post_json(URL_POR_FECHA, payload)


def consultar_nacional():
    data = post_json(URL_NACIONAL, None)
    if isinstance(data, list) and data:
        return int(data[0].get("CLIENTES", 0))
    return 0


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ahora_utc = datetime.now(timezone.utc)
    ahora_cl = ahora_utc.astimezone(TZ_CHILE)

    registros = consultar_por_fecha(ahora_cl)
    clientes_pais = consultar_nacional()

    comunas = {}
    regiones = {}
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
        "total": total,
        "clientes_pais": clientes_pais,
        "regiones": regiones,
        "comunas": comunas,
    }
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

    punto = {
        "t": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total,
        "reg": {k: v["clientes"] for k, v in regiones.items() if v["clientes"] > 0},
    }
    historial["puntos"].append(punto)

    limite = ahora_utc - timedelta(days=DIAS_HISTORIAL, hours=2)
    historial["puntos"] = [
        p for p in historial["puntos"]
        if datetime.strptime(p["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= limite
    ]

    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, separators=(",", ":"))

    print(f"OK · {total:,} clientes sin suministro de {clientes_pais:,} · {len(comunas)} comunas")


if __name__ == "__main__":
    main()
