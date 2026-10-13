# Algoritmo de Skillscope (público y auditable)

Este documento describe **exactamente** cómo se clasifica, puntúa y busca cada repositorio. Las constantes viven en un solo lugar del código (`analyzer/scoring.py`, `analyzer/lexicon.py`, `indexer/embeddings.py` y `web/src/search/`) y las pruebas numéricas de `tests/unit/test_scoring.py` fijan cada fórmula: si alguien cambia un número, una prueba falla.

Notación: `log` es logaritmo natural salvo que se indique `log2` o `log10`; `clamp(x, a, b)` limita `x` al intervalo `[a, b]`; `sat(x) = min(1, x)`.

## 1. Puntaje total

```
total = round( clamp( Q + M + A + S + U − R, 0, 100 ) )
```

| Componente | Máx. | Idea |
|---|---|---|
| Q · Calidad del paquete | 25 | ¿El formato es válido y está bien documentado? |
| M · Mantenimiento | 20 | ¿Alguien lo cuida? |
| A · Adopción | 20 | ¿Lo usa la gente? |
| S · Interés social | 15 | ¿Se habla de esto **ahora**? |
| U · Utilidad declarada | 20 | ¿Resuelve lo que la gente pregunta? |
| R · Penalización por riesgo | 25 | ¿Qué puede salir mal al instalarlo? |

Cada ficha muestra el desglose factor por factor con el valor medido y los puntos que dio.

### 1.1 Calidad del paquete (Q, 25)

| Factor | Puntos | Fórmula |
|---|---|---|
| q1 Formato válido | 6 | `6 · válidos / analizables` sobre SKILL.md, `plugin.json`, `marketplace.json` y agentes. Reglas R1–R4 de [modelo-datos.md](modelo-datos.md). Sin artefactos: 0. |
| q2 La descripción dice CUÁNDO usarla | 5 | `5 · (descripciones con disparador / descripciones)`. Disparadores: «use when», «use this when», «when the user», «when you need», «when working with», «use for», «triggers on», «úsala cuando», «usar cuando», «cuando el usuario», «cuando necesites». Si el repo no tiene skills ni agentes: 2,5 si hay alguna descripción, si no 0. |
| q3 Archivo breve con detalle aparte | 4 | `3 · (SKILL.md con ≤ 500 líneas / SKILL.md)` + 1 si alguna skill usa archivos de apoyo (`references/`, `scripts/`, `assets/` u otros `.md`) o todas tienen ≤ 200 líneas. Sin skills: 2. |
| q4 Ejemplos | 3 | 3 si el README o un SKILL.md tiene una sección «example/ejemplo/usage/uso/demo» o existe `examples/`. |
| q5 README con instalación | 3 | 3 si el README explica la instalación (`/plugin`, `claude plugin`, `~/.claude/skills`, «install», «instalación»); 1 si hay README sin eso; 0 sin README. |
| q6 Licencia declarada | 2 | 2 con SPDX reconocido; 1 con `NOASSERTION` (hay licencia, no estándar); 0 sin licencia. |
| q7 Validador o pruebas | 2 | 2 si hay `tests/`, `test/`, `__tests__/`, `spec/`, `evals/`, archivos `*.test.*`/`*_test.*` o workflows de CI. |

### 1.2 Mantenimiento (M, 20)

| Factor | Puntos | Fórmula |
|---|---|---|
| m1 Recencia del último commit | 10 | `10 · 2^(−días / 90)` (vida media de 90 días). Repos archivados: 0. |
| m2 Releases recientes | 3 | 3 si la última release tiene ≤ 180 días; 1,5 si ≤ 365; si no, 0. Archivados: 0. |
| m3 Issues cerrados | 4 | `4 · (cerrados + 1) / (abiertos + cerrados + 2)` (suavizado de Laplace: un repo sin issues obtiene 2). |
| m4 CI en verde | 3 | Estado combinado de checks del último commit: `SUCCESS` 3 · `PENDING`/`EXPECTED` 1,5 · sin checks, `FAILURE` o `ERROR` 0. |

### 1.3 Adopción (A, 20)

| Factor | Puntos | Fórmula |
|---|---|---|
| a1 Estrellas (escala logarítmica) | 10 | `10 · sat( log10(1 + estrellas) / log10(10 001) )` → 10.000 estrellas = máximo. |
| a2 Forks | 3 | `3 · sat( log10(1 + forks) / log10(1 001) )` |
| a3 Colecciones | 5 | `5 · sat( log2(1 + n) / log2(9) )`, `n` = marketplaces y listas awesome distintas que lo incluyen. |
| a4 Descargas | 2 | Si publica paquete npm: `2 · sat( log10(1 + descargas_mes) / log10(10 001) )`. Si no publica paquete, `A = (a1 + a2 + a3) · 20 / 18` para no castigar a quien no publica. |

