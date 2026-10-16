# Buildozer config for the Wattly Android APK (p4a webview bootstrap).
# The very same Flask app that powers the desktop window is served on
# 127.0.0.1 by waitress and loaded in a fullscreen WebView.

[app]

title = Wattly
package.name = wattly
package.domain = org.wattly

source.dir = .
source.include_exts = py,png,css,js,woff2,html,ico
source.exclude_dirs = .git, .venv, .buildozer, bin, dist, build, tests, packaging
source.exclude_patterns = *.pyc, *.pyo, *.db, *.pdf, *.spec, *.md, *.log

version = 1.0.0

requirements = python3, flask, sqlalchemy, pillow, openpyxl, pdfplumber, pdfminer.six, charset-normalizer, et-xmlfile, six, waitress, platformdirs

orientation = landscape
fullscreen = 0

icon.filename = %(source.dir)s/wattly/assets/icons/icon.png

p4a.bootstrap = webview
p4a.port = 5055
p4a.hook = %(source.dir)s/packaging/android/p4a_hook.py

#
# Android specific
#

android.accept_sdk_license = True
android.release_artifact = apk

android.permissions = INTERNET
android.api = 34
android.minapi = 24

[buildozer]

log_level = 2
warn_on_root = 1
