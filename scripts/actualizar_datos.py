# -*- coding: utf-8 -*-
"""
Monitor de Cortes de Luz — Ian Arias (@ayam-arias)
Consulta la API pública de la SEC (Superintendencia de Electricidad y Combustibles)
y genera:
  - data/actual.json    : último snapshot por comuna/región + tops
  - data/historial.json : serie temporal nacional y por región (7 días móviles)

Ejecutado cada hora por GitHub Actions.
"""

import json
import os
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = "https://apps.sec.cl/INTONLINEv1/ClientesAfectados/GetPorFecha"
TZ_CHILE = timezone(timedelta(hours=-4))  # CLT invierno; solo referencial para consulta de fecha
DIAS_HISTORIAL = 7
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")


def norm(s: str) -> str:
    """Normaliza nombres de comuna: mayúsculas, sin tildes ni signos."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "".join(ch for ch in s.upper() if ch.isalnum())


# Alias entre nomenclatura SEC y geometrías oficiales
ALIAS = {
    "AISEN": "AYSEN",
    "COIHAIQUE": "COYHAIQUE",
    "PAIGUANO": "PAIHUANO",
    "MARCHIHUE": "MARCHIGUE",
    "LLAYLLAY": "LLAILLAY",
    "TREHUACO": "TREGUACO",
    "CABODEHORNOSEXNAVARINO": "CABODEHORNOS",
}


def consultar_sec(fecha: datetime):
    """Consulta la API SEC para una fecha. Devuelve lista de registros (o [])."""
    payload = json.dumps({
        "anho": str(fecha.year),
        "mes": str(fecha.month),
        "dia": str(fecha.day),
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (monitor-sinluz; github.com/ayam-arias)",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def campo(reg: dict, *nombres, defecto=None):
    """Acceso tolerante a variaciones de nombre de campo de la API."""
    for n in nombres:
        if n in reg:
            return reg[n]
        for k in reg:
            if k.upper() == n.upper():
                return reg[k]
    return defecto


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ahora_utc = datetime.now(timezone.utc)
    ahora_cl = ahora_utc.astimezone(TZ_CHILE)

    # 1) Obtener registros: hoy; si el día recién comienza y viene vacío, probar ayer
    registros = consultar_sec(ahora_cl)
    if not registros:
        registros = consultar_sec(ahora_cl - timedelta(days=1))

    # 2) Quedarse con la última actualización disponible (mayor HORA reportada)
    horas = [campo(r, "HORA", defecto=0) or 0 for r in registros]
    hora_max = max(horas) if horas else 0
    ultimos = [r for r in registros if (campo(r, "HORA", defecto=0) or 0) == hora_max]

    # 3) Agregar por comuna y región
    comunas = {}
    regiones = {}
    for r in ultimos:
        n_com = campo(r, "NOMBRE_COMUNA", "COMUNA", defecto="")
        n_reg = campo(r, "NOMBRE_REGION", "REGION", defecto="")
        id_reg = campo(r, "ID_REGION", defecto=0)
        cli = int(campo(r, "CLIENTES_AFECTADOS", "AFECTADOS", defecto=0) or 0)
        if not n_com:
            continue
        clave = norm(n_com)
        clave = ALIAS.get(clave, clave)
        c = comunas.setdefault(clave, {
            "comuna": n_com.title() if n_com.isupper() else n_com,
            "region": n_reg,
            "id_region": id_reg,
            "clientes": 0,
        })
        c["clientes"] += cli
        rg = regiones.setdefault(str(id_reg), {"region": n_reg, "clientes": 0})
        rg["clientes"] += cli

    total = sum(c["clientes"] for c in comunas.values())

    # 4) actual.json
    actual = {
        "actualizado_utc": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hora_sec": hora_max,
        "total": total,
        "regiones": regiones,
        "comunas": comunas,
    }
    with open(os.path.join(DATA_DIR, "actual.json"), "w", encoding="utf-8") as f:
        json.dump(actual, f, ensure_ascii=False, separators=(",", ":"))

    # 5) historial.json (serie nacional + por región, 7 días móviles)
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

    print(f"OK · {total:,} clientes sin suministro · {len(comunas)} comunas · hora SEC {hora_max}")


if __name__ == "__main__":
    main()
