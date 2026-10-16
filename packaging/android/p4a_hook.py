"""python-for-android build hook (buildozer: p4a.hook = packaging/android/p4a_hook.py).

The stock webview bootstrap activity has no WebChromeClient (no
``<input type=file>``) and no DownloadListener (no CSV/Excel exports).
``before_apk_build`` fires after the bootstrap sources are staged into
the dist directory but before javac runs, so we drop in Wattly's
patched PythonActivity.java.
"""

from __future__ import annotations

import shutil
from os.path import abspath, dirname, exists, join

PATCHED_ACTIVITY = join(dirname(abspath(__file__)), "PythonActivity.java")
ACTIVITY_REL = join(
    "src", "main", "java", "org", "kivy", "android", "PythonActivity.java"
)


def before_apk_build(toolchain) -> None:
    dist_dir = toolchain._dist.dist_dir
    target = join(dist_dir, ACTIVITY_REL)
    if not exists(target):
        print(f"[wattly-p4a-hook] warning: {target} not found yet — patch skipped")
        return
    shutil.copyfile(PATCHED_ACTIVITY, target)
    print(f"[wattly-p4a-hook] patched {target}")
