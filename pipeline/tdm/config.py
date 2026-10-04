"""設定ファイルと作業ディレクトリの場所。"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PIPELINE_DIR.parent
CONFIG_DIR = PIPELINE_DIR / "config"


@dataclass(frozen=True)
class Paths:
    data_dir: Path

    @property
    def raw(self) -> Path:
        return self.data_dir / "raw"

    @property
    def db(self) -> Path:
        return self.data_dir / "db" / "tdm.sqlite"

    @property
    def releases(self) -> Path:
        return self.data_dir / "releases"


DEFAULT_PATHS = Paths(REPO_DIR / "data")


def load_sources() -> dict[str, dict]:
    return tomllib.loads((CONFIG_DIR / "sources.toml").read_text(encoding="utf-8"))


def load_indicators() -> dict[str, dict]:
    return tomllib.loads((CONFIG_DIR / "indicators.toml").read_text(encoding="utf-8"))


def load_censuses() -> list[dict]:
    """取り込む国勢調査の時点（古い順）。最後の時点の境界を地図に使う。"""
    censuses = tomllib.loads((CONFIG_DIR / "censuses.toml").read_text(encoding="utf-8"))["census"]
    return sorted(censuses, key=lambda c: c["period"])
