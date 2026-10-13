# Investigación y fuentes

Todo lo que el proyecto da por cierto sale de esta tabla. Cada regla del código o de la documentación cita su número (`#n`).
Fecha de consulta de todas las fuentes: **2026-10-12** (salvo que se indique otra).

## 1. Fuentes oficiales consultadas

### 1.1 Formato del ecosistema (skills, plugins y marketplaces)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 1 | Claude Code Docs — Skills | https://code.claude.com/docs/en/skills | En Claude Code **todos** los campos del frontmatter son opcionales; solo se recomienda `description`. `description` + `when_to_use` se truncan a 1.536 caracteres. Ubicaciones: `~/.claude/skills/<n>/SKILL.md` (personal), `.claude/skills/` (proyecto), `<plugin>/skills/<n>/SKILL.md`. Recomendación: SKILL.md de menos de 500 líneas y el detalle en archivos de apoyo. Riesgos: `allowed-tools` concede permisos sin preguntar; `` !`cmd` `` ejecuta comandos antes de cargar la skill. |
| 2 | Agent Skills — Specification | https://agentskills.io/specification | Estándar abierto que sigue Claude Code. `name` **obligatorio**: 1–64 caracteres, solo `a-z`, `0-9` y `-`, sin guion al inicio/fin, sin `--`, igual al nombre de la carpeta. `description` **obligatorio**: 1–1.024 caracteres, debe decir qué hace y cuándo usarla. Opcionales: `license`, `compatibility` (≤ 500), `metadata` (mapa texto→texto), `allowed-tools`. Carpetas `scripts/`, `references/`, `assets/`. Cuerpo < 5.000 tokens y < 500 líneas. |
| 3 | Plugin manifest reference | https://code.claude.com/docs/en/plugins-reference | `.claude-plugin/plugin.json` es **opcional**; si existe, `name` es el **único campo obligatorio** (kebab-case, sin espacios, `@`, `:` ni separadores). Opcionales: `version`, `description`, `author{name,email,url}`, `homepage`, `repository`, `license` (SPDX), `keywords`, `commands`, `agents`, `skills`, `hooks`, `mcpServers`, `lspServers`, `userConfig`, etc. Estructura estándar: `skills/`, `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json`, `bin/`. Nombres reservados (`claude-*`, `anthropic-*`…). Rutas deben empezar con `./` y no salir de la raíz. |
| 4 | Create a marketplace | https://code.claude.com/docs/en/plugin-marketplaces | `marketplace.json` en `.claude-plugin/` exige `name`, `owner` y `plugins`; cada entrada exige `name` y `source`. Instalación: `claude plugin marketplace add <owner>/<repo>` y `claude plugin install <plugin>@<marketplace>` (en sesión: `/plugin marketplace add`, `/plugin install`). |
| 5 | Marketplace reference | https://code.claude.com/docs/en/plugins/marketplace-reference | Reglas de `name` (letras, dígitos, `.`, `_`, `-`; empieza con letra o dígito), `owner.name` obligatorio, lista de **nombres reservados** (`claude-plugins-official`, `agent-skills`, …) válidos solo bajo `github.com/anthropics/`. Tipos de `source`: ruta relativa (`./`), `github{repo,ref,sha}`, `url`, `git-subdir`, `npm`, `archive{url,sha256}`, `command`. |
| 6 | Install and manage plugins | https://code.claude.com/docs/en/plugins/install | Comandos exactos: `/plugin marketplace add owner/repo` (admite `#ref`), `/plugin install <p>@<m>`, `claude plugin install <p>@<m> --scope user|project|local`, y en un paso `claude plugin install <p> --marketplace owner/repo` (v2.1.292+). |
| 7 | Plugin security and trust | https://code.claude.com/docs/en/plugins/security | «Un plugin puede ejecutar código arbitrario en tu máquina con tus privilegios». Hooks, monitores, servidores MCP/LSP y `bin/` corren fuera del sandbox; revisar `hooks/hooks.json`, `.mcp.json` y `bin/` antes de instalar. Base de las banderas de riesgo. |
| 8 | Publish and distribute a plugin | https://code.claude.com/docs/en/plugins/publish | Sin marketplace: `claude --plugin-dir ./ruta` (una sesión) o mover el plugin bajo `~/.claude/skills/`. Con marketplace en el mismo repo: entrada con `"source": "./"`. |
| 9 | Anthropic's marketplaces | https://code.claude.com/docs/en/plugins/anthropic-marketplaces | Repos oficiales: `anthropics/claude-plugins-official` (`claude-plugins-official`), `anthropics/claude-plugins-community` (`claude-community`), `anthropics/claude-code` (demo `claude-code-plugins`), además de `anthropics/skills`. Se usan como semillas de descubrimiento. |
| 10 | MCP | https://code.claude.com/docs/en/mcp | Sintaxis `claude mcp add [opciones] <nombre> -- <comando> [args]` y `--transport http <nombre> <url>`; ámbitos `local`, `project`, `user`. |
| 11 | Subagents | https://code.claude.com/docs/en/sub-agents | Agentes en `.claude/agents/` y `~/.claude/agents/`; `name` y `description` obligatorios; `tools` opcional (si falta hereda todas). |