### 1.4 Interés social (S, 15)

Cada mención `i` de la fuente `f`, con antigüedad `d` días y `e` interacciones (puntos, votos, reacciones), pesa:

```
w_i = peso_f · 2^(−d / 30) · (1 + sat( log10(1 + e) / 3 ))
peso: Hacker News 1,0 · YouTube 0,9 · Reddit 0,8 · Stack Exchange 0,7 · DEV 0,6 · Mastodon 0,5 · Bluesky 0,5
S = 15 · sat( log2(1 + Σ w_i) / log2(21) )        (solo menciones de los últimos 180 días)
```

Una mención de hoy vale el doble que una de hace 30 días y 64 veces más que una de hace medio año. Una mención solo cuenta si enlaza explícitamente `github.com/owner/repo` (sin coincidencias por nombre, para evitar falsos positivos).

**Media móvil de 30 días** (lista «Más mencionadas»): `menciones_30d = Σ peso_f · (1 + sat(log10(1 + e)/3))` de las menciones de los últimos 30 días, sin decaimiento.

### 1.5 Utilidad declarada (U, 20)

Corpus de demanda: preguntas de Stack Exchange del último año (sin respuesta pesan 1,0; con respuesta 0,5) y conteos por tema de Reddit (0,8 por petición) cuando esa fuente está activa.

| Factor | Puntos | Fórmula |
|---|---|---|
| u1 Preguntas reales que responde | 12 | Una pregunta `q` «coincide» con el repo si el coseno LSA (§3.2) entre su título + etiquetas y el repo es ≥ 0,35 **y** comparten al menos una palabra clave. `u1 = 12 · sat( log2(1 + Σ peso_q) / log2(11) )`. |
| u2 Demanda de su categoría | 8 | `8 · demanda_categoría / max(demanda por categoría)` |

Si en el build no hay ningún dato de demanda, `U = 10` (neutral) y el desglose lo dice con la etiqueta «sin datos de demanda».

### 1.6 Penalización por riesgo (R, máximo 25)

