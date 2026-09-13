#!/usr/bin/env python3
"""Install and setup script for OmaCheck."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOCAL_BIN_DIR = Path.home() / ".local" / "bin"
PLUGIN_TARGET_DIR = Path.home() / ".config" / "omarchy" / "plugins" / "carsten.omacheck"
CONFIG_DIR = Path.home() / ".config" / "omacheck"
APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"


def install_cli() -> bool:
    print("-> Installing OmaCheck CLI...")
    LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_bin = LOCAL_BIN_DIR / "omacheck"

    source_py = PROJECT_ROOT / "omacheck.py"
    if not source_py.is_file():
        print(f"Error: {source_py} does not exist.")
        return False

    if target_bin.is_symlink() or target_bin.is_file():
        target_bin.unlink()

    try:
        target_bin.symlink_to(source_py)
        target_bin.chmod(0o755)
        print(f"✓ Symlink created: {target_bin} -> {source_py}")
    except Exception:
        shutil.copy2(source_py, target_bin)
        target_bin.chmod(0o755)
        print(f"✓ Copied: {target_bin}")

    return True


def install_desktop_entry() -> bool:
    print("-> Installing desktop app launcher...")
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    target_desktop = APPLICATIONS_DIR / "omacheck.desktop"
    source_desktop = PROJECT_ROOT / "omacheck.desktop"

    if not source_desktop.is_file():
        print(f"Error: {source_desktop} does not exist.")
        return False

    shutil.copy2(source_desktop, target_desktop)
    print(f"✓ Desktop entry installed: {target_desktop}")

    try:
        subprocess.run(["update-desktop-database", str(APPLICATIONS_DIR)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    return True


def install_plugin() -> bool:
    print("-> Installing Quickshell plugin (carsten.omacheck)...")
    PLUGIN_TARGET_DIR.mkdir(parents=True, exist_ok=True)

    plugin_src = PROJECT_ROOT / "plugin"
    if not plugin_src.is_dir():
        print(f"Error: {plugin_src} does not exist.")
        return False

    # Clean up any old links in the plugin folder
    for old_item in PLUGIN_TARGET_DIR.glob("*"):
        if old_item.is_symlink() or old_item.is_file():
            old_item.unlink()
        elif old_item.is_dir():
            shutil.rmtree(old_item)

    for item in plugin_src.glob("*"):
        dest = PLUGIN_TARGET_DIR / item.name
        try:
            dest.symlink_to(item.resolve())
            print(f"✓ Plugin file linked: {dest.name}")
        except Exception:
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
            print(f"✓ Plugin file copied: {dest.name}")

    # Re-scan plugins in the Omarchy shell
    try:
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Omarchy shell: plugins rescanned.")
    except Exception:
        pass

    return True


def setup_example_notes() -> None:
    import omacheck

    config = omacheck.load_config()
    notes_dir, mode_desc = omacheck.resolve_notes_directory(config)

    print(f"-> Checking notes directory ({mode_desc}): {notes_dir}")
    welcome_file = notes_dir / "Welcome.md"
    if not welcome_file.exists():
        content = (
            "# Welcome to OmaCheck\n\n"
            "OmaCheck is your universal notes & to-do app for Omarchy Linux.\n\n"
            "## Tasks\n"
            "- [ ] Check off your first to-do in the desktop widget or the app ⏫ 📅 2026-09-15\n"
            "- [ ] Edit any note here or in an editor of your choice\n"
            "- [x] OmaCheck installed successfully ✅ 2026-09-12\n\n"
            "## Notes & ideas\n"
            "- Checkboxes sync automatically.\n"
            "- Categories can be created as subfolders, or pinned from Settings.\n"
        )
        try:
            with open(welcome_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✓ Example note created: {welcome_file}")
        except Exception as err:
            print(f"Note: Could not create example note: {err}")


def main() -> int:
    print("=== OmaCheck setup for Omarchy Linux ===\n")
    if not install_cli():
        return 1
    if not install_desktop_entry():
        return 1
    if not install_plugin():
        return 1
    # Apply the saved choice; a fresh installation leaves the bar widget off.
    if subprocess.run([sys.executable, str(PROJECT_ROOT / "omacheck.py"), "settings", "--apply"]).returncode:
        print("Error: Could not apply the bar widget setting.")
        return 1
    setup_example_notes()

    print("\n✓ Installation completed successfully!")
    print("\nAvailable interfaces:")
    print("1. Desktop widget:  Runs permanently on the wallpaper (bottom layer)")
    print("2. Bar widget:      Off by default; enable it in the app under Settings")
    print("3. Native app:      omacheck gui (or via the Omarchy app menu)")
    print("4. Terminal CLI:    omacheck tasks / omacheck add 'Task'")
    print("\nNotes are stored under ~/Documents/OmaCheck by default; switch to an")
    print("Obsidian vault any time from the app's Settings panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