### 1.2 GitHub (API, Actions, Pages y términos)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 12 | Rate limits for the REST API | https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api | REST: 60/h sin autenticar, **5.000/h** con token personal, **1.000/h por repositorio con `GITHUB_TOKEN`** en Actions. Secundarios: ≤ 100 concurrentes, 900 puntos/min REST y 2.000/min GraphQL, 90 s de CPU por minuto (máx. 60 s para GraphQL); el CPU «se estima midiendo el tiempo total de respuesta»; ante `retry-after` no reintentar antes de ese plazo (consultado de nuevo el 2026-10-13). Cabeceras `x-ratelimit-limit/remaining/used/reset/resource`. Al exceder: 403/429; respetar `retry-after`, si `remaining=0` esperar a `reset`, si no esperar ≥ 1 min y luego back-off exponencial. |
| 13 | Best practices for using the REST API | https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api | ETag/`If-None-Match` y `Last-Modified`; **un 304 no descuenta del límite primario** si la petición va autenticada. Peticiones en serie, no concurrentes. Seguir redirecciones y enlaces `Link` de paginación sin construir URLs a mano. |
| 14 | REST — Search | https://docs.github.com/en/rest/search/search | Búsqueda: **30/min** autenticado (10 sin autenticar); búsqueda de código **exige token** y tiene **10/min**. **Máximo 1.000 resultados por búsqueda**, 100 por página. Consultas de ≤ 256 caracteres y ≤ 5 operadores. Código: solo rama por defecto y archivos < 384 KB. `incomplete_results` ante timeouts. |
| 15 | GraphQL rate and query limits | https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api | **5.000 puntos/h** por usuario, **1.000 puntos/h por repo con `GITHUB_TOKEN`**. Costo = solicitudes/100 (mínimo 1). `first/last` 1–100, ≤ 500.000 nodos. Timeout de 10 s (502/504) que además cuesta puntos. Objeto `rateLimit{cost remaining resetAt}`. |
| 16 | Events that trigger workflows | https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows | `schedule`: intervalo mínimo **5 min**; **se retrasa en horas de alta carga (inicio de cada hora) y puede descartar trabajos**; solo corre en la rama por defecto; **en repos públicos se desactiva tras 60 días sin actividad**. `workflow_dispatch` se puede disparar por API. |
| 17 | Disable and enable workflows | https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows | Reactivación por UI, `gh workflow enable` o REST. **La página no define qué es "actividad del repositorio"** (ver S1). |
| 18 | Trigger a workflow | https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow | Los eventos creados con `GITHUB_TOKEN` no disparan workflows, **excepto `workflow_dispatch` y `repository_dispatch`** (el vigilante puede relanzar el build). |
| 19 | REST — Workflows | https://docs.github.com/en/rest/actions/workflows | `POST /repos/{o}/{r}/actions/workflows/{id}/dispatches` con `{"ref": "main"}`; `PUT …/enable` responde 204. |
| 20 | Permissions for fine-grained PATs | https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens | `dispatches` y `enable` requieren el permiso de repositorio **Actions: write** y nada más (token mínimo para cron-job.org). |
| 21 | Actions limits | https://docs.github.com/en/actions/reference/limits | 6 h por job en runners de GitHub; 20 jobs concurrentes en plan Free; caché de 10 GB por repo. |
| 22 | Dependency caching | https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching | La caché se **borra si no se usa en 7 días**; las claves son inmutables; `restore-keys` restaura la más reciente por prefijo. Base del almacenamiento de `state.json` entre ejecuciones. |
| 23 | GitHub Pages limits | https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits | Sitio publicado ≤ **1 GB**, ancho de banda blando **100 GB/mes**, despliegue que excede **10 min** expira, el límite blando de 10 builds/h **no aplica a workflows propios de Actions**, no es hosting de negocios. |
| 24 | Dependabot — ecosistemas | https://docs.github.com/en/code-security/dependabot/ecosystems-supported-by-dependabot/supported-ecosystems-and-repositories | Soporta `uv`, `npm`, `github-actions` y `docker`. |
| 25 | GitHub Terms of Service (D.5 y H) | https://docs.github.com/en/site-policy/github-terms/github-terms-of-service | Al hacer público un repo se concede a otros usuarios licencia para ver y bifurcar **dentro del servicio**; no autoriza a copiar su contenido fuera. API: prohibido abuso, compartir tokens para saltar límites y usar datos para spam. |
| 26 | GitHub Acceptable Use Policies §7 | https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies | «Scraping» es extraer con bots/crawlers; **la recolección vía API no es scraping**. Prohibido usar la información para spam o vender datos personales. Por eso todo el descubrimiento usa la API oficial. |
| 27 | Licensing a repository | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository | Sin licencia rigen los derechos de autor por defecto: nadie puede reproducir ni crear obras derivadas. Por eso **no se copia ningún README** y "sin licencia" es bandera de riesgo. |

