"""Risk flags with evidence (catalog in docs/modelo-datos.md §3).

A skill or plugin is text that enters the model's context and code that runs on the user's
machine (docs #7, OWASP LLM01/LLM03 #30). Every flag keeps the file, line and a short
fragment so anyone can verify it in the original repository.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from analyzer.model import Artifact, Evidence, MarketplaceEntry, RiskFlag

CATALOG: dict[str, tuple[str, int, str, str]] = {
    "prompt-injection": (
        "high",
        10,
        "Posible inyección de instrucciones",
        "El texto que entra al contexto del agente intenta anular instrucciones o esconder "
        "acciones al usuario.",
    ),
    "exec-unexplained": (
        "high",
        8,
        "Ejecuta comandos sin explicarlos",
        "Hooks, scripts o servidores que corren en tu máquina sin que la documentación los nombre.",
    ),
    "downloads-binary": (
        "high",
        8,
        "Descarga y ejecuta código remoto",
        "Baja scripts o binarios de internet y los ejecuta sin verificar su integridad.",
    ),
    "requests-credentials": (
        "medium",
        6,
        "Pide o lee credenciales",
        "Solicita contraseñas, claves o tokens, o lee archivos de credenciales locales.",
    ),
    "obfuscated-code": (
        "medium",
        6,
        "Código ofuscado",
        "Ejecuta texto codificado (base64, eval) o código minificado difícil de auditar.",
    ),
    "network-exfil": (
        "medium",
        6,
        "Envía datos a servidores externos",
        "Manda contenido de tu máquina a una URL externa desde un script o hook.",
    ),
    "broad-permissions": (
        "medium",
        5,
        "Permisos amplios",
        "Concede Bash sin restricciones o se salta las confirmaciones de permisos.",
    ),
    "no-license": (
        "medium",
        4,
        "Sin licencia",
        "Sin licencia rigen los derechos de autor por defecto: no se puede reutilizar legalmente.",
    ),
    "unpinned-deps": (
        "medium",
        4,
        "Dependencias sin versión fija",
        "Instala paquetes o plugins sin fijar versión: lo que se ejecuta puede cambiar sin aviso.",
    ),
    "exec-declared": (
        "low",
        2,
        "Ejecuta comandos (documentados)",
        "Corre scripts, hooks o servidores en tu máquina; la documentación los nombra.",
    ),
}

INJECTION_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier|system)\s+"
        r"(instructions|prompts?|messages|rules)",
        r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|system)\s+"
        r"(instructions|prompts?|rules)",
        r"(do\s+not|don'?t|never)\s+(tell|inform|reveal\s+to|mention\s+to|show)\s+the\s+user\s+"
        r"(about|that\s+you|what\s+you|this|these|the\s+(command|script|step|change|file)s?)\b",
        r"(hide|conceal)\s+(this|these|it)\s+from\s+the\s+user",
        r"you\s+are\s+now\s+(in\s+)?(developer|dan|jailbreak|unrestricted)",
        r"override\s+(the\s+)?(system|safety)\s+(prompt|instructions|rules)",
        r"ignora\s+(todas\s+)?las\s+instrucciones\s+(anteriores|previas)",
        r"no\s+(le\s+)?(digas|informes|muestres)\s+(nada\s+)?al\s+usuario",
    )
]
INVISIBLE = re.compile(
    "[\u200b\u200c\u200d\u2060\u202a-\u202e\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.S)
COMMENT_IMPERATIVE = re.compile(
    r"\b(ignore|disregard)\b[^>]{0,60}\b(instructions?|prompts?|rules)\b"
    r"|\b(do\s+not|don'?t|never)\s+(tell|inform|mention)\b"
    r"|\b(run|execute)\s+(curl|wget|bash|sh|python3?|node|rm|powershell|iex)\b"
    r"|\b(curl|wget)\s+-?\S*\s*https?://|\bsystem\s+prompt\b"
    r"|\bsend\b[^>]{0,60}\bto\s+https?://",
    re.I,
)
BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")

DOWNLOAD_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
        r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(python3?|node|perl|ruby)\b(?!\s+-[cem]\b)",
        r"\b(iwr|irm|invoke-webrequest|invoke-restmethod)\b[^\n|]*\|\s*(iex|invoke-expression)\b",
        r"\b(curl|wget)\b[^\n]*\s-(o|O)\s*\S+\.(exe|bin|zip|tar\.gz|tgz|dmg|msi|appimage|deb|rpm|run)\b",
        r"https://\S+\.(mcpb|dxt)\b",
    )
]
CREDENTIAL_TEXT = re.compile(
    r"\b(paste|enter|provide|give\s+me|send|share|type|pega|ingresa|escribe|envia)\s+(me\s+)?"
    r"(your|their|the\s+user'?s|tu|su|sus)\s+[^.\n]{0,30}\b(password|passphrase|api[\s_-]?key|"
    r"access\s+token|token|secret|credentials?|private\s+key|ssh\s+key|contrasena|contraseña|clave)\b",
    re.I,
)
NEGATION = re.compile(r"\b(never|don'?t|do\s+not|nunca|no)\b[^.\n]{0,25}$", re.I)
CREDENTIAL_FILES = re.compile(
    r"(~|\$HOME|%USERPROFILE%)/\.(ssh/id_|aws/credentials|netrc|git-credentials|docker/config\.json)"
    r"|\bcredentials\s+file\b|/\.config/[^\s]*credential|\bsecurity\s+find-generic-password\b",
    re.I,
)
CREDENTIAL_READS = re.compile(
    r"\b(cat|less|head|tail|open|read_text|readFileSync|readFile|Get-Content|source)\b[^\n]{0,40}"
    r"(\.ssh/id_|\.aws/credentials|\.netrc|\.git-credentials|\.docker/config\.json|keychain)"
    r"|\bsecurity\s+find-generic-password\b",
    re.I,
)
SECRET_LIKE = re.compile(
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}"
    r"|(?:AKIA|ASIA)[0-9A-Z]{16}|xox[abprs]-[0-9A-Za-z-]{10,}|sk-[A-Za-z0-9_-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
QUOTES = frozenset("\"'“”‘’«»`(")
OBFUSCATION = [
    re.compile(p, re.I)
    for p in (
        r"\beval\b[^\n]*(base64|atob|b64decode|fromcharcode|\\x[0-9a-f]{2})",
        r"base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh\b",
        r"\bexec\s*\(\s*(base64\.)?b64decode",
        r"\bexec\s*\(\s*compile\s*\(",
    )
]
EXFIL = [
    re.compile(p, re.I)
    for p in (
        r"\bcurl\b[^\n]*\s(-d|--data(-binary|-raw|-urlencode)?|-F|--form|-T|--upload-file)\s"
        r"[^\n]*https?://(?!localhost|127\.0\.0\.1)",
        r"hooks\.slack\.com/services|discord(app)?\.com/api/webhooks",
        r"requests\.post\(\s*['\"]https?://(?!localhost|127\.0\.0\.1)",
        r"\bnc\s+-e\b|/dev/tcp/",
    )
]
SKIP_PERMISSIONS = re.compile(
    r"--dangerously-skip-permissions|\"defaultMode\"\s*:\s*\"bypassPermissions\""
)
NPX_LIKE = re.compile(r"\b(npx|bunx|pnpx|uvx|pipx\s+run)\s+([^\n;&|]+)")
PIP_INSTALL = re.compile(r"\bpip3?\s+install\s+([^\n;&|]+)")
PACKAGE_SPEC = re.compile(r"^(@[\w.-]+/)?[A-Za-z0-9][\w.-]*(@[\w.^~<>=*-]+)?$")
TEST_SCRIPT = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.)")
SCRIPT_REF = re.compile(r"[\w./${}\"'-]*?([\w.-]+\.(?:sh|bash|py|js|mjs|cjs|ts|ps1|rb))\b")


@dataclass(slots=True)
class RiskInput:
    files: dict[str, str]
    readme: str
    markdown_paths: list[str]  # SKILL.md, commands, agents
    script_paths: list[str]  # scanned for dangerous commands
    exec_paths: list[str]  # scripts the agent can run (skill folders and bin/)
    hook_commands: list[tuple[str, str]]  # (file, command)
    mcp_servers: list[tuple[str, dict[str, Any]]]  # (file, server config)
    artifacts: list[Artifact]
    license: str | None
    marketplace_entries: list[MarketplaceEntry] = field(default_factory=list)
    marketplace_path: str | None = None


def visible(text: str) -> str:
    """Make invisible characters explicit, hide credentials and keep the fragment short.

    Evidence is republished on the site, so a token leaked in someone else's repository
    must never be copied into it.
    """
    shown = INVISIBLE.sub(lambda m: f"⟨U+{ord(m.group(0)):04X}⟩", text)
    shown = SECRET_LIKE.sub("[secreto oculto]", shown)
    shown = re.sub(r"\s+", " ", shown).strip()
    return shown if len(shown) <= 100 else shown[:99] + "…"


def _matches(path: str, text: str, patterns: Iterable[re.Pattern[str]]) -> list[Evidence]:
    patterns = [p for p in patterns if p.search(text)]  # fast reject on the whole text
    if not patterns:
        return []
    found: list[Evidence] = []
    for number, line in enumerate(text.splitlines(), 1):
        if any(p.search(line) for p in patterns):
            found.append(Evidence(path, number, visible(line)))
    return found


def _code_matches(path: str, text: str, patterns: Iterable[re.Pattern[str]]) -> list[Evidence]:
    """Like ``_matches`` but ignores comment lines (``#``, ``//``) in scripts."""
    patterns = [p for p in patterns if p.search(text)]
    if not patterns:
        return []
    found: list[Evidence] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(("//", "REM ")) or (
            stripped.startswith("#") and not stripped.startswith("#!")
        ):
            continue
        if any(p.search(line) for p in patterns):
            found.append(Evidence(path, number, visible(line)))
    return found


def _injection_matches(path: str, text: str) -> list[Evidence]:
    """Injection phrases, except when the text only quotes them (e.g. explaining a defence)."""
    found: list[Evidence] = []
    if not any(p.search(text) for p in INJECTION_PATTERNS):
        return found
    for number, line in enumerate(text.splitlines(), 1):
        for pattern in INJECTION_PATTERNS:
            match = pattern.search(line)
            if match is None:
                continue
            before = line[: match.start()].rstrip()
            if before and before[-1] in QUOTES:
                continue
            found.append(Evidence(path, number, visible(line)))
            break
    return found


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _flag(flag_id: str, evidence: list[Evidence]) -> RiskFlag:
    severity, penalty, title, why = CATALOG[flag_id]
    return RiskFlag(flag_id, severity, penalty, title, why, evidence[:3])


def _package_spec(argument_text: str) -> str | None:
    for token in argument_text.split():
        if token.startswith("-"):
            continue
        return token.strip("\"'")
    return None


def _is_pinned(spec: str, tool: str) -> bool:
    if tool.startswith(("uvx", "pipx")):
        return "==" in spec or bool(re.search(r"@v?\d", spec))
    return bool(re.search(r"@v?\d[\w.+-]*$", spec))


def _inside_message(line: str, start: int) -> bool:
    """True when the match sits inside a string literal or a printed message."""
    before = line[:start]
    if before.count('"') % 2 == 1 or before.count("'") % 2 == 1:
        return True
    return any(m in before for m in ("print(", "echo ", "console.", "raise ", "log(", "warn("))


def _unpinned_commands(path: str, text: str) -> list[Evidence]:
    found: list[Evidence] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("#", "//")) and not line.lstrip().startswith("#!"):
            continue
        for match in NPX_LIKE.finditer(line):
            spec = _package_spec(match.group(2))
            if (
                spec
                and PACKAGE_SPEC.match(spec)
                and not _inside_message(line, match.start())
                and not _is_pinned(spec, match.group(1))
            ):
                found.append(Evidence(path, number, visible(line)))
                break
        for match in PIP_INSTALL.finditer(line):
            if _inside_message(line, match.start()):
                continue
            args = [a for a in match.group(1).split() if not a.startswith("-")]
            if args and any("==" not in a and not a.endswith((".txt", ".whl")) for a in args):
                found.append(Evidence(path, number, visible(line)))
    return found


