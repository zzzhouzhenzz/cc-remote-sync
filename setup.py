"""py2app build:  python setup.py py2app
Produces dist/cc-remote-sync.app — a menu-bar-only (LSUIElement) bundle."""
from setuptools import setup

APP = ["app_main.py"]
DATA_FILES = [("assets", [
    "assets/menubar_idle.png",
    "assets/menubar_syncing.png",
    "assets/menubar_error.png",
])]
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "assets/AppIcon.icns",
    "packages": ["cc_remote_sync", "rumps"],
    "plist": {
        "CFBundleName": "cc-remote-sync",
        "CFBundleDisplayName": "cc-remote-sync",
        "CFBundleIdentifier": "com.zz.cc-remote-sync",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,          # menu-bar only, no Dock icon
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "",
    },
}

setup(
    app=APP,
    name="cc-remote-sync",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