### 1.3 Web, seguridad y estándares

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 28 | W3C — Content Security Policy Level 3 §3.3 | https://www.w3.org/TR/CSP3/ | Una CSP en `<meta>` **no admite** `report-uri`, `frame-ancestors` ni `sandbox`, ni el modo report-only. Lo demás (`default-src`, `script-src`, `connect-src`…) sí funciona por `<meta>`. |
| 29 | OWASP Top 10:2025 | https://top10.owasp.org/2025 | A02 Security Misconfiguration, A03 Software Supply Chain Failures, A05 Injection, A08 Software or Data Integrity Failures, A10 Mishandling of Exceptional Conditions: guían la revisión del sitio y del colector. |
| 30 | OWASP Top 10 for LLM Applications 2025 | https://genai.owasp.org/llm-top-10/ | LLM01 Prompt Injection y LLM03 Supply Chain: una skill es texto que entra al contexto del modelo y código que se ejecuta; base de las banderas `prompt-injection` y `unpinned-deps`. |

### 1.4 Fuentes sociales (solo señal, nunca recomendación)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 31 | HN Search API (Algolia) | https://hn.algolia.com/api | Sin clave. `search_by_date` con `tags`, `numericFilters=created_at_i>X`, `hitsPerPage`. **Límite: 10.000 peticiones/h por IP.** |
| 32 | Stack Exchange API — Throttles | https://api.stackexchange.com/docs/throttle | > 30 req/s por IP = bloqueo. Cuota diaria por IP (300 sin clave; con clave, cuota de la app, 10.000 por defecto). **Si la respuesta trae `backoff`, hay que esperar esos segundos antes de repetir el método.** No repetir la misma consulta más de una vez por minuto. |
| 33 | Stack Exchange API — Docs | https://api.stackexchange.com/docs | Las claves se piden registrando la app en Stack Apps; respuestas siempre comprimidas; filtros para recortar campos. |
| 34 | Stack Exchange API Terms of Use | https://stackoverflow.com/legal/api-terms-of-use | Toda app debe **indicar visualmente que Stack Exchange es la fuente**; si la indexan buscadores, cumplir las reglas de atribución de los términos. |
| 35 | Stack Overflow Public Network Terms | https://stackoverflow.com/legal/terms-of-service/public | El contenido público se licencia **CC BY-SA** y exige atribución. Base de la ficha de cada pregunta: título + enlace + autor + licencia. |
| 36 | Reddit Data API Wiki | https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki | Uso sujeto a la **Responsible Builder Policy** y a solicitud previa («To request, please contact us»). OAuth obligatorio, User-Agent `<plataforma>:<app>:<versión> (by /u/<usuario>)`, **100 QPM por client id** (promedio de 10 min), cabeceras `X-Ratelimit-*`. **Hay que borrar el contenido eliminado en Reddit** (recomiendan cada 48 h). |
| 37 | YouTube Data API — Getting started | https://developers.google.com/youtube/v3/getting-started | Requiere clave de API. 10.000 unidades/día para el resto de endpoints y una asignación aparte de **100 llamadas `search.list` por día**. |
| 38 | Bluesky — Rate limits | https://bsky.network/docs/rate-limits/ | PDS: 3.000 peticiones / 5 min por IP; `createSession` 30 / 5 min y 300/día por cuenta. `public.api.bsky.app` está cacheado y no admite autenticación. |
| 39 | Bluesky — Developer guidelines | https://bsky.network/docs/developer-guidelines/ | Prohibido el spam y las interacciones automatizadas; borrar contenido cuando se pida. Skillscope solo lee y cuenta. |
| 40 | Mastodon — Rate limits | https://docs.joinmastodon.org/api/rate-limits/ | 300 peticiones / 5 min por cuenta y por IP; cabeceras `X-RateLimit-*`. |
| 41 | Mastodon — Timelines | https://docs.joinmastodon.org/methods/timelines/ | `GET /api/v1/timelines/tag/:hashtag` es **público** salvo que la instancia lo desactive; `limit` ≤ 40; paginación con `min_id`. |
| 42 | Forem (DEV) API v1 | https://developers.forem.com/api/v1 | `GET /api/articles?tag=…&per_page=…` y `GET /api/articles/{id}` sin clave para lectura pública. |
| 43 | DEV Community Terms | https://dev.to/terms | La licencia del sitio es para visualización personal; no hablan de API. Por eso de DEV **solo se guardan conteos y enlaces** (ver S3). |
| 44 | X API — Pricing | https://docs.x.com/x-api/getting-started/pricing | Solo pago por uso (USD 0,005 por lectura) y créditos promocionales al registrar tarjeta: **no hay nivel gratuito utilizable → se descarta**. |
| 45 | Meta — IG Hashtag Search | https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-hashtag-search | Requiere la función *Instagram Public Content Access*, permiso `instagram_basic`, usuario vinculado a una página de Facebook y máximo 30 hashtags por semana. |
| 46 | Meta — Automated Data Collection Terms | https://www.facebook.com/legal/automated_data_collection_terms | **Prohibida la recolección automatizada sin permiso escrito expreso de Meta.** Sin cuentas de empresa propias ni revisión de la app → **Instagram y Facebook se descartan**. |
| 47 | cron-job.org — FAQ | https://cron-job.org/en/faq/ | Gratis, hasta una ejecución por minuto, admite POST con cuerpo y cabeceras propias, timeout de 30 s, avisos por correo y desactivación tras más de 25 fallos seguidos. |

