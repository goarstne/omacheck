#!/usr/bin/env python3
"""Installations- und Setup-Skript für OmaCheck."""

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
    print("-> Installiere OmaCheck CLI...")
    LOCAL_BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_bin = LOCAL_BIN_DIR / "omacheck"

    source_py = PROJECT_ROOT / "omacheck.py"
    if not source_py.is_file():
        print(f"Fehler: {source_py} existiert nicht.")
        return False

    if target_bin.is_symlink() or target_bin.is_file():
        target_bin.unlink()

    try:
        target_bin.symlink_to(source_py)
        target_bin.chmod(0o755)
        print(f"✓ Symlink erstellt: {target_bin} -> {source_py}")
    except Exception:
        shutil.copy2(source_py, target_bin)
        target_bin.chmod(0o755)
        print(f"✓ Kopiert: {target_bin}")

    return True


def install_desktop_entry() -> bool:
    print("-> Installiere Desktop-App Launcher...")
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    target_desktop = APPLICATIONS_DIR / "omacheck.desktop"
    source_desktop = PROJECT_ROOT / "omacheck.desktop"

    if not source_desktop.is_file():
        print(f"Fehler: {source_desktop} existiert nicht.")
        return False

    shutil.copy2(source_desktop, target_desktop)
    print(f"✓ Desktop-Eintrag installiert: {target_desktop}")

    try:
        subprocess.run(["update-desktop-database", str(APPLICATIONS_DIR)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    return True


def install_plugin() -> bool:
    print("-> Installiere Quickshell-Plugin (carsten.omacheck)...")
    PLUGIN_TARGET_DIR.mkdir(parents=True, exist_ok=True)

    plugin_src = PROJECT_ROOT / "plugin"
    if not plugin_src.is_dir():
        print(f"Fehler: {plugin_src} existiert nicht.")
        return False

    # Vorhandene alte Verlinkungen im Plugin-Ordner bereinigen
    for old_item in PLUGIN_TARGET_DIR.glob("*"):
        if old_item.is_symlink() or old_item.is_file():
            old_item.unlink()
        elif old_item.is_dir():
            shutil.rmtree(old_item)

    for item in plugin_src.glob("*"):
        dest = PLUGIN_TARGET_DIR / item.name
        try:
            dest.symlink_to(item.resolve())
            print(f"✓ Plugin-Datei verlinkt: {dest.name}")
        except Exception:
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
            print(f"✓ Plugin-Datei kopiert: {dest.name}")

    # Plugin im Omarchy-Shell neu einlesen
    try:
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Omarchy-Shell: Plugins neu eingelesen.")
    except Exception:
        pass

    return True


def setup_example_notes() -> None:
    import omacheck

    config = omacheck.load_config()
    notes_dir, mode_desc = omacheck.resolve_notes_directory(config)

    print(f"-> Prüfe Notizen-Verzeichnis ({mode_desc}): {notes_dir}")
    welcome_file = notes_dir / "Willkommen.md"
    if not welcome_file.exists():
        content = (
            "# Willkommen bei OmaCheck\n\n"
            "OmaCheck ist deine universelle Notizen- und To-Do-App für Omarchy Linux.\n\n"
            "## Aufgaben\n"
            "- [ ] Erstes To-Do im Desktop-Widget oder in der App abhaken ⏫ 📅 2026-09-15\n"
            "- [ ] Beliebige Notiz in Obsidian oder im Terminal bearbeiten\n"
            "- [x] OmaCheck erfolgreich installiert ✅ 2026-09-12\n\n"
            "## Notizen & Ideen\n"
            "- Checkboxen werden automatisch synchronisiert.\n"
            "- Kategorien können als Unterordner angelegt werden.\n"
        )
        try:
            with open(welcome_file, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✓ Beispiel-Notiz erstellt: {welcome_file}")
        except Exception as err:
            print(f"Hinweis: Konnte Beispielnotiz nicht anlegen: {err}")


def main() -> int:
    print("=== OmaCheck Setup für Omarchy Linux ===\n")
    if not install_cli():
        return 1
    if not install_desktop_entry():
        return 1
    if not install_plugin():
        return 1
    setup_example_notes()

    print("\n✓ Installation erfolgreich abgeschlossen!")
    print("\nVerfügbare Schnittstellen:")
    print("1. Desktop-Widget:   Läuft permanent auf dem Desktop-Hintergrund (Bottom Layer)")
    print("2. Bar-Widget:       In Omarchy-Leiste mit Zähleranzeige (omarchy bar put carsten.omacheck)")
    print("3. Eigene App:       omacheck gui (oder über das Omarchy Anwendungsmenü)")
    print("4. Terminal CLI:     omacheck tasks / omacheck add 'Aufgabe'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
