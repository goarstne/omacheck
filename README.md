# OmaCheck

**Universal notes & to-do app for Omarchy Linux, with interactive checkboxes, optional categories, a permanent desktop widget, a bar widget, and a native app window.**

Built on the **Ponytail principle** (*lazy senior dev: "The best code is the code never written"*):
plain Markdown as the single source of truth, no external database, no custom sync daemon, full use of the Omarchy Linux ecosystem (Hyprland + Quickshell), with optional Obsidian vault compatibility.

---

## Components

1. **Desktop widget (permanent, on the wallpaper):**
   - Runs as a Quickshell service on `WlrLayershell.layer: Bottom`.
   - Shows a compact task list with checkboxes to the left of the text, directly on the desktop background.
   - Category filter (with a "+" to pin a new category) and one-click checking off.
   - Sits behind normal windows and doesn't interfere with tiling.
   - Can be turned off entirely from **Settings** in the app.

2. **Native Omarchy app (`omacheck gui`):**
   - Full, modern application window (`FloatingWindow`), loaded in-process as a `panel`-kind plugin — the same mechanism `omarchy.menu` uses for its own panel, not a separate `quickshell` process.
   - 100% theme-compatible (picks up colors, accents, and fonts from `qs.Commons.Color` and `qs.Ui.Style`).
   - Category filter and search across a two-column notes/tasks view.
   - Tasks use real checkboxes to the left of the text.
   - **Settings** lets you toggle the bar widget, the desktop widget, and the storage mode (standalone vs. Obsidian).
   - Reachable from the terminal (`omacheck gui`), by clicking the bar widget, or via the Omarchy app menu (`omacheck.desktop`) — each just runs `omarchy-shell shell toggle carsten.omacheck`.

3. **Bar widget:**
   - Off by default; enable it from **Settings → Show bar widget** in the app.
   - The choice persists across restarts.
   - Shows the current open-task count (`✓ 3`).
   - Click to open or close the OmaCheck app.

4. **Storage — standalone by default, Obsidian optional:**
   - By default, notes live under `~/Documents/OmaCheck` — no other app required.
   - Switch to an Obsidian vault any time from **Settings → Obsidian vault**; OmaCheck then auto-detects the currently open vault from `~/.config/obsidian/obsidian.json` and stores notes under `<Vault>/Notes/`.
   - Widget and app both read/write the same Markdown files, so a task added in one shows up in the other — the desktop widget and app poll every ~8 seconds, the bar widget every ~10 seconds; click **Refresh** in the app window for an instant update.

---

## Install & setup

```bash
git clone https://github.com/goarstne/omacheck.git
cd omacheck
python3 install.py
```

The script:
1. Creates the symlink `~/.local/bin/omacheck`.
2. Installs the app launcher `~/.local/share/applications/omacheck.desktop`.
3. Links the Quickshell plugin into `~/.config/omarchy/plugins/carsten.omacheck/`.
4. Reloads the Omarchy shell plugins (`omarchy-shell shell rescanPlugins`).

---

## CLI commands

```bash
# Launch the GUI / app
omacheck gui
omacheck app

# List tasks
omacheck tasks
omacheck tasks --all
omacheck tasks -c Work

# Add a new task
omacheck add "Finish project report" -c "Work" -p high -d 2026-09-20 -t release

# Check off or reopen a checkbox
omacheck toggle <task_id>

# Create a new note
omacheck create-note "Architecture planning" -c "Dev"

# List categories (--add pins a category before it has any notes)
omacheck categories
omacheck categories --add "Shopping"

# Check status & storage path
omacheck status

# Toggle the bar widget / desktop widget (also available in app Settings)
omacheck settings --bar-widget on
omacheck settings --bar-widget off
omacheck settings --desktop-widget on
omacheck settings --desktop-widget off

# Switch storage mode (also available in app Settings)
omacheck settings --storage-mode standalone
omacheck settings --storage-mode obsidian

# JSON output for widgets & scripts
omacheck tasks --json
```

---

## Tests

```bash
python3 -m unittest discover -s tests -v

# Native checkbox interaction and write-failure handling with isolated test notes
python3 tests/check_ui.py

# App panel open/close lifecycle (host- vs. user-initiated close, shell.hide() sync)
python3 tests/check_app_panel.py
```

---

## License

MIT License. Copyright (c) 2026 Carsten.