### 1.5 Versiones de herramientas

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 48 | Node.js releases | https://nodejs.org/dist/index.json | LTS vigente: **Node 24 "Krypton" v24.21.0** (2026-09-07). Node 26 sigue como *Current*. |
| 49 | Python releases | https://www.python.org/downloads/ | 3.15.0 salió el 2026-10-09; 3.14.8 el 2026-09-30. |
| 50 | PyPI | https://pypi.org/ | numpy 2.5.4 tiene ruedas cp314 y cp315; **PyYAML 6.0.3 no tiene ruedas cp315** → se usa Python **3.14** (última estable con todas las ruedas del proyecto). Versiones exactas en `pyproject.toml` / `uv.lock`. |

### 1.6 Algoritmos (publicaciones revisadas por pares; DOI verificado en Crossref)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 51 | Deerwester et al. (1990), *Indexing by latent semantic analysis*, JASIS 41(6) — revisado por pares | https://doi.org/10.1002/(SICI)1097-4571(199009)41:6%3C391::AID-ASI1%3E3.0.CO;2-9 | Fundamento de los embeddings LSA (TF-IDF + SVD) usados en la búsqueda semántica sin modelo neuronal. |
| 52 | Robertson y Zaragoza (2009), *The Probabilistic Relevance Framework: BM25 and Beyond*, FnTIR — revisado por pares | https://doi.org/10.1561/1500000019 | Fórmula BM25 y valores típicos `k1 = 1,2`, `b = 0,75` del índice de texto. |
| 53 | Halko, Martinsson y Tropp (2011), *Finding structure with randomness*, SIAM Review 53(2) — revisado por pares | https://doi.org/10.1137/090771806 | SVD aleatorizada (sobremuestreo e iteraciones de potencia) para calcular LSA rápido en CI con numpy. |