`R = min(25, Σ penalización de cada bandera distinta)` con el catálogo de [modelo-datos.md §3](modelo-datos.md#3-catálogos). Cada bandera guarda hasta 3 evidencias `{archivo, línea, fragmento ≤ 100 caracteres}` para que cualquiera pueda comprobarla en el repo original.

Qué archivos se revisan: los `SKILL.md`, comandos y agentes (`.md`), `hooks.json`, `.claude/settings.json`, `.mcp.json`, `plugin.json`, `marketplace.json`, el README y hasta 10 scripts (`.sh`, `.py`, `.js`, `.ts`, `.ps1`…) de máximo 64 KB que estén dentro de una carpeta de skill, en `bin/` o en `hooks/` de un plugin. Las carpetas `test(s)/`, `fixtures/`, `testdata/` y `docs/` no cuentan como artefactos.

Reglas que evitan falsos positivos (cada una tiene su prueba en `tests/unit/test_risk.py`):

- **Ejecución**: cuenta lo que el agente puede correr (scripts de carpetas de skills y `bin/`, comandos de hooks, servidores MCP stdio y `` !`cmd` ``). Los scripts de compilación del repositorio fuera de esas carpetas no cuentan. Un script está «explicado» si el README o un `.md` del artefacto nombra su archivo; si se nombra al menos un script de una carpeta, sus módulos auxiliares también cuentan como explicados. Los archivos de prueba (`test_*`, `*_test.*`, `*.test.*`) se ignoran.
- **Comentarios**: en scripts se ignoran las líneas de comentario (`#`, `//`).
- **Citas**: una frase de inyección entre comillas (por ejemplo, una skill que explica cómo defenderse de «ignore previous instructions») no se marca.
- **Salvaguardas**: «nunca pidas al usuario su token» no es una petición de credenciales.
- **Mensajes**: `pip install x` dentro de un `print(...)` o de una cadena no es una instalación.
- **Procesar datos**: `curl … | python3 -c "…"` lee JSON, no ejecuta lo descargado.

Nivel: 0 sin banderas · 1 bajo (1–5) · 2 medio (6–12) · 3 alto (≥ 13).

Validación con 115 repositorios reales (2026-10-12): tras estas reglas, 33 sin banderas, 21 nivel bajo, 25 medio y 36 alto; las banderas más frecuentes fueron `exec-unexplained` (47), `broad-permissions` (30) y `downloads-binary` (22). Antes de estas reglas `exec-unexplained` aparecía en 93 repos y `requests-credentials` en 34.

## 2. Listas derivadas

| Lista | Criterio | Desempate |
|---|---|---|
| Más usadas | A descendente | estrellas |
| Más mencionadas | `menciones_30d` > 0 descendente | S |
| Nuevas | Creados en GitHub hace ≤ 30 días, total descendente | estrellas |
| En tendencia | `0,7 · crec_estrellas + 0,3 · crec_menciones` > 0, con `crec_estrellas = g7 / (estrellas − g7 + 20)`, donde `g7` son las estrellas de los últimos 7 días según el historial de estrellas de GitHub (#59) medido en los últimos 2 días; sin esa medición, `(e_hoy − e_hace7) / (e_hace7 + 20)` con las instantáneas propias (el día más antiguo mientras no haya 7 días). `crec_menciones = max(0, (m_7d − m_7d_previos) / (m_7d_previos + 3))`. Si `g7 ≥ 1.000` y supera la mitad de las estrellas, la ficha dice «más de la mitad de sus estrellas llegó esta semana». | total |
| Más útiles | `U + Q − R` descendente | total |
| Más necesarias | Por categoría: `demanda / (1 + oferta)`, oferta = repos de la categoría con total ≥ 50. | demanda |
| Más seguras | `R` ascendente entre repos con artefactos y total ≥ 40 | total |
| Más riesgosas | `R` descendente | estrellas |

**Huecos del ecosistema**: las preguntas de demanda se agrupan de forma voraz y determinista (en orden de fecha, cada pregunta entra al tema más parecido si el coseno con su centroide es ≥ 0,3; si no, abre un tema nuevo). Se agrupan con el vocabulario TF-IDF **de las propias preguntas**, no con el espacio LSA de los repos: un hueco es justo un tema que los repos no cubren, así que su vocabulario no podría representarlo. Solo cuenta como demanda una pregunta **sobre trabajar con un agente**: con una etiqueta de agente o un término de agente en el título (la búsqueda libre de Stack Exchange también devuelve preguntas ajenas, como una de constructores de copia en C++). Los **asuntos** del tema son sus etiquetas **completas** (curadas por la comunidad), sin las que solo dicen que hay un agente de por medio (`claude-code`, `ai`, `llm`…); si no hay etiquetas, sus 3 palabras más frecuentes. Un asunto es **específico** salvo que los datos de ese build digan que es contexto: lo cubre más de 1/4 de los repos (`python`, `vs-code`) o aparece en más del 10 % de los temas (`advice`, `best-practices`); con menos de 20 repos o temas no se aplica esta regla. **Oferta** = repos con total ≥ 40 que contienen al menos la mitad de los asuntos específicos (una skill genérica de revisión no cubre «revisión de ABAP»: necesita también `abap`). **HUECO** = demanda ponderada ≥ 2, al menos un asunto específico y oferta = 0. Con los datos reales del 2026-10-13 la regla anterior (palabras sueltas: `vs-code` → `vs` + `code`) daba 0 huecos porque «code» está en casi todos los repos; la actual encuentra Spring AI, OAuth de Figma en MCP y cliente MCP de Notion.

## 3. Clasificación, resumen y búsqueda

### 3.1 Normalización de texto (idéntica en Python y TypeScript)

1. Unicode NFKD, quitar tildes, minúsculas.
2. Frases fijas a término canónico: «pull request(s)» → `pr`, «code review» → `review`, «base de datos» → `database`, «hoja de cálculo» → `spreadsheet`, «inteligencia artificial» → `ai`, etc.
3. Separar por caracteres no alfanuméricos; descartar tokens de 1 carácter y números puros.
4. Quitar palabras vacías en español e inglés.
5. Traducir español → inglés con el léxico bilingüe (`revisar` → `review`, `pruebas` → `test`, `seguridad` → `security`…), porque casi todo el ecosistema está en inglés.
6. Lematizador ligero por sufijos (`-ies` → `-y`, `-ing`, `-ed`, `-es`, `-s`).

Un archivo de casos compartido (`data/samples/tokenize-cases.json`) se prueba con pytest **y** con Vitest para garantizar que ambos lados producen los mismos tokens.

### 3.2 Embeddings latentes (LSA) cuantizados

En CI: matriz TF-IDF de documentos (`tf = 1 + log tf`, `idf = log((N + 1)/(df + 1)) + 1`, vocabulario de términos con `df ≥ 2`, `df ≤ 0,5·N`, máximo 5.000) y SVD aleatorizada de rango 64 (Halko, Martinsson y Tropp, 2011; sobremuestreo 10, 2 iteraciones de potencia, semilla 42). Vectores de documento = `U·Σ` normalizados y cuantizados a int8 (`round(127·v)`); vectores de término = filas de `V` con escala por término (`max|v| / 127`).

En el navegador: vector de la consulta = `Σ peso_tf-idf(t) · V_t` y coseno contra los documentos. Es la técnica clásica de *Latent Semantic Analysis* (Deerwester et al., 1990): captura co-ocurrencias («pull request» ↔ «code review») **sin descargar un modelo neuronal** de decenas de MB, sin servidor y sin claves.

### 3.3 Búsqueda híbrida por necesidad

1. Consulta validada: máximo 200 caracteres, sin caracteres de control.
2. **BM25** (Robertson y Zaragoza, 2009; `k1 = 1,2`, `b = 0,75`) sobre nombre (×3), palabras clave (×2), resumen, tipo y categoría.
3. **Semántica**: coseno LSA.
4. Mezcla: `final = 0,45 · sem + 0,35 · lex + 0,20 · total/100`, con `lex = BM25 / BM25 máximo` y `sem = max(0, coseno)`.
5. Bloques:
   - **Resuelve exactamente eso**: `lex ≥ 0,5`, `sem ≥ 0,25` y **cobertura ≥ 0,5** (hasta 8).
   - **Se le parece**: el resto con cobertura ≥ 1/3 y `sem ≥ 0,30`, o `sem ≥ 0,55` aunque no comparta palabras (hasta 8). Mientras el modelo semántico no ha cargado: cobertura ≥ 0,5 y `lex ≥ 0,2`. Umbrales medidos sobre el índice en vivo (E15): con multilingual-e5 cualquier par de textos técnicos ronda `sem` 0,40-0,45, así que el umbral anterior (0,4) mostraba ruido y ocultaba la búsqueda «más allá del índice».

   *Cobertura* = términos distintos de la consulta que contiene el repo ÷ términos de la consulta. Hace falta porque BM25 se normaliza por el mejor resultado: sin cobertura, una consulta que solo comparte una palabra genérica («trabajo») produciría un 1,0 falso. Lo detectó la prueba end-to-end «migrar trabajos COBOL», que ahora devuelve correctamente «nadie ha publicado una skill para esto».
   - **Se usan junto con eso**: repos que comparten colecciones con los 3 primeros resultados (hasta 6).
6. **Más allá del índice**: si «Resuelve exactamente eso» tiene menos de 3 resultados, se busca también entre los repos ya descubiertos y aún sin analizar (`data/candidates.json`, hasta 5.000 por prioridad): BM25 sobre nombre (×3), temas (×2) y descripción, cobertura ≥ 0,5, orden `0,8 · BM25 normalizado + 0,2 · min(1, log10(1 + estrellas) / 5)`. Además se ofrece «Buscar en todo GitHub», que consulta la API pública de búsqueda **solo si el lector pulsa el botón** (#62). Cada resultado sin analizar enlaza a un formulario que lo pone primero en la cola del siguiente build.
7. Si los dos primeros bloques quedan vacíos: «Nadie ha publicado una skill para esto» con enlace a la plantilla oficial para crearla.

### 3.4 Categoría y causa

Léxicos ponderados por categoría y causa (`analyzer/lexicon.py`). Para cada repo: `puntaje_c = Σ peso(término) · apariciones` sobre nombre (×3), topics (×2), descripciones de skills y palabras clave (×1). Gana la categoría con mayor puntaje; las dos siguientes con ≥ 50 % del ganador quedan como secundarias. Sin coincidencias: `development` (categoría) y `automate` (causa). Las palabras que decidieron quedan en la ficha.

### 3.5 Resumen propio («Qué hace» y «Cuándo usarla»)

Se compone con plantillas a partir de **hechos medidos** (tipo, categoría, causa, cantidad de skills/comandos/agentes/hooks, herramientas declaradas, licencia, actividad y palabras clave sueltas), nunca con oraciones del README. Un guardián (`analyzer/copyguard.py`) compara cada resumen contra el README y las descripciones originales y lo rechaza si comparte **16 o más palabras seguidas**; la prueba de aceptación recorre todos los resúmenes generados.

## 4. Reproducibilidad

- Todas las respuestas crudas se guardan con hash SHA-256 y fecha en `data/raw/`.
- El modo `--offline` reconstruye el índice completo desde `data/samples/` sin red (lo usan las pruebas y `docker compose`).
- Semillas fijas (SVD = 42), orden estable por `id` en todos los empates.

## Referencias

- Deerwester, S., Dumais, S., Furnas, G., Landauer, T., Harshman, R. (1990). *Indexing by latent semantic analysis*. Journal of the American Society for Information Science, 41(6), 391–407. DOI: 10.1002/(SICI)1097-4571(199009)41:6<391::AID-ASI1>3.0.CO;2-9
- Robertson, S., Zaragoza, H. (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. Foundations and Trends in Information Retrieval. DOI: 10.1561/1500000019
- Halko, N., Martinsson, P.-G., Tropp, J. A. (2011). *Finding structure with randomness: Probabilistic algorithms for constructing approximate matrix decompositions*. SIAM Review, 53(2), 217–288. DOI: 10.1137/090771806
