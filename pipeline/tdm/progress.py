"""長い取込・書き出しの途中経過を、開始からの経過時間つきで出す（全国の公開版は数時間かかるため）。"""

from __future__ import annotations

import resource
import time

_STARTED = time.monotonic()


def progress(message: str) -> None:
    elapsed = int(time.monotonic() - _STARTED)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024   # Linux は KB
    print(f"[{elapsed // 3600}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}] {message}（最大メモリ {peak_mb:,}MB）",
          flush=True)
