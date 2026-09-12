# OmaCheck

**Universelle Notizen- & To-Do-App für Omarchy Linux mit interaktiven Checkboxen, optionalen Kategorien, permanentem Desktop-Widget, Bar-Widget und nativer App-Oberfläche.**

Gebaut nach dem **Ponytail-Prinzip** (*Lazy Senior Dev: "The best code is the code never written"*):
Reines Markdown als Single Source of Truth, keine externe Datenbank, kein eigener Sync-Daemon, vollständige Nutzung des Omarchy Linux Ökosystems (Hyprland + Quickshell) und direkte Obsidian-Vault-Kompatibilität.

---

## Komponenten

1. **Desktop-Widget (Permanent auf dem Wallpaper):**
   - Läuft als Quickshell-Service auf `WlrLayershell.layer: Bottom`.
   - Zeigt Notizen & Checkboxen direkt auf dem Desktop-Hintergrund an.
   - Kategorien-Filter und direktes Abhaken per Klick.
   - Liegt hinter normalen Arbeitsfenstern und stört das Kacheln nicht.

2. **Native Omarchy App (`omacheck gui`):**
   - Vollständiges, modernes Anwendungsfenster (`FloatingWindow`).
   - 100 % Theme-kompatibel (übernimmt Farben, Akzente und Schriftarten aus `qs.Commons.Color` und `qs.Ui.Style`).
   - 3-Spalten-Layout: Kategorien-Sidebar, Notizenliste und interaktive Aufgaben- & Notizansicht.
   - Erreichbar über Terminal (`omacheck gui`), Klick auf das Bar-Widget oder das Omarchy-App-Menü (`omacheck.desktop`).

3. **Statusleisten-Widget:**
   - Integriert in `omarchy.bar` (`bar.layout.right`).
   - Zeigt den aktuellen Zähler offener Aufgaben (`✓ 3`).
   - Klick öffnet direkt die OmaCheck App.

4. **Obsidian-Integration:**
   - Erkennt den aktiven Obsidian-Vault automatisch aus `~/.config/obsidian/obsidian.json`.
   - Notizen liegen standardmäßig unter `<Vault>/Notes/`.
   - Manuelles Bearbeiten in Obsidian oder im Terminal synchronisiert sich automatisch mit den Widgets und der App.

---

## Installation & Einrichtung

```bash
cd /home/carsten/Projects/omacheck
python3 install.py
```

Das Skript:
1. Erstellt den Symlink `~/.local/bin/omacheck`.
2. Installiert den Anwendungsstarter `~/.local/share/applications/omacheck.desktop`.
3. Kopiert das Quickshell-Plugin nach `~/.config/omarchy/plugins/carsten.omacheck/`.
4. Lädt die Omarchy-Shell-Plugins neu (`omarchy-shell shell rescanPlugins`).

---

## CLI-Befehle

```bash
# GUI / App starten
omacheck gui
omacheck app

# Aufgaben anzeigen
omacheck tasks
omacheck tasks --all
omacheck tasks -c Arbeit

# Neue Aufgabe anlegen
omacheck add "Projektbericht fertigstellen" -c "Arbeit" -p high -d 2026-09-20 -t release

# Checkbox abhaken oder wiedereröffnen
omacheck toggle <task_id>

# Neue Notiz erstellen
omacheck create-note "Architektur-Planung" -c "Dev"

# Kategorien anzeigen
omacheck categories

# Status & Vault-Pfad prüfen
omacheck status

# JSON-Ausgabe für Widgets & Scripts
omacheck tasks --json
```

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```
