#!/usr/bin/env python3
"""OmaCheck — Universelle Notizen- & To-Do-Engine für Omarchy Linux.

Verwaltet Markdown-Notizen mit interaktiven Checkboxen, optionalen Kategorien
und Obsidian-Vault-Integration nach dem Ponytail-Prinzip (Zero Dependencies).
"""

import argparse
import datetime
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "omacheck" / "config.json"
OBSIDIAN_CONFIG_PATH = Path.home() / ".config" / "obsidian" / "obsidian.json"
DEFAULT_STANDALONE_DIR = Path.home() / ".local" / "share" / "omacheck" / "notes"

CHECKBOX_PATTERN = re.compile(r"^(\s*)-\s*\[([ xX])\]\s+(.*)$")
PRIORITY_MAP = {
    "⏫": "high",
    "🔼": "medium",
    "🔽": "low",
}
REV_PRIORITY_MAP = {
    "high": "⏫",
    "medium": "🔼",
    "low": "🔽",
}
DUE_DATE_PATTERN = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
DONE_DATE_PATTERN = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})")
TAG_PATTERN = re.compile(r"(?<!\S)#([a-zA-Z0-9_\-]+)")


@dataclass
class Task:
    id: str
    raw: str
    text: str
    completed: bool
    line_number: int
    file_path: str
    note_title: str
    category: str
    priority: Optional[str] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    tags: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        if data["tags"] is None:
            data["tags"] = []
        return data


@dataclass
class Note:
    title: str
    category: str
    file_path: str
    mtime: float
    tasks: List[Task]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "file_path": self.file_path,
            "mtime": self.mtime,
            "tasks": [t.to_dict() for t in self.tasks],
        }


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """Lädt die Konfiguration oder gibt sichere Defaults zurück."""
    defaults: Dict[str, Any] = {
        "storage": {
            "mode": "auto",  # 'auto', 'obsidian' oder 'standalone'
            "obsidian_vault": "auto",
            "notes_dir_name": "Notes",
            "fallback_dir": str(DEFAULT_STANDALONE_DIR),
        },
        "categories": {
            "default_category": "Allgemein",
            "pinned": ["Arbeit", "Privat", "Ideen"],
        },
        "tasks": {
            "append_completion_date": True,
        },
    }
    if not config_path.is_file():
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
            # Flaches Mergen für storage und categories
            for section in ["storage", "categories", "tasks"]:
                if section in user_config and isinstance(user_config[section], dict):
                    defaults[section].update(user_config[section])
            return defaults
    except Exception as err:
        sys.stderr.write(f"Warnung: Konnte {config_path} nicht lesen: {err}\n")
        return defaults


