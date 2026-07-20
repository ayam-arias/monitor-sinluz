# ⚡ Monitor de Cortes de Luz — Chile

Monitor en tiempo casi real de clientes sin suministro eléctrico en Chile, con datos
oficiales de la **Superintendencia de Electricidad y Combustibles (SEC)**.

**Demo:** https://ayam-arias.github.io/monitor-sinluz/

Desarrollado por **[Ian Arias](https://www.linkedin.com/in/ian-arias/)** — Analista Geoespacial ·
Ing. en Geomensura y Cartografía · GIS · Teledetección · RPAS.
Inspirado en el trabajo original de [@aprendecondiland](https://diland9.github.io/monitor-sinluz/).

---

## Arquitectura

```
API SEC (apps.sec.cl) ──► GitHub Actions (cron horario)
                              │  scripts/actualizar_datos.py
                              ▼
                        data/actual.json      ← snapshot por comuna/región
                        data/historial.json   ← serie temporal 7 días
                              │
                              ▼
                        GitHub Pages (index.html)
                        Leaflet + Chart.js
```

Sin servidores, sin bases de datos externas, sin Google Sheets: todo vive en este repositorio.

## Estructura

| Archivo | Descripción |
|---|---|
| `index.html` | Dashboard completo (mapa, gráfico, filtros, tops) |
| `scripts/actualizar_datos.py` | Consulta la API SEC y regenera los JSON |
| `data/comunas_centroides.json` | Centroides de las 346 comunas de Chile |
| `data/actual.json` | Último snapshot (generado automáticamente) |
| `data/historial.json` | Serie temporal de 7 días (generado automáticamente) |
| `.github/workflows/actualizar.yml` | Cron horario de actualización |

## Despliegue (5 minutos)

1. **Crear el repositorio** `monitor-sinluz` en tu cuenta de GitHub (público).
2. **Subir todos los archivos** de este paquete respetando la estructura de carpetas
   (`Add file → Upload files`, arrastrando las carpetas completas).
3. **Permisos de escritura para Actions:**
   `Settings → Actions → General → Workflow permissions → Read and write permissions → Save`.
4. **Primera carga de datos:**
   `Actions → Actualizar datos SEC → Run workflow`.
   Esto genera `data/actual.json` y `data/historial.json`.
5. **Activar GitHub Pages:**
   `Settings → Pages → Source: Deploy from a branch → Branch: main / (root) → Save`.
6. Esperar 1–2 minutos y abrir `https://ayam-arias.github.io/monitor-sinluz/`.

Desde ese momento, el workflow se ejecuta **cada hora** (minuto 12 UTC) y el sitio se
redespliega solo con cada commit de datos.

## Notas técnicas

- **`CLIENTES_PAIS`** (en `index.html`): base referencial de clientes eléctricos a nivel
  nacional usada para calcular el "% del país" (≈ 8,16 millones). Ajustable según cifra
  oficial vigente de la SEC.
- La **leyenda del mapa** clasifica comunas por percentiles del evento en curso
  (top 10 % / 10–30 % / 30–60 % / 60–100 %), igual que el visor original de la SEC.
- El historial se **poda automáticamente a 7 días** para mantener el JSON liviano.
- Si la API de la SEC cambia nombres de campos, `actualizar_datos.py` tiene acceso
  tolerante a variaciones (`campo()`).
- Los cron de GitHub Actions pueden retrasarse algunos minutos en horas de alta demanda;
  es comportamiento normal de la plataforma.

## Licencia y créditos

- Datos: [SEC Chile](https://www.sec.cl/) — información pública de interrupciones de suministro.
- Geometrías comunales: [fcortes/Chile-GeoJSON](https://github.com/fcortes/Chile-GeoJSON).
- Mapa base: © OpenStreetMap © CARTO.