### 1.7 Formatos de publicación (consultados el 2026-10-12)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 54 | JSON Feed 1.1 | https://www.jsonfeed.org/version/1.1/ | `version` = `https://jsonfeed.org/version/1.1`; obligatorios `version`, `title`, `items`; cada ítem exige `id` estable y al menos `content_text` o `content_html`; `language` es campo válido desde 1.1. Base de `feed.json`. |
| 55 | RSS 2.0 Specification (RSS Advisory Board) | https://www.rssboard.org/rss-specification | Canal con `title`, `link`, `description`; ítem con `title` o `description`; `pubDate` en RFC 822; `guid isPermaLink="false"` es solo identificador; `ttl` = minutos de caché. Base de `feed.xml` (`ttl` 60). |
| 56 | Sitemaps XML protocol | https://www.sitemaps.org/protocol.html | Máximo **50.000 URL y 50 MB** por archivo; espacio de nombres `http://www.sitemaps.org/schemas/sitemap/0.9`; `lastmod` en W3C Datetime (`AAAA-MM-DD` válido); escapar `&`, comillas y `<>`; línea `Sitemap:` en `robots.txt`. |
| 57 | schema.org — SoftwareSourceCode | https://schema.org/SoftwareSourceCode | `codeRepository` y `programmingLanguage` son propios del tipo; `license`, `dateModified`, `keywords`, `author`, `isPartOf` se heredan de CreativeWork. Base del JSON-LD de cada página estática. |

### 1.8 Operación de Actions (consultado el 2026-10-13)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 58 | Deployments and environments | https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments | Temporizador de espera de un entorno: entero de **1 a 43.200 min**; en planes Free/Pro/Team solo en **repos públicos**; «el tiempo de espera no cuenta como tiempo facturable». Base de la capa 2 (`next-later` espera 20 min en el entorno `cadence`). |

### 1.9 Redes, tendencias y búsqueda en vivo (consultado el 2026-10-13)