def detect_obsidian_vault() -> Optional[Path]:
    """Liest die aktiven Obsidian-Vaults aus ~/.config/obsidian/obsidian.json."""
    if not OBSIDIAN_CONFIG_PATH.is_file():
        return None
    try:
        with open(OBSIDIAN_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        vaults = data.get("vaults", {})
        # Suche bevorzugt nach dem aktuell geöffneten Vault
        for v in vaults.values():
            if v.get("open") and v.get("path"):
                p = Path(v["path"]).expanduser().resolve()
                if p.is_dir():
                    return p
        # Fallback auf den ersten gültigen Pfad
        for v in vaults.values():
            if v.get("path"):
                p = Path(v["path"]).expanduser().resolve()
                if p.is_dir():
                    return p
    except Exception:
        pass
    return None


def resolve_notes_directory(config: Dict[str, Any]) -> Tuple[Path, str]:
    """Ermittelt das aktive Notizen-Verzeichnis basierend auf Config und System."""
    mode = config["storage"].get("mode", "auto")
    notes_subdir = config["storage"].get("notes_dir_name", "Notes")

    if mode in ("auto", "obsidian"):
        configured_vault = config["storage"].get("obsidian_vault", "auto")
        vault_path: Optional[Path] = None
        if configured_vault != "auto":
            p = Path(configured_vault).expanduser().resolve()
            if p.is_dir():
                vault_path = p
        else:
            vault_path = detect_obsidian_vault()

        if vault_path:
            notes_dir = vault_path / notes_subdir
            notes_dir.mkdir(parents=True, exist_ok=True)
            return notes_dir, f"obsidian ({vault_path.name})"

    # Standalone Fallback
    fallback = Path(config["storage"].get("fallback_dir", str(DEFAULT_STANDALONE_DIR))).expanduser().resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback, "standalone"


def extract_frontmatter_category(lines: List[str]) -> Optional[str]:
    """Liest die optionale Kategorie aus dem YAML-Frontmatter einer Notiz."""
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, val = line.split(":", 1)
            if key.strip().lower() in ("category", "kategorie"):
                cat = val.strip().strip('"\'')
                if cat:
                    return cat
    return None


def parse_task_line(
    line: str,
    line_number: int,
    file_path: Path,
    note_title: str,
    category: str,
) -> Optional[Task]:
    """Parst eine einzelne Zeile und extrahiert Checkbox-Daten und Metadaten."""
    m = CHECKBOX_PATTERN.match(line)
    if not m:
        return None

    indent, check_char, rest = m.groups()
    completed = check_char.lower() == "x"

    # Priorität ermitteln
    priority = None
    for emoji, prio in PRIORITY_MAP.items():
        if emoji in rest:
            priority = prio
            break

    # Fälligkeitsdatum
    due_date = None
    due_match = DUE_DATE_PATTERN.search(rest)
    if due_match:
        due_date = due_match.group(1)

    # Abschlussdatum
    completed_date = None
    done_match = DONE_DATE_PATTERN.search(rest)
    if done_match:
        completed_date = done_match.group(1)

    # Tags
    tags = TAG_PATTERN.findall(rest)

    # Reinen Text bereinigen (Metadaten entfernen für saubere Anzeige)
    clean_text = rest
    for emoji in PRIORITY_MAP.keys():
        clean_text = clean_text.replace(emoji, "")
    clean_text = DUE_DATE_PATTERN.sub("", clean_text)
    clean_text = DONE_DATE_PATTERN.sub("", clean_text)
    clean_text = TAG_PATTERN.sub("", clean_text).strip()

    # Eindeutige deterministische ID (Slug des Dateinamens + Zeilennummer)
    slug = re.sub(r"[^a-zA-Z0-9]", "", note_title.lower())[:8] or "task"
    task_id = f"{slug}:{line_number}"

    return Task(
        id=task_id,
        raw=line.rstrip("\r\n"),
        text=clean_text or rest.strip(),
        completed=completed,
        line_number=line_number,
        file_path=str(file_path.resolve()),
        note_title=note_title,
        category=category,
        priority=priority,
        due_date=due_date,
        completed_date=completed_date,
        tags=tags,
    )


def scan_notes(notes_dir: Path, default_category: str = "Allgemein") -> List[Note]:
    """Durchsucht das Notizenverzeichnis rekursiv nach .md-Dateien."""
    notes: List[Note] = []
    if not notes_dir.is_dir():
        return notes

    # Sortierte Liste aller .md Dateien
    for md_file in sorted(notes_dir.rglob("*.md")):
        if md_file.name.startswith("."):
            continue

        try:
            with open(md_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            continue

        # Kategorie ermitteln:
        # 1. Unterordner relativ zu notes_dir?
        rel_parent = md_file.parent.relative_to(notes_dir)
        category = default_category
        if str(rel_parent) != ".":
            category = rel_parent.parts[0]
        else:
            # 2. Frontmatter Fallback
            fm_cat = extract_frontmatter_category(lines)
            if fm_cat:
                category = fm_cat

        note_title = md_file.stem
        tasks: List[Task] = []
        for idx, line in enumerate(lines, start=1):
            t = parse_task_line(line, idx, md_file, note_title, category)
            if t:
                tasks.append(t)

        mtime = md_file.stat().st_mtime
        notes.append(
            Note(
                title=note_title,
                category=category,
                file_path=str(md_file.resolve()),
                mtime=mtime,
                tasks=tasks,
            )
        )

    return notes


def toggle_task(
    file_path: Path,
    line_number: int,
    append_completion_date: bool = True,
) -> Tuple[bool, str]:
    """Toggelt eine Checkbox atomar und threadsicher via POSIX flock."""
    if not file_path.is_file():
        return False, f"Datei nicht gefunden: {file_path}"

    try:
        with open(file_path, "r+", encoding="utf-8") as f:
            # Exklusives File Locking gegen Race Conditions
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                if line_number < 1 or line_number > len(lines):
                    return False, f"Ungültige Zeilennummer: {line_number}"

                target_line = lines[line_number - 1]
                m = CHECKBOX_PATTERN.match(target_line)
                if not m:
                    return False, f"Zeile {line_number} enthält keine Checkbox"

                indent, check_char, rest = m.groups()
                is_checked = check_char.lower() == "x"

                today_str = datetime.date.today().isoformat()
                if not is_checked:
                    # Von [ ] -> [x]
                    new_check = "[x]"
                    # Optionales Abschlussdatum anfügen
                    if append_completion_date and not DONE_DATE_PATTERN.search(rest):
                        rest = f"{rest.rstrip()} ✅ {today_str}"
                else:
                    # Von [x] -> [ ]
                    new_check = "[ ]"
                    # Abschlussdatum entfernen
                    rest = DONE_DATE_PATTERN.sub("", rest).rstrip()

                # Zeilenumbruch der Originalzeile erhalten
                ending = "\n" if target_line.endswith("\n") else ""
                lines[line_number - 1] = f"{indent}- {new_check} {rest}{ending}"

                # Atomares Schreiben via Tempdatei im selben Verzeichnis
                temp_fd, temp_path = tempfile.mkstemp(
                    dir=file_path.parent,
                    prefix=".omacheck_tmp_",
                    text=True,
                )
                with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
                    tf.writelines(lines)
                    tf.flush()
                    os.fsync(tf.fileno())

                os.replace(temp_path, file_path)
                status_str = "offen" if is_checked else "erledigt"
                return True, f"Aufgabe als {status_str} markiert"
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as err:
        return False, f"Fehler beim Aktualisieren: {err}"


def add_task(
    notes_dir: Path,
    text: str,
    note_title: Optional[str] = None,
    category: str = "Allgemein",
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    tag: Optional[str] = None,
) -> Tuple[bool, str]:
    """Fügt eine neue Checkbox-Aufgabe zu einer Notiz hinzu."""
    target_note_title = note_title.strip() if note_title else "Aufgaben"

    # Verzeichnis der Kategorie
    cat_dir = notes_dir if category == "Allgemein" else notes_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    target_file = cat_dir / f"{target_note_title}.md"

    # Task-Zeile formatieren
    tokens = [text.strip()]
    if tag:
        t = tag.lstrip("#")
        tokens.append(f"#{t}")
    if priority and priority.lower() in REV_PRIORITY_MAP:
        tokens.append(REV_PRIORITY_MAP[priority.lower()])
    if due_date:
        tokens.append(f"📅 {due_date.strip()}")

    task_line = f"- [ ] {' '.join(tokens)}\n"

    try:
        # Falls Datei noch nicht existiert: Erstellen mit Header
        if not target_file.is_file():
            content = f"# {target_note_title}\n\n## Aufgaben\n{task_line}"
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
            return True, f"Neue Notiz '{target_note_title}' mit Aufgabe erstellt"

        # Datei existiert: An Aufgaben-Bereich oder ans Ende anfügen
        with open(target_file, "r+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                # Sucht nach "## Aufgaben" o.ä.
                insert_idx = len(lines)
                for i, l in enumerate(lines):
                    if l.strip().lower() in ("## aufgaben", "## tasks", "## todo"):
                        insert_idx = i + 1
                        break

                if insert_idx == len(lines) and lines and not lines[-1].endswith("\n"):
                    lines[-1] += "\n"

                lines.insert(insert_idx, task_line)

                temp_fd, temp_path = tempfile.mkstemp(
                    dir=target_file.parent,
                    prefix=".omacheck_tmp_",
                    text=True,
                )
                with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
                    tf.writelines(lines)
                    tf.flush()
                    os.fsync(tf.fileno())

                os.replace(temp_path, target_file)
                return True, f"Aufgabe zu '{target_note_title}' hinzugefügt"
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as err:
        return False, f"Fehler beim Hinzufügen der Aufgabe: {err}"


def create_note(
    notes_dir: Path,
    title: str,
    category: str = "Allgemein",
    content: str = "",
) -> Tuple[bool, str]:
    """Erstellt eine neue Markdown-Notiz in der gewünschten Kategorie."""
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    if not clean_title:
        return False, "Ungültiger Notiztitel"

    cat_dir = notes_dir if category == "Allgemein" else notes_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    target_file = cat_dir / f"{clean_title}.md"

    if target_file.exists():
        return False, f"Notiz '{clean_title}' existiert bereits in '{category}'"

    template = f"# {clean_title}\n\n"
    if content:
        template += f"{content.strip()}\n\n"
    template += "## Aufgaben\n- [ ] Erste Aufgabe erledigen\n"

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(template)
        return True, f"Notiz erstellt: {target_file}"
    except Exception as err:
        return False, f"Fehler beim Erstellen der Notiz: {err}"


# ==============================================================================
# CLI Handler & Subkommandos
# ==============================================================================


def cmd_status(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, mode_desc = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    total_tasks = sum(len(n.tasks) for n in notes)
    open_tasks = sum(sum(1 for t in n.tasks if not t.completed) for n in notes)
    categories = sorted({n.category for n in notes})

    if args.json:
        data = {
            "mode": mode_desc,
            "notes_dir": str(notes_dir),
            "categories": categories,
            "notes_count": len(notes),
            "total_tasks": total_tasks,
            "open_tasks": open_tasks,
        }
        print(json.dumps(data, indent=2))
        return 0

    print("=== OmaCheck Status ===")
    print(f"Modus:            {mode_desc}")
    print(f"Notizen-Pfad:     {notes_dir}")
    print(f"Notizen gesamt:   {len(notes)}")
    print(f"Kategorien:       {', '.join(categories) if categories else 'Keine'}")
    print(f"Aufgaben offen:   {open_tasks} / {total_tasks}")
    return 0


def cmd_tasks(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, mode_desc = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    # Filter nach Kategorie
    if args.category:
        notes = [n for n in notes if n.category.lower() == args.category.lower()]

    all_tasks: List[Task] = []
    for n in notes:
        for t in n.tasks:
            if not args.all and t.completed:
                continue
            all_tasks.append(t)

    categories = sorted({n.category for n in scan_notes(notes_dir)})

    if args.json:
        out = {
            "mode": mode_desc,
            "notes_dir": str(notes_dir),
            "selected_category": args.category or "Alle",
            "categories": ["Alle"] + categories,
            "tasks_count": len(all_tasks),
            "notes": [n.to_dict() for n in notes],
            "tasks": [t.to_dict() for t in all_tasks],
        }
        print(json.dumps(out, indent=2))
        return 0

    if not all_tasks:
        print("Keine offenen Aufgaben gefunden.")
        return 0

    current_note = ""
    for t in all_tasks:
        if t.note_title != current_note:
            current_note = t.note_title
            print(f"\n📁 [{t.category}] {current_note}")
        status = "[x]" if t.completed else "[ ]"
        prio = f" {REV_PRIORITY_MAP[t.priority]}" if t.priority else ""
        due = f" 📅 {t.due_date}" if t.due_date else ""
        print(f"  {t.id:<10} {status} {t.text}{prio}{due}")

    return 0


def cmd_toggle(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, _ = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    # Suche Task nach ID
    matched_task: Optional[Task] = None
    for n in notes:
        for t in n.tasks:
            if t.id == args.task_id:
                matched_task = t
                break
        if matched_task:
            break

    if not matched_task:
        # Prüfe ob task_id im Format 'pfad:zeile' angegeben wurde
        if ":" in args.task_id:
            path_str, line_str = args.task_id.rsplit(":", 1)
            p = Path(path_str)
            if p.is_file() and line_str.isdigit():
                ok, msg = toggle_task(
                    p,
                    int(line_str),
                    config["tasks"]["append_completion_date"],
                )
                if args.json:
                    print(json.dumps({"success": ok, "message": msg}))
                else:
                    print(msg)
                return 0 if ok else 1

        msg = f"Aufgabe mit ID '{args.task_id}' nicht gefunden."
        if args.json:
            print(json.dumps({"success": False, "message": msg}))
        else:
            sys.stderr.write(f"Fehler: {msg}\n")
        return 1

    ok, msg = toggle_task(
        Path(matched_task.file_path),
        matched_task.line_number,
        config["tasks"]["append_completion_date"],
    )
    if args.json:
        print(json.dumps({"success": ok, "message": msg, "task_id": matched_task.id}))
    else:
        print(msg)
    return 0 if ok else 1


def cmd_add(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, _ = resolve_notes_directory(config)
    category = args.category or config["categories"]["default_category"]

    ok, msg = add_task(
        notes_dir=notes_dir,
        text=args.text,
        note_title=args.note,
        category=category,
        priority=args.priority,
        due_date=args.due,
        tag=args.tag,
    )

    if args.json:
        print(json.dumps({"success": ok, "message": msg}))
    else:
        print(msg if ok else f"Fehler: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_create_note(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, _ = resolve_notes_directory(config)
    category = args.category or config["categories"]["default_category"]

    ok, msg = create_note(
        notes_dir=notes_dir,
        title=args.title,
        category=category,
        content=args.content or "",
    )

    if args.json:
        print(json.dumps({"success": ok, "message": msg}))
    else:
        print(msg if ok else f"Fehler: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_categories(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, _ = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    cat_stats: Dict[str, Dict[str, int]] = {}
    for n in notes:
        if n.category not in cat_stats:
            cat_stats[n.category] = {"notes": 0, "open_tasks": 0, "total_tasks": 0}
        cat_stats[n.category]["notes"] += 1
        for t in n.tasks:
            cat_stats[n.category]["total_tasks"] += 1
            if not t.completed:
                cat_stats[n.category]["open_tasks"] += 1

    if args.json:
        print(json.dumps(cat_stats, indent=2))
        return 0

    if not cat_stats:
        print("Keine Kategorien vorhanden.")
        return 0

    print("=== Kategorien ===")
    for cat, stats in sorted(cat_stats.items()):
        print(f"📁 {cat:<15} ({stats['notes']} Notizen, {stats['open_tasks']}/{stats['total_tasks']} Aufgaben)")
    return 0


def launch_gui(config: Dict[str, Any]) -> int:
    shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
    if not (shell / "Ui").is_dir() or not shutil.which("quickshell"):
        sys.stderr.write("Fehler: Die GUI benötigt Omarchy mit Quickshell und den nativen UI-Komponenten.\n")
        return 1

    lock_file = Path(tempfile.gettempdir()) / "omacheck-gui.lock"
    lock = open(lock_file, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Fenster läuft bereits
        return 0

    project_root = Path(__file__).resolve().parent
    gui_qml = project_root / "Gui.qml"
    if not gui_qml.is_file():
        sys.stderr.write(f"Fehler: {gui_qml} nicht gefunden.\n")
        return 1

    with tempfile.TemporaryDirectory(prefix="omacheck-gui-") as tmp:
        root = Path(tmp)
        for module in ("Commons", "Ui"):
            (root / module).symlink_to(shell / module, target_is_directory=True)
        shutil.copyfile(gui_qml, root / "shell.qml")
        env = dict(
            os.environ,
            OMACHECK_BACKEND=str(project_root / "omacheck.py"),
            QT_QPA_PLATFORMTHEME="",
        )
        return subprocess.call(["quickshell", "-p", str(root)], env=env)


def cmd_gui(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    return launch_gui(config)


def main() -> int:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--json", action="store_true", help="Ausgabe als JSON formatieren")
    common_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Pfad zur config.json")

    parser = argparse.ArgumentParser(
        prog="omacheck",
        description="OmaCheck — Notizen- & To-Do-Engine für Omarchy Linux",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="Verfügbare Befehle")

    # gui / app
    p_gui = subparsers.add_parser("gui", parents=[common_parser], help="Startet die native Omarchy-App")
    p_gui.set_defaults(func=cmd_gui)

    p_app = subparsers.add_parser("app", parents=[common_parser], help="Startet die native Omarchy-App")
    p_app.set_defaults(func=cmd_gui)

    # status
    p_status = subparsers.add_parser("status", parents=[common_parser], help="Zeigt Vault- und Notizenstatus")
    p_status.set_defaults(func=cmd_status)

    # tasks
    p_tasks = subparsers.add_parser("tasks", parents=[common_parser], help="Listet alle Aufgaben / Checkboxen auf")
    p_tasks.add_argument("-c", "--category", help="Nach Kategorie filtern")
    p_tasks.add_argument("-a", "--all", action="store_true", help="Auch erledigte Aufgaben anzeigen")
    p_tasks.set_defaults(func=cmd_tasks)

    # toggle
    p_toggle = subparsers.add_parser("toggle", parents=[common_parser], help="Hakt eine Checkbox ab (- [ ] <-> - [x])")
    p_toggle.add_argument("task_id", help="ID der Aufgabe (z. B. sprint:8 oder datei.md:8)")
    p_toggle.set_defaults(func=cmd_toggle)

    # add
    p_add = subparsers.add_parser("add", parents=[common_parser], help="Fügt eine neue Checkbox-Aufgabe hinzu")
    p_add.add_argument("text", help="Text der Aufgabe")
    p_add.add_argument("-c", "--category", help="Kategorie der Notiz")
    p_add.add_argument("-n", "--note", help="Name der Notiz (Standard: Aufgaben)")
    p_add.add_argument("-p", "--priority", choices=["high", "medium", "low"], help="Priorität")
    p_add.add_argument("-d", "--due", help="Fälligkeitsdatum (YYYY-MM-DD)")
    p_add.add_argument("-t", "--tag", help="Tag (ohne #)")
    p_add.set_defaults(func=cmd_add)

    # note create
    p_note = subparsers.add_parser("create-note", parents=[common_parser], help="Erstellt eine neue Notiz")
    p_note.add_argument("title", help="Titel der Notiz")
    p_note.add_argument("-c", "--category", help="Kategorie der Notiz")
    p_note.add_argument("--content", help="Initialer Textinhalt")
    p_note.set_defaults(func=cmd_create_note)

    # categories
    p_cats = subparsers.add_parser("categories", parents=[common_parser], help="Listet alle Kategorien auf")
    p_cats.set_defaults(func=cmd_categories)

    args = parser.parse_args()
    if not args.command:
        # Standardaktion: Aufgaben anzeigen
        args.category = None
        args.all = False
        config = load_config(args.config)
        return cmd_tasks(args, config)

    config = load_config(args.config)
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
