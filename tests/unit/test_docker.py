"""Container rules: pinned images, non-root runtime, healthcheck, hardened compose, same CSP."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_every_base_image_has_an_exact_version() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    images = re.findall(r"^FROM\s+(\S+)", dockerfile, re.M)
    images += re.findall(r"COPY --from=(\S+/\S+)\s", dockerfile)
    assert len(images) >= 4
    for image in images:
        name, _, tag = image.rpartition(":")
        assert name and re.match(r"^v?\d+\.\d+\.\d+", tag), f"{image} is not pinned"
        assert "latest" not in tag


def test_runtime_is_unprivileged_with_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("AS runtime", 1)[1]
    assert re.search(r"^USER\s+(?!0\b|root\b)\S+", runtime, re.M)
    assert "HEALTHCHECK" in runtime
    assert "nginx-unprivileged" in dockerfile


def test_compose_is_hardened_and_needs_no_secret() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    web = compose["services"]["web"]
    assert web["read_only"] is True
    assert web["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in web["security_opt"]
    assert "healthcheck" in web
    assert all(port.startswith("127.0.0.1:") for port in web["ports"])
    assert "environment" not in web and "env_file" not in web


def test_nginx_sends_the_same_csp_as_the_meta_tag_plus_frame_ancestors() -> None:
    vite = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")
    block = vite.split("export const CSP = [", 1)[1].split("]", 1)[0]
    meta = re.findall(r'"([^"]+)"', block)
    headers = (ROOT / "docker" / "nginx" / "security-headers.conf").read_text(encoding="utf-8")
    match = re.search(r'Content-Security-Policy "([^"]+)"', headers)
    assert match is not None
    header = [d.strip() for d in match.group(1).split(";")]
    assert header == [*meta, "frame-ancestors 'none'"]
    for name in ("X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy"):
        assert name in headers
