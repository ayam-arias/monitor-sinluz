/**
 * Relay SEC — Cloudflare Worker
 * Ian Arias · Análisis Geoespacial
 * https://github.com/ayam-arias · https://www.linkedin.com/in/ian-arias/
 *
 * Reenvía las consultas a apps.sec.cl desde la red de Cloudflare, evitando el
 * filtrado de los rangos IP de los runners de GitHub Actions (Azure).
 *
 * Despliegue (3 minutos, plan gratuito):
 *   1. dash.cloudflare.com -> Workers & Pages -> Create -> Start with Hello World
 *   2. Pegar este código y desplegar.
 *   3. Settings -> Variables -> añadir RELAY_TOKEN (una cadena aleatoria).
 *   4. En el repo: Settings -> Secrets and variables -> Actions:
 *        SEC_BASE        = https://<nombre>.<subdominio>.workers.dev
 *        SEC_RELAY_TOKEN = <mismo valor de RELAY_TOKEN>
 *
 * Costo: 100.000 solicitudes/día en el plan free; el monitor usa 48/día.
 */

const UPSTREAM = "https://apps.sec.cl";

const RUTAS_PERMITIDAS = new Set([
  "/INTONLINEv1/ClientesAfectados/GetPorFecha",
  "/INTONLINEv1/ClientesAfectados/GetClientesNacional",
]);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/" || url.pathname === "/health") {
      return json({ ok: true, servicio: "relay-sec", rutas: [...RUTAS_PERMITIDAS] });
    }

    if (!RUTAS_PERMITIDAS.has(url.pathname)) {
      return json({ error: "ruta no permitida" }, 403);
    }

    if (env.RELAY_TOKEN && request.headers.get("X-Relay-Token") !== env.RELAY_TOKEN) {
      return json({ error: "token invalido" }, 401);
    }

    const cuerpo = request.method === "POST" ? await request.text() : "";

    let upstream;
    try {
      upstream = await fetch(UPSTREAM + url.pathname, {
        method: "POST",
        headers: {
          "Accept": "application/json, text/javascript, */*; q=0.01",
          "Content-Type": "application/json; charset=UTF-8",
          "Origin": UPSTREAM,
          "Referer": `${UPSTREAM}/INTONLINEv1/index.aspx`,
          "X-Requested-With": "XMLHttpRequest",
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        },
        body: cuerpo,
      });
    } catch (e) {
      return json({ error: "upstream inalcanzable", detalle: String(e) }, 502);
    }

    const texto = await upstream.text();
    return new Response(texto, {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