| # | Fuente | URL | Qué se tomó de aquí |
|---|---|---|---|
| 59 | REST — Starring (List stargazers y Get repository star history) | https://docs.github.com/en/rest/activity/starring | **Desde julio de 2026 el listado de stargazers queda limitado a administradores y colaboradores**, así que no sirve para repos ajenos. `GET /repos/{o}/{r}/stargazers/history` devuelve estrellas **agregadas por semana con conteo diario** y sin datos de personas (máx. 30 semanas por página). Base de «estrellas de la semana» y de «En tendencia». |
| 60 | robots.txt de hachyderm.io y fosstodon.org | https://hachyderm.io/robots.txt · https://fosstodon.org/robots.txt | Solo bloquean `GPTBot` y rutas internas (`/media_proxy/`, `/interact/`); la API de timelines públicas por etiqueta está permitida. Límites de la API de Mastodon: #40. |
| 61 | Lemmy — API y robots.txt de programming.dev y lemmy.world | https://join-lemmy.org/docs/contributors/04-api.html · https://programming.dev/robots.txt | La API v3 se lee sin cuenta y el límite es por IP. El robots.txt bloquea la interfaz `/search/` (no la API) y pide **`Crawl-delay: 60`**: una petición por instancia y por ejecución, con la consulta rotando entre ejecuciones. |
| 62 | Using CORS and JSONP to make cross-origin requests | https://docs.github.com/en/rest/using-the-rest-api/using-cors-and-jsonp-to-make-cross-origin-requests | «The REST API supports cross-origin resource sharing (CORS) for AJAX requests from any origin»; sin cuenta, la búsqueda permite 10 peticiones por minuto (#14). Base de «Buscar en todo GitHub» desde el navegador, solo al pulsar el botón. |
| 63 | robots.txt de api.bsky.app (AppView de Bluesky) | https://api.bsky.app/robots.txt | «Crawling the public parts of the API is allowed»; usa HTTP 429 para limitar y acepta «a handful» de peticiones concurrentes. `app.bsky.feed.searchPosts` responde **sin cuenta** en `api.bsky.app` (en `public.api.bsky.app` sigue en 403, E2). Bluesky ya no necesita credenciales. |
| 64 | robots.txt de infosec.exchange y mas.to | https://infosec.exchange/robots.txt · https://mas.to/robots.txt | Igual que #60: solo bloquean `GPTBot` y rutas internas; las timelines públicas por etiqueta están permitidas. |

**Descartadas tras revisar sus reglas (2026-10-13)**: Hashnode bloquea `/api/` en su robots.txt. Medium permite sus feeds RSS en robots.txt, pero sus términos no se pudieron leer (la página exige verificación de navegador), así que queda fuera hasta poder verificarlos. YouTube (clave de API) y Reddit (aprobación previa del Data API) siguen exigiendo credenciales por sus propias reglas.

