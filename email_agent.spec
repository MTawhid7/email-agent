# email_agent.spec
# Build with: pyinstaller email_agent.spec
# Produces: dist/Email Agent.app (Mac) or dist/Email Agent.exe (Windows)

import sys
from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE

block_cipher = None

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("templates",   "templates"),
        ("static",      "static"),
        ("credentials/credentials.json", "credentials"),  # bundled shared OAuth app identity
    ],
    hiddenimports=[
        # Google Auth
        "google.auth",
        "google.auth.transport.requests",
        "google.auth.exceptions",
        "google.oauth2.credentials",
        "google_auth_oauthlib.flow",
        "google_auth_oauthlib.helpers",
        # Gmail API
        "googleapiclient",
        "googleapiclient.discovery",
        "googleapiclient.errors",
        "googleapiclient.http",
        # Gemini
        "google.genai",
        "google.genai.types",
        "google.genai.errors",
        # Flask
        "flask",
        "werkzeug",
        "jinja2",
        "click",
        # Other
        "bs4",
        "dotenv",
        "requests",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Email Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # No terminal window shown to user
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Mac-only: wrap the EXE in a .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Email Agent.app",
        icon=None,           # Replace with "icon.icns" if you have one
        bundle_identifier="com.emailagent.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSUIElement": False,
        },
    )
