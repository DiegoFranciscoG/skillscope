"""The browser tokenizer tables must always match analyzer/text.py."""

import importlib.util

from tests.support import ROOT


def test_generated_typescript_lexicon_is_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location(
        "export_lexicon", ROOT / "scripts" / "export_lexicon.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    current = module.TARGET.read_text(encoding="utf-8")
    assert current == module.render(), "run: uv run python scripts/export_lexicon.py"
