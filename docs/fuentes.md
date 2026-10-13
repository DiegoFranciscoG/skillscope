# Fuentes de datos, límites verificados y presupuesto por ejecución

Regla del colector: **cada fuente tiene presupuesto de llamadas por ejecución, caché con ETag y back-off exponencial**. Si una fuente falla, el build continúa con las demás y lo registra en `index.json → sources`.
Los números `#n` remiten a [investigacion.md](investigacion.md). Límites consultados el 2026-10-12.

## 1. Resumen

| Fuente | Rol | Estado | Credencial | Límite oficial verificado | Presupuesto por ejecución (por defecto) | Cadencia propia |
|---|---|---|---|---|---|---|
| GitHub REST | Motor (árboles, búsqueda) | Activa | `SKILLSCOPE_GITHUB_TOKEN` (en Actions: `GITHUB_TOKEN` o un token fino propio) | 1.000/h por repo con `GITHUB_TOKEN`; 5.000/h con token personal (#12) | 140 llamadas | Cada build |
| GitHub Search (repos) | Motor (descubrimiento) | Activa | Igual | 30/min, 1.000 resultados por consulta (#14) | 24 llamadas, ≥ 2,1 s entre llamadas | Cada build |
| GitHub Search (código) | Motor (descubrimiento) | Activa si el token lo permite (S2) | Igual | 10/min, exige token (#14) | 5 llamadas, ≥ 6,5 s entre llamadas | Cada build |
| GitHub GraphQL | Motor (metadatos y contenido) | Activa | Igual | 1.000 pts/h con `GITHUB_TOKEN`, 5.000 con token personal; 2.000 pts/min (#15) | 120 puntos | Cada build |
| npm downloads | Adopción (descargas) | Activa | Ninguna | No publicado (S4) | 30 llamadas, caché 24 h | Cada build |
| Hacker News (Algolia) | Señal social | Activa | Ninguna | 10.000/h por IP (#31) | 6 llamadas | Cada build |
| Stack Exchange | Señal de **demanda** y menciones | Activa | `SKILLSCOPE_STACKEXCHANGE_KEY` opcional | 300/día por IP sin clave; respetar `backoff`; no repetir consulta en < 1 min (#32) | 6 llamadas | Cada 120 min |
| Reddit | Señal social y demanda | **Apagada** salvo credenciales aprobadas (S5) | `SKILLSCOPE_REDDIT_CLIENT_ID`, `SKILLSCOPE_REDDIT_CLIENT_SECRET`, `SKILLSCOPE_REDDIT_USER_AGENT` | 100 QPM por client id (#36) | 10 llamadas | Cada 60 min |
| DEV (Forem) | Señal social | Activa | Ninguna | No publicado; API pública (#42) | 2 listados + 10 artículos | Cada 60 min |
| Mastodon (mastodon.social, hachyderm.io, fosstodon.org) | Señal social | Activa | Ninguna | 300 / 5 min por IP en cada instancia (#40, #60) | 9 llamadas (3 etiquetas × 3 instancias); una publicación federada cuenta una vez | Cada 30 min |
| Lemmy (programming.dev, lemmy.world) | Señal social | Activa | Ninguna | Por IP; `Crawl-delay: 60` (#61) | 1 búsqueda por instancia, consulta rotativa | Cada 60 min |
| GitHub — historial de estrellas | Tendencias | Activa | `SKILLSCOPE_GITHUB_TOKEN` | Recurso `core` (#12, #59) | 40 repos por build, cada uno a lo sumo una vez cada 20 h | Cada build, antes del análisis |
| GitHub Search desde el navegador | Búsqueda en vivo | Activa, solo al pulsar «Buscar en GitHub ahora» | Ninguna (sin cuenta ni cookies) | 10/min por IP del visitante (#14, #62) | 1 petición por clic | A pedido |
| Bluesky | Señal social | Opcional (E2) | `SKILLSCOPE_BLUESKY_HANDLE`, `SKILLSCOPE_BLUESKY_APP_PASSWORD` | 3.000 / 5 min por IP; 300 sesiones/día (#38) | 1 sesión + 3 búsquedas | Cada 120 min |
| YouTube Data API | Señal social | Opcional | `SKILLSCOPE_YOUTUBE_API_KEY` | 100 `search.list`/día (#37) | 2 búsquedas + 1 `videos.list` | Cada 180 min (≤ 16 búsquedas/día) |
| X | — | **Descartada** | — | Sin nivel gratuito utilizable (#44) | — | — |
| Lobsters | — | **Descartada** | — | Su `robots.txt` prohíbe todo agente que no sea un buscador (#61, nota) | — | — |
| Instagram / Facebook | — | **Descartadas** | — | Solo API oficial con cuenta de empresa propia y revisión de app; recolección automatizada prohibida sin permiso escrito (#45, #46) | — | — |

## 2. Cómo se calcula el presupuesto de GitHub

1. Antes de empezar, el colector consulta `GET /rate_limit` (no descuenta del límite) y toma `remaining` de cada recurso (`core`, `search`, `code_search`, `graphql`).
2. Presupuesto efectivo = `min(presupuesto configurado, remaining − 10 % del límite)`. Nunca se gasta la reserva.
3. En cada respuesta se leen `x-ratelimit-remaining` y `x-ratelimit-reset` (#12). Si `remaining` cae a la reserva, ese recurso se cierra para el resto de la ejecución.
4. Errores 403/429: si hay `retry-after` se espera eso; si `remaining = 0` se espera a `reset` (o se cierra el recurso si el reset cae fuera del tiempo de la ejecución); si no, 60 s y back-off exponencial con jitter, máximo 3 reintentos (#12, #13).
5. Peticiones en serie, nunca concurrentes (#13). Las búsquedas se espacian (2,1 s y 6,5 s) para no rozar 30/min y 10/min.
6. Peticiones condicionales con `If-None-Match`: un 304 autenticado no descuenta (#13), así que refrescar un recurso sin cambios es gratis.

**Cuenta para el peor caso con `GITHUB_TOKEN`** (1.000 REST/h y 1.000 pts GraphQL/h por repo, #12 y #15): hasta 6 builds por hora (4 del cron cada 15 min + 2 del disparador externo cada 30 min) × 140 REST = 840 < 1.000, y 6 × 120 = 720 pts < 1.000. Queda margen para el vigilante y para builds manuales.

**Rendimiento medido (E11)**: los metadatos se piden en lotes de 10 repos por consulta GraphQL (40 llegaban al tope de 10 s y GitHub respondía `502`/`429`); si una consulta falla se parte por la mitad y un repo que falla solo vuelve a la cola (se descarta tras 3 builds). Después de cada respuesta de GitHub el recolector espera 0,5 × lo que tardó, para que el CPU que consume en el servidor quede por debajo del tope secundario (#12). Con la cola llena (≥ 300 candidatos) la búsqueda amplia se difiere y solo se buscan repos recientes. Con token personal y estado vacío: 40 repos en el primer build y ~60 nuevos por build después. Con un token fino propio (5.000/h) se pueden subir `SKILLSCOPE_BUDGET_REST` y `SKILLSCOPE_BUDGET_GRAPHQL` como variables del repo.

## 3. Estrategia de descubrimiento (GitHub)

| Vía | Consulta | Por qué |
|---|---|---|
| Topics | `topic:claude-skills`, `claude-code-plugin`, `claude-skill`, `agent-skills`, `claude-code-skills`, `claude-plugin`, `claude-code-plugins`, `claude-plugins`, `claude-marketplace`, `claude-code-marketplace`, `skill-md`, `claude-code-hooks`, `claude-code-agents`, `claude-code-commands`, `claude-agents`, `claude-code`, y `topic:mcp claude` | Topics del sondeo E7. `OR` no funciona con calificadores (E6): una consulta por topic. |
| Partición por fecha | Si una consulta supera 1.000 resultados (#14) se parte el rango `created:` por la mitad hasta que cada trozo quede bajo 1.000. Los trozos y su cursor se guardan en `state.json`. | Permite recorrer el universo completo a lo largo de varias ejecuciones. |
| Frescura | `topic:X pushed:>=<último build>` ordenado por `updated` | Detecta cambios sin reprocesar todo. |
| Código | `name filename:SKILL.md`, `plugins filename:marketplace.json path:.claude-plugin`, `name filename:plugin.json path:.claude-plugin`, partidos por `size:` | Encuentra skills en repos sin topics (E8). |
| Listas y marketplaces | Enlaces `github.com/owner/repo` de listas awesome conocidas y entradas `source` de cada `marketplace.json` analizado (incluidos los oficiales, #9) | Descubrimiento en bola de nieve y dato de adopción («en cuántas colecciones aparece»). |

Prioridad de la cola de candidatos: `log10(1 + estrellas) + 0,5 · (nº de vías que lo encontraron) + 0,3 · recencia`. Los repos sin artefactos se recuerdan con su `head_oid` para no volver a revisarlos hasta que cambien.

## 4. Qué se guarda de cada fuente (minimización)

| Fuente | Se guarda | No se guarda |
|---|---|---|
| GitHub | Metadatos públicos del repo, rutas del árbol, archivos de configuración necesarios para el análisis (en `data/raw`, que **no** se versiona ni se publica) | Correos de `owner`/`author` de los manifiestos, contenido de README en el sitio |
| Stack Exchange | Título, enlace, autor (nombre público) y fecha de preguntas de demanda, con atribución CC BY-SA (#35) | Cuerpos de preguntas y respuestas |
| Reddit | Conteo de menciones y de peticiones por tema y día | Títulos, textos, autores e IDs (evita la obligación de borrado de #36) |
| HN, DEV, Mastodon, Bluesky, YouTube | Conteo por repo y día, peso de interacción y hash del ID para no contar dos veces (retención 180 días) | Textos, autores |

Las redes sociales **nunca** aparecen como recomendación: solo alimentan el componente «Interés social» y la lista «Más mencionadas».

## 5. Retirada del índice

Si el autor de un repo pide salir, se saca sin discusión:

1. **Autoservicio**: agregar el topic `skillscope-optout` al repo. El siguiente build lo excluye.
2. **Formulario**: issue con la plantilla «Retirar mi repositorio». Si quien abre el issue es el dueño del repo, el build lo excluye automáticamente; si no, basta con que el mantenedor ponga la etiqueta `opt-out-approved`.
3. **Manual**: línea en `config/optout.txt`.