def scan(data: RiskInput) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    md = {p: data.files[p] for p in data.markdown_paths if p in data.files}
    scripts = {p: data.files[p] for p in data.script_paths if p in data.files}

    # -- prompt injection ---------------------------------------------------------------------
    evidence: list[Evidence] = []
    for path, text in md.items():
        evidence += _injection_matches(path, text)
        for match in INVISIBLE.finditer(text.removeprefix("\ufeff")):
            line_no = _line_of(text, match.start())
            evidence.append(Evidence(path, line_no, visible(text.splitlines()[line_no - 1])))
            break
        for match in HTML_COMMENT.finditer(text):
            if COMMENT_IMPERATIVE.search(match.group(1)):
                evidence.append(
                    Evidence(path, _line_of(text, match.start()), visible(match.group(0)))
                )
        for match in BASE64_BLOB.finditer(text):
            evidence.append(Evidence(path, _line_of(text, match.start()), visible(match.group(0))))
    if evidence:
        flags.append(_flag("prompt-injection", _dedupe(evidence)))

    # -- execution ----------------------------------------------------------------------------
    docs = "\n".join([data.readme, *md.values()]).lower()
    executed: list[tuple[Evidence, bool]] = []
    referenced_scripts: set[str] = set()
    for path, command in data.hook_commands:
        names = [m.group(1) for m in SCRIPT_REF.finditer(command)]
        referenced_scripts.update(names)
        explained = bool(names) and all(n.lower() in docs for n in names)
        executed.append((Evidence(path, 1, visible(command)), explained))
    for path, server in data.mcp_servers:
        if "command" not in server:
            continue
        command = " ".join([str(server["command"]), *[str(a) for a in server.get("args", [])]])
        name = str(server.get("name", "")).lower()
        explained = "mcp" in data.readme.lower() or (bool(name) and name in data.readme.lower())
        executed.append((Evidence(path, 1, visible(f"{name}: {command}")), explained))
    # A folder whose documentation names at least one of its scripts counts as documented:
    # helper modules imported by that script are part of the same, explained tooling.
    folders: dict[str, list[str]] = {}
    for path in data.exec_paths:
        base = posixpath.basename(path)
        if path in data.files and base not in referenced_scripts and not TEST_SCRIPT.search(base):
            folders.setdefault(posixpath.dirname(path), []).append(path)
    for folder_paths in folders.values():
        explained = any(
            posixpath.basename(p).lower() in docs or p.lower() in docs for p in folder_paths
        )
        for path in folder_paths:
            executed.append((Evidence(path, 1, visible(posixpath.basename(path))), explained))
    for path, text in md.items():
        for match in re.finditer(r"!`([^`]+)`", text):
            first = match.group(1).split()[0].lower() if match.group(1).split() else ""
            explained = bool(first) and first in data.readme.lower()
            executed.append(
                (Evidence(path, _line_of(text, match.start()), visible(match.group(0))), explained)
            )
    if executed:
        unexplained = [e for e, ok in executed if not ok]
        if unexplained:
            flags.append(_flag("exec-unexplained", unexplained))
        else:
            flags.append(_flag("exec-declared", [e for e, _ in executed]))

    # -- downloads, credentials, obfuscation, exfiltration ------------------------------------
    executable_texts = dict(scripts)
    for index, (path, command) in enumerate(data.hook_commands):
        executable_texts[f"{path}#{index}"] = command
    download = []
    for path, text in executable_texts.items():
        download += _code_matches(path.split("#")[0], text, DOWNLOAD_PATTERNS)
    for path, text in {**md, "README": data.readme}.items():
        download += _matches(path, text, DOWNLOAD_PATTERNS)
    for path, server in data.mcp_servers:
        joined = " ".join(str(a) for a in server.get("args", []))
        download += _matches(path, joined, DOWNLOAD_PATTERNS[-1:])
    if download:
        flags.append(_flag("downloads-binary", _dedupe(download)))

    credentials: list[Evidence] = []
    for path, text in md.items():
        for item in _matches(path, text, [CREDENTIAL_TEXT, CREDENTIAL_FILES]):
            line = text.splitlines()[item.line - 1]
            request = CREDENTIAL_TEXT.search(line)
            if request and NEGATION.search(line[: request.start()]):
                continue  # "never ask the user to paste a token" is a safeguard, not a request
            credentials.append(item)
    for path, text in executable_texts.items():
        credentials += _code_matches(path.split("#")[0], text, [CREDENTIAL_READS])
    if credentials:
        flags.append(_flag("requests-credentials", _dedupe(credentials)))

    obfuscated: list[Evidence] = []
    for path, text in executable_texts.items():
        obfuscated += _code_matches(path.split("#")[0], text, OBFUSCATION)
        for number, line in enumerate(text.splitlines(), 1):
            if len(line) > 1000:
                obfuscated.append(Evidence(path.split("#")[0], number, visible(line)))
    if obfuscated:
        flags.append(_flag("obfuscated-code", _dedupe(obfuscated)))

    exfil: list[Evidence] = []
    for path, text in executable_texts.items():
        exfil += _code_matches(path.split("#")[0], text, EXFIL)
    if exfil:
        flags.append(_flag("network-exfil", _dedupe(exfil)))

    # -- permissions --------------------------------------------------------------------------
    broad: list[Evidence] = []
    for artifact in data.artifacts:
        for tool in artifact.tools:
            if tool in {"Bash", "Bash(*)", "Bash(*:*)", "bypassPermissions"}:
                broad.append(Evidence(artifact.path, 1, visible(f"{tool}")))
    for path, text in {**md, **executable_texts, "README": data.readme}.items():
        broad += _matches(path.split("#")[0], text, [SKIP_PERMISSIONS])
    for path in (p for p in data.files if p.endswith(".claude/settings.json")):
        broad += _matches(path, data.files[path], [SKIP_PERMISSIONS])
    if broad:
        flags.append(_flag("broad-permissions", _dedupe(broad)))

    # -- license ------------------------------------------------------------------------------
    if data.license is None:
        flags.append(_flag("no-license", []))

    # -- unpinned dependencies ----------------------------------------------------------------
    unpinned: list[Evidence] = []
    for path, server in data.mcp_servers:
        if "command" in server:
            command = " ".join([str(server["command"]), *[str(a) for a in server.get("args", [])]])
            unpinned += _unpinned_commands(path, command)
    for path, text in executable_texts.items():
        unpinned += _unpinned_commands(path.split("#")[0], text)
    for entry in data.marketplace_entries:
        if entry.repo and not entry.pinned:
            unpinned.append(
                Evidence(
                    data.marketplace_path or "marketplace.json",
                    1,
                    f"{entry.name} → {entry.repo} sin sha",
                )
            )
    if unpinned:
        flags.append(_flag("unpinned-deps", _dedupe(unpinned)))

    order = list(CATALOG)
    return sorted(flags, key=lambda f: order.index(f.id))


def _dedupe(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, int]] = set()
    out: list[Evidence] = []
    for item in evidence:
        key = (item.path, item.line)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