**Descartadas tras revisar sus reglas**: Lobsters publica feeds RSS por etiqueta, pero su `robots.txt` responde `Disallow: /` a todo agente que no sea un buscador conocido, así que no se consulta. PyPI Stats pide no consultar en masa y cachear un día (https://pypistats.org/api/); queda como mejora futura solo para paquetes MCP de Python ya indexados.

## 2. Verificaciones empíricas propias (2026-10-12)

| # | Qué se probó | Resultado | Decisión |
|---|---|---|---|
| E1 | `curl -I` a sitios de GitHub Pages (pages.github.com, jekyllrb.com, diegofranciscog.github.io) y repetición con `If-None-Match` | Pages envía `ETag`, `Last-Modified`, `Cache-Control: max-age=600` y responde **304**. No envía CSP, X-Frame-Options ni X-Content-Type-Options y no hay forma de configurarlos. | El navegador sondea `index.json` con `If-None-Match`. La CSP va en `<meta>` (#28); Cloudflare gratis queda como opción documentada si se quieren las cabeceras completas. |
| E2 | `GET public.api.bsky.app/xrpc/app.bsky.feed.searchPosts` sin sesión | **403** | Bluesky solo funciona con cuenta propia y contraseña de aplicación → fuente opcional. |
| E3 | `GET mastodon.social/api/v1/timelines/tag/claudecode` | 200, `ETag`, `X-RateLimit-Limit: 300`, paginación `Link` | Fuente activa sin credenciales. |
| E4 | `GET dev.to/api/articles?tag=claudecode` | 200 sin clave | Fuente activa (solo conteos). |
| E5 | Stack Exchange `search/advanced` y `tags/claude-code/info` | `quota_max: 300` sin clave; 305 preguntas con «claude code», 33 con la etiqueta `claude-code` | La demanda existe pero es pequeña: se consulta cada 2 h y se respeta `backoff`. |
| E6 | Búsqueda de GitHub con `OR` entre `topic:` | **422**: los operadores lógicos no aplican a calificadores | Una consulta por topic; para > 1.000 resultados se parte por rango de fechas `created:`. |
| E7 | `total_count` por topic | `claude-code` 89.740 · `mcp` 93.420 · `agent-skills` 31.485 · `claude-skills` 10.832 · `claude-code-plugin` 9.673 · `claude-skill` 5.985 · `claude-plugin` 2.656 · `claude-code-skills` 2.120 · `skill-md` 1.756 · `claude-code-plugins` 722 · `claude-code-hooks` 615 · `claude-code-marketplace` 473 | El universo supera con creces 3.000 repos: el colector es **incremental** y prioriza. |
| E8 | Búsqueda de código `filename:SKILL.md`, `marketplace.json` y `plugin.json` en `.claude-plugin` | ~5,78 M archivos SKILL.md (con forks y copias), 39.424 marketplaces, 28.224 manifiestos de plugin | Imposible recorrer todo en una ejecución: presupuesto por ejecución + cursores persistentes. |
| E9 | Sondeo GraphQL de 600 repos con más estrellas de esos topics (archivos clave por `object(expression:)`) | 304 con `marketplace.json`, 159 con skills, 19 con `plugin.json`, 21 listas awesome, 95 sin artefactos en rutas estándar | El analizador debe mirar el **árbol completo**, no solo rutas fijas. Con esto se armó la lista semilla. |
| E10 | Consulta GraphQL de metadatos (estrellas, issues, release, CI, commits en 30 días, árbol) para 4 repos | `cost: 1` | Los metadatos se refrescan por lotes de 40–50 repos por punto. |
| E11 | Primer build en Actions (2026-10-13) y medición de la consulta de metadatos con token personal: 40 repos de la semilla más grandes, 3 tamaños de consulta | En Actions la primera consulta GraphQL tras 29 búsquedas recibió `429` con `retry-after` largo y el build publicó 0 repos. 40 repos por consulta tardan ~10 s y a veces dan `502` (tope de 10 s de GraphQL), con o sin `history`; 10 repos tardan ~3 s | Lotes de 10 que se parten por la mitad si fallan, pausa de 0,5 × tiempo de respuesta tras cada llamada a GitHub (el CPU se estima por el tiempo de respuesta, #12), búsqueda amplia diferida con cola ≥ 300 y 60 s reservados para las redes. Resultado local desde cero: 40 repos en el 1.er build y 98 en el 2.º. |
| E12 | Pruebas en vivo del 2026-10-13: Lemmy y tres instancias de Mastodon sin cuenta, historial de estrellas de repos ajenos y build completo en local con token personal | Lemmy y Mastodon responden 200 con publicaciones del día. El historial de estrellas funciona para repos ajenos (1 llamada `core`). El build midió 40 repos y la lista «En tendencia» pasó de 2 a 41. Un repo pasó de ~150 estrellas/semana a > 40.000/día: el 95 % de sus estrellas llegó en 7 días | Medir tendencias antes del análisis (no las deja sin tiempo). Mostrar «más de la mitad de sus estrellas llegó esta semana» como dato, sin acusar, porque la popularidad se puede inflar. |
| E13 | Build en Actions colgado 10 min (2026-10-13 20:15) y prueba de todas las expresiones regulares (89) con entradas hostiles de 20.000 caracteres, cada una en un proceso aparte | Solo `SCRIPT_REF` (nombres de script en comandos de hooks/MCP) superó 4 s: su prefijo perezoso `[\w./${}"'-]*?` se solapaba con `[\w.-]+` y el tiempo crecía de forma cuadrática. Descargar repos completos (`/tarball`) se descartó: de 15 repos reales, 12 pesaban megas o gigas (hasta 854 MB) | `SCRIPT_REF` reescrita con borde de palabra y longitud acotada (mismos resultados, 3 ms con 200.000 caracteres); prueba permanente `tests/unit/test_regex_safety.py`; el paso del pipeline falla a los 8 min en vez de cancelar el job, así la cadena de builds no se corta. |
| E14 | Auditoría del índice en vivo (695 repos, 2026-10-13 22:17): evidencia de los repos de riesgo alto con más estrellas | «Código ofuscado» marcaba texto largo en lenguaje natural dentro de archivos JS (prompts), líneas de shell largas y `base64` usado para **codificar** código visible; scripts de prueba con guion (`send-imessage-test.sh`) contaban como ejecución sin explicar | Analizador v2: línea «empaquetada» = > 1.000 caracteres y < 5 % de espacios; `eval` solo cuenta si **decodifica**; `test-`/`-test.` son pruebas. Los 695 repos se reanalizan de a 40 por build. |
| E15 | Sonda del buscador sobre el índice en vivo (782 repos, 2026-10-13) | Consultas sin respuesta real (`facturación electrónica Ecuador`) devolvían 8 «Se le parece» con `sem` 0,42-0,45 y ninguna palabra en común; consultas con respuesta (`base de datos postgres`) daban `sem` 0,60-0,70 aun sin palabras compartidas | «Se le parece» exige `sem ≥ 0,30` con 1/3 de las palabras, o `sem ≥ 0,55` sin ellas; la búsqueda entre candidatos se activa con menos de 3 exactos. Prueba fija en `web/test/search.test.ts`. |

## 3. Supuestos (no verificables en fuente oficial) — avisados al usuario

| # | Supuesto | Por qué no se pudo verificar | Mitigación |
|---|---|---|---|
| S1 | Un push a una rama distinta de `main` y/o reactivar el workflow por API cuentan como «actividad» para la regla de 60 días. | #16 y #17 no definen «actividad del repositorio». | Tres capas: cron interno, disparo externo cada 30 min y workflow mensual que reactiva `build.yml` y empuja un commit vacío a la rama `keepalive` (no toca `main`). Alerta si pasan 90 min sin build. |
| S2 | La búsqueda de código funciona con el `GITHUB_TOKEN` de Actions. | #14 solo dice «requiere autenticación». | Si responde 401/403/422 el colector marca `code_search: unavailable` y sigue con topics y listas. Con un token personal fino funciona (verificado con `gh`). |
| S3 | Contar menciones con la API pública de DEV no es «exhibición pública» de sus materiales. | #43 no menciona la API. | De DEV no se guarda ni muestra texto: solo número de menciones por repo y día. |
| S4 | La API de descargas de npm (`api.npmjs.org/downloads`) tolera ~30 consultas por ejecución. | No publica límites. | Presupuesto de 30 por ejecución y caché de 24 h por paquete. |
| S5 | El texto completo de la Responsible Builder Policy de Reddit. | La página oficial responde 403 a lectores automáticos; solo se leyó el anuncio en espejos de r/redditdev (11-nov-2025). La wiki oficial (#36) confirma que se requiere solicitud. | Reddit queda **apagado** salvo que existan credenciales aprobadas; aun así solo se guardan conteos por tema (nada de títulos, autores ni IDs). |
| S6 | GitHub Pages no permite cabeceras HTTP propias. | No hay página oficial que lo diga; se verificó empíricamente (E1). | CSP por `<meta>`; `docker compose` sirve el sitio con nginx y cabeceras completas como referencia. |
| S7 | Tras un despliegue, la CDN de Pages puede servir `index.json` hasta 10 min viejo (`max-age=600`). | El purgado en despliegue no está documentado. | La web muestra la hora real del build, no la de descarga. |
| S8 | La clave de Stack Exchange no es secreta. | La documentación no lo dice explícitamente. | Igual se guarda en GitHub Secrets. |
