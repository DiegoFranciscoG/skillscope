"""Exact install commands per artifact type (docs/modelo-datos.md R5; docs #4, #6, #8, #10).

Every name that ends up inside a command comes from third-party files, so it is checked
against a strict character set first. If anything looks odd, no command is generated.
"""

from __future__ import annotations

import json
import posixpath
import re
import tomllib

from analyzer.model import Artifact, Install, InstallStep

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
SAFE_VERSION = re.compile(r"^[0-9][0-9A-Za-z.+-]*$")
SAFE_PACKAGE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")


def _safe(value: str | None, pattern: re.Pattern[str]) -> bool:
    return bool(value) and bool(pattern.match(value or "")) and ".." not in (value or "")


def marketplace_install(repo_id: str, marketplace: str, plugins: list[str]) -> Install | None:
    plugin = next((p for p in plugins if _safe(p, SAFE_ID)), None)
    if not (_safe(marketplace, SAFE_ID) and plugin):
        return None
    steps = [
        InstallStep("Agregar el marketplace (en una sesión)", f"/plugin marketplace add {repo_id}"),
        InstallStep(
            "Instalar el plugin (en una sesión)", f"/plugin install {plugin}@{marketplace}"
        ),
    ]
    note = ""
    if len(plugins) > 1:
        note = f"El marketplace ofrece {len(plugins)} plugins; cambia el nombre antes de «@»."
    return Install(
        kind="marketplace",
        steps=steps,
        note=note,
        one_liner=(
            f"claude plugin marketplace add {repo_id} && "
            f"claude plugin install {plugin}@{marketplace}"
        ),
    )


def plugin_dir_install(repo_id: str) -> Install:
    name = repo_id.split("/")[1]
    clone = f"git clone --depth 1 https://github.com/{repo_id}.git"
    return Install(
        kind="plugin_dir",
        steps=[
            InstallStep("Clonar el repositorio", clone),
            InstallStep("Cargar el plugin en una sesión", f"claude --plugin-dir ./{name}"),
        ],
        note="Sin marketplace propio solo se carga por sesión; el autor puede publicar un "
        "marketplace.json para instalarlo por nombre.",
        one_liner=f"{clone} && claude --plugin-dir ./{name}",
    )


def copy_install(repo_id: str, path: str, target: str, kind: str) -> Install | None:
    """Copy a skill folder, agent file or command file into the user's ~/.claude directory."""
    name = repo_id.split("/")[1]
    temp = f"/tmp/skillscope-{name}"  # noqa: S108 - text of a command shown to the user
    clone = f"git clone --depth 1 https://github.com/{repo_id}.git {temp}"
    if kind == "skill":
        folder = posixpath.dirname(path)
        skill_name = posixpath.basename(folder) if folder else name
        if not _safe(skill_name, SAFE_ID) or (folder and not _safe(folder, SAFE_PATH)):
            return None
        if not folder:
            url = f"https://github.com/{repo_id}.git"
            command = f"git clone --depth 1 {url} ~/.claude/skills/{skill_name}"
            return Install(
                kind="skill_copy",
                steps=[InstallStep("Clonar la skill en tu carpeta personal", command)],
                note="Para un solo proyecto usa .claude/skills/ dentro del repositorio.",
                one_liner=command,
            )
        copy = f"mkdir -p ~/.claude/skills && cp -r {temp}/{folder} ~/.claude/skills/{skill_name}"
        return Install(
            kind="skill_copy",
            steps=[
                InstallStep("Clonar el repositorio", clone),
                InstallStep("Copiar la skill", copy),
            ],
            note="Para un solo proyecto copia la carpeta en .claude/skills/ del repositorio.",
            one_liner=f"{clone} && {copy}",
        )
    if not _safe(path, SAFE_PATH):
        return None
    copy = f"mkdir -p ~/.claude/{target} && cp {temp}/{path} ~/.claude/{target}/"
    label = "Copiar el agente" if kind == "agent" else "Copiar el comando"
    return Install(
        kind="skill_copy",
        steps=[InstallStep("Clonar el repositorio", clone), InstallStep(label, copy)],
        note=f"Para un solo proyecto usa .claude/{target}/ dentro del repositorio.",
        one_liner=f"{clone} && {copy}",
    )


def mcp_install(repo_id: str, package_json: str | None, pyproject: str | None) -> Install:
    short = re.sub(r"[^a-z0-9-]", "-", repo_id.split("/")[1].lower()).strip("-") or "server"
    if package_json:
        try:
            data = json.loads(package_json)
        except json.JSONDecodeError:
            data = {}
        name, version = str(data.get("name") or ""), str(data.get("version") or "")
        if _safe(name, SAFE_PACKAGE) and _safe(version, SAFE_VERSION) and not data.get("private"):
            command = f"claude mcp add {short} -- npx -y {name}@{version}"
            return Install("mcp", [InstallStep("Registrar el servidor MCP", command)], "", command)
    if pyproject:
        try:
            project = tomllib.loads(pyproject).get("project", {})
        except tomllib.TOMLDecodeError:
            project = {}
        name, version = str(project.get("name") or ""), str(project.get("version") or "")
        if _safe(name, SAFE_PACKAGE) and _safe(version, SAFE_VERSION):
            command = f"claude mcp add {short} -- uvx {name}=={version}"
            return Install("mcp", [InstallStep("Registrar el servidor MCP", command)], "", command)
    return Install(
        "manual",
        [],
        "No publica un paquete con versión verificable: sigue las instrucciones del README.",
        None,
    )


def build_install(
    *,
    repo_id: str,
    repo_type: str,
    marketplace_name: str | None,
    marketplace_installable: bool,
    marketplace_plugins: list[str],
    artifacts: list[Artifact],
    package_json: str | None,
    pyproject: str | None,
) -> Install:
    if repo_type == "awesome_list":
        return Install("list", [], "Es una lista curada: no se instala, se exploran sus enlaces.")
    if repo_type == "template":
        command = f"gh repo create mi-skill --template {repo_id} --private --clone"
        return Install(
            "template", [InstallStep("Crear tu repo desde la plantilla", command)], "", command
        )
    if marketplace_name:
        if marketplace_installable:
            install = marketplace_install(repo_id, marketplace_name, marketplace_plugins)
            if install:
                return install
        return Install(
            "manual",
            [],
            "El marketplace.json no es instalable (nombre reservado o entradas inválidas).",
        )
    if repo_type == "plugin":
        return plugin_dir_install(repo_id)
    if repo_type == "mcp_server":
        return mcp_install(repo_id, package_json, pyproject)
    preferred = {"skill": "skill", "agent": "agent", "command": "command"}
    wanted = preferred.get(repo_type)
    ordered = sorted(
        (a for a in artifacts if a.kind in {"skill", "agent", "command"}),
        key=lambda a: (a.kind != wanted, not a.valid, a.path),
    )
    for artifact in ordered:
        target = {"skill": "skills", "agent": "agents", "command": "commands"}[artifact.kind]
        install = copy_install(repo_id, artifact.path, target, artifact.kind)
        if install:
            return install
    if repo_type == "hook":
        return Install(
            "manual",
            [],
            "Revisa hooks/hooks.json y copia los hooks a ~/.claude/settings.json (clave «hooks»).",
        )
    return Install("manual", [], "Sigue las instrucciones del README.")
