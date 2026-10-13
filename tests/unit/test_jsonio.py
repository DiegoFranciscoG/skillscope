import os
import stat
from pathlib import Path

import pytest

from pipeline.jsonio import read_json, write_json


def test_atomic_write_round_trip_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "data.json"
    write_json(target, {"ñ": [1, 2]})
    write_json(target, {"ñ": [3]})
    assert read_json(target) == {"ñ": [3]}
    assert [p.name for p in target.parent.iterdir()] == ["data.json"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_published_files_are_world_readable(tmp_path: Path) -> None:
    target = tmp_path / "index.json"
    write_json(target, {})
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
