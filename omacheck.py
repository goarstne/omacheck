#!/usr/bin/env python3
"""OmaCheck — Universal notes & to-do engine for Omarchy Linux.

Manages Markdown notes with interactive checkboxes, optional categories,
and optional Obsidian vault integration, following the Ponytail principle
(zero dependencies).
"""

import argparse
import datetime
import fcntl
import hashlib
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
DEFAULT_STANDALONE_DIR = Path.home() / "Documents" / "OmaCheck"
OMARCHY_SHELL_CONFIG_PATH = Path.home() / ".config" / "omarchy" / "shell.json"

PLUGIN_ID = "carsten.omacheck"
BAR_WIDGET_DEFAULT_SECTION = "right"
BAR_SECTIONS = ("left", "center", "right")
DEFAULT_CATEGORY = "General"
ALL_CATEGORIES_LABEL = "All"

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
    """Loads the configuration or returns safe defaults."""
    defaults: Dict[str, Any] = {
        "storage": {
            # 'standalone' (default, ~/Documents/OmaCheck), 'obsidian', or the
            # legacy 'auto' (try the open Obsidian vault, else standalone).
            "mode": "standalone",
            "obsidian_vault": "auto",
            "notes_dir_name": "Notes",
            "fallback_dir": str(DEFAULT_STANDALONE_DIR),
        },
        "categories": {
            "default_category": DEFAULT_CATEGORY,
            "pinned": ["Work", "Personal", "Ideas"],
        },
        "tasks": {
            "append_completion_date": True,
        },
        "widgets": {
            # Bar widget is off by default, even for existing installs
            # without an explicit preference in config.json.
            "bar_enabled": False,
            # Desktop widget is on by default, so existing installs keep
            # their previous behavior.
            "desktop_enabled": True,
        },
    }
    if not config_path.is_file():
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
            # Shallow-merge for storage, categories, tasks and widgets
            for section in ["storage", "categories", "tasks", "widgets"]:
                if section in user_config and isinstance(user_config[section], dict):
                    defaults[section].update(user_config[section])
            return defaults
    except Exception as err:
        sys.stderr.write(f"Warning: Could not read {config_path}: {err}\n")
        return defaults


def _load_config_file_strict(config_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Reads config.json raw, without merging defaults — for safe write paths.

    Unlike load_config(), this does NOT fall back to defaults on broken JSON:
    (None, error message) means the caller must not overwrite the file. A
    missing file is not an error (fresh install).
    """
    if not config_path.is_file():
        return {}, None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as err:
        return None, f"Invalid {config_path}, not overwritten: {err}"
    if not isinstance(data, dict):
        return None, f"Invalid {config_path} (not an object), not overwritten"
    return data, None


def save_config(config: Dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> Tuple[bool, str]:
    """Saves the configuration atomically (temp file + os.replace)."""
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(
            dir=config_path.parent, prefix=".omacheck_cfg_tmp_", text=True
        )
        with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
            json.dump(config, tf, indent=2, ensure_ascii=False)
            tf.write("\n")
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(temp_path, config_path)
        return True, f"Configuration saved: {config_path}"
    except Exception as err:
        return False, f"Error saving configuration: {err}"


def detect_obsidian_vault() -> Optional[Path]:
    """Reads the active Obsidian vaults from ~/.config/obsidian/obsidian.json."""
    if not OBSIDIAN_CONFIG_PATH.is_file():
        return None
    try:
        with open(OBSIDIAN_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        vaults = data.get("vaults", {})
        # Prefer the vault that is currently open
        for v in vaults.values():
            if v.get("open") and v.get("path"):
                p = Path(v["path"]).expanduser().resolve()
                if p.is_dir():
                    return p
        # Fall back to the first valid path
        for v in vaults.values():
            if v.get("path"):
                p = Path(v["path"]).expanduser().resolve()
                if p.is_dir():
                    return p
    except Exception:
        pass
    return None


def resolve_notes_directory(config: Dict[str, Any]) -> Tuple[Path, str]:
    """Determines the active notes directory based on config and system state."""
    mode = config["storage"].get("mode", "standalone")
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

    # Standalone fallback (also used when obsidian mode has no vault yet)
    fallback = Path(config["storage"].get("fallback_dir", str(DEFAULT_STANDALONE_DIR))).expanduser().resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback, "standalone"


def extract_frontmatter_category(lines: List[str]) -> Optional[str]:
    """Reads the optional category from a note's YAML frontmatter."""
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
    notes_dir: Optional[Path] = None,
) -> Optional[Task]:
    """Parses a single line and extracts checkbox data and metadata."""
    m = CHECKBOX_PATTERN.match(line)
    if not m:
        return None

    indent, check_char, rest = m.groups()
    completed = check_char.lower() == "x"

    # Priority
    priority = None
    for emoji, prio in PRIORITY_MAP.items():
        if emoji in rest:
            priority = prio
            break

    # Due date
    due_date = None
    due_match = DUE_DATE_PATTERN.search(rest)
    if due_match:
        due_date = due_match.group(1)

    # Completion date
    completed_date = None
    done_match = DONE_DATE_PATTERN.search(rest)
    if done_match:
        completed_date = done_match.group(1)

    # Tags
    tags = TAG_PATTERN.findall(rest)

    # Clean text (strip metadata for display)
    clean_text = rest
    for emoji in PRIORITY_MAP.keys():
        clean_text = clean_text.replace(emoji, "")
    clean_text = DUE_DATE_PATTERN.sub("", clean_text)
    clean_text = DONE_DATE_PATTERN.sub("", clean_text)
    clean_text = TAG_PATTERN.sub("", clean_text).strip()

    # Deterministic unique ID: derived from the note's path *relative to the
    # notes root*, not just its title — two notes with the same filename in
    # different category folders (e.g. General/Tasks.md and Work/Tasks.md)
    # otherwise produce identical IDs, so clicking a checkbox in one silently
    # toggles a same-numbered line in the other file instead.
    if notes_dir is not None:
        try:
            slug_source = str(file_path.resolve().relative_to(notes_dir.resolve()).with_suffix(""))
        except ValueError:
            slug_source = note_title
    else:
        slug_source = note_title
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", slug_source.lower()).strip("-")[:24] or "task"
    digest = hashlib.sha1(slug_source.encode("utf-8")).hexdigest()[:6]
    task_id = f"{slug}-{digest}:{line_number}"

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


def scan_notes(notes_dir: Path, default_category: str = DEFAULT_CATEGORY) -> List[Note]:
    """Recursively scans the notes directory for .md files."""
    notes: List[Note] = []
    if not notes_dir.is_dir():
        return notes

    # Sorted list of all .md files
    for md_file in sorted(notes_dir.rglob("*.md")):
        if md_file.name.startswith("."):
            continue

        try:
            with open(md_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            continue

        # Determine category:
        # 1. Subfolder relative to notes_dir?
        rel_parent = md_file.parent.relative_to(notes_dir)
        category = default_category
        if str(rel_parent) != ".":
            category = rel_parent.parts[0]
        else:
            # 2. Frontmatter fallback
            fm_cat = extract_frontmatter_category(lines)
            if fm_cat:
                category = fm_cat

        note_title = md_file.stem
        tasks: List[Task] = []
        for idx, line in enumerate(lines, start=1):
            t = parse_task_line(line, idx, md_file, note_title, category, notes_dir)
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
    """Toggles a checkbox atomically and thread-safely via POSIX flock."""
    if not file_path.is_file():
        return False, f"File not found: {file_path}"

    try:
        with open(file_path, "r+", encoding="utf-8") as f:
            # Exclusive file lock against race conditions
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                if line_number < 1 or line_number > len(lines):
                    return False, f"Invalid line number: {line_number}"

                target_line = lines[line_number - 1]
                m = CHECKBOX_PATTERN.match(target_line)
                if not m:
                    return False, f"Line {line_number} does not contain a checkbox"

                indent, check_char, rest = m.groups()
                is_checked = check_char.lower() == "x"

                today_str = datetime.date.today().isoformat()
                if not is_checked:
                    # [ ] -> [x]
                    new_check = "[x]"
                    # Optionally append completion date
                    if append_completion_date and not DONE_DATE_PATTERN.search(rest):
                        rest = f"{rest.rstrip()} ✅ {today_str}"
                else:
                    # [x] -> [ ]
                    new_check = "[ ]"
                    # Remove completion date
                    rest = DONE_DATE_PATTERN.sub("", rest).rstrip()

                # Preserve the original line ending
                ending = "\n" if target_line.endswith("\n") else ""
                lines[line_number - 1] = f"{indent}- {new_check} {rest}{ending}"

                # Atomic write via temp file in the same directory
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
                status_str = "open" if is_checked else "done"
                return True, f"Task marked as {status_str}"
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as err:
        return False, f"Error updating task: {err}"


def delete_task(file_path: Path, line_number: int) -> Tuple[bool, str]:
    """Deletes a checkbox line atomically and thread-safely via POSIX flock."""
    if not file_path.is_file():
        return False, f"File not found: {file_path}"

    try:
        with open(file_path, "r+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                if line_number < 1 or line_number > len(lines):
                    return False, f"Invalid line number: {line_number}"

                target_line = lines[line_number - 1]
                if not CHECKBOX_PATTERN.match(target_line):
                    return False, f"Line {line_number} does not contain a checkbox"

                del lines[line_number - 1]

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
                return True, "Task deleted"
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as err:
        return False, f"Error deleting task: {err}"


def add_task(
    notes_dir: Path,
    text: str,
    note_title: Optional[str] = None,
    category: str = DEFAULT_CATEGORY,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    tag: Optional[str] = None,
) -> Tuple[bool, str]:
    """Adds a new checkbox task to a note."""
    target_note_title = note_title.strip() if note_title else "Tasks"

    # Category directory
    cat_dir = notes_dir if category == DEFAULT_CATEGORY else notes_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    target_file = cat_dir / f"{target_note_title}.md"

    # Format the task line
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
        # If the file doesn't exist yet: create it with a header
        if not target_file.is_file():
            content = f"# {target_note_title}\n\n## Tasks\n{task_line}"
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
            return True, f"New note '{target_note_title}' created with task"

        # File exists: append to the tasks section or to the end
        with open(target_file, "r+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                # Look for a "## Tasks"-style heading
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
                return True, f"Task added to '{target_note_title}'"
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as err:
        return False, f"Error adding task: {err}"


def create_note(
    notes_dir: Path,
    title: str,
    category: str = DEFAULT_CATEGORY,
    content: str = "",
) -> Tuple[bool, str]:
    """Creates a new Markdown note in the requested category."""
    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    if not clean_title:
        return False, "Invalid note title"

    cat_dir = notes_dir if category == DEFAULT_CATEGORY else notes_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    target_file = cat_dir / f"{clean_title}.md"

    if target_file.exists():
        return False, f"Note '{clean_title}' already exists in '{category}'"

    template = f"# {clean_title}\n\n"
    if content:
        template += f"{content.strip()}\n\n"
    template += "## Tasks\n- [ ] First task to complete\n"

    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(template)
        return True, f"Note created: {target_file}"
    except Exception as err:
        return False, f"Error creating note: {err}"


def add_category(name: str, config_path: Path) -> Tuple[bool, str]:
    """Pins a category name in config.json so it shows up even before any
    note exists in it. Categories are otherwise derived purely from note
    subfolders/frontmatter, so a brand-new one needs an explicit pin."""
    clean_name = name.strip()
    if not clean_name:
        return False, "Category name cannot be empty"

    raw, err = _load_config_file_strict(config_path)
    if raw is None:
        return False, err

    categories = raw.get("categories")
    if not isinstance(categories, dict):
        categories = {}
    pinned = categories.get("pinned")
    if not isinstance(pinned, list):
        pinned = []
    if clean_name not in pinned:
        pinned = pinned + [clean_name]
    categories["pinned"] = pinned
    raw["categories"] = categories

    save_ok, save_msg = save_config(raw, config_path)
    if not save_ok:
        return False, save_msg
    return True, f"Category '{clean_name}' added"


def remove_category(
    name: str,
    config_path: Path,
    notes_dir: Path,
    default_category: str = DEFAULT_CATEGORY,
) -> Tuple[bool, str]:
    """Un-pins a category. Refuses if real notes still live under it (folder-
    based categories come back from the next scan regardless of the pin, so
    silently "succeeding" there would just be confusing) or if it is the
    reserved default/all-categories name."""
    clean_name = name.strip()
    if not clean_name:
        return False, "Category name cannot be empty"
    if clean_name in (default_category, ALL_CATEGORIES_LABEL):
        return False, f"Cannot remove the '{clean_name}' category"

    notes = scan_notes(notes_dir, default_category)
    if any(n.category == clean_name for n in notes):
        return False, f"Category '{clean_name}' still has notes; move or delete them first"

    raw, err = _load_config_file_strict(config_path)
    if raw is None:
        return False, err

    categories = raw.get("categories")
    pinned = categories.get("pinned") if isinstance(categories, dict) else None
    if not isinstance(pinned, list) or clean_name not in pinned:
        return False, f"Category '{clean_name}' is not pinned"

    categories["pinned"] = [c for c in pinned if c != clean_name]
    raw["categories"] = categories

    save_ok, save_msg = save_config(raw, config_path)
    if not save_ok:
        return False, save_msg
    return True, f"Category '{clean_name}' removed"


def _bar_entry_id(entry: Any) -> Any:
    return entry.get("id") if isinstance(entry, dict) else entry


def read_bar_widget_live_state(shell_config_path: Optional[Path] = None) -> Optional[bool]:
    """Checks whether carsten.omacheck currently sits in a bar.layout section.

    None means: shell.json is missing or unreadable/invalid (state unknown).
    """
    path = shell_config_path or OMARCHY_SHELL_CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    bar = data.get("bar")
    layout = bar.get("layout") if isinstance(bar, dict) else None
    if not isinstance(layout, dict):
        return False

    for section in BAR_SECTIONS:
        entries = layout.get(section)
        if not isinstance(entries, list):
            continue
        if any(_bar_entry_id(e) == PLUGIN_ID for e in entries):
            return True
    return False


def set_bar_widget_enabled(
    enabled: bool,
    shell_config_path: Optional[Path] = None,
    section: str = BAR_WIDGET_DEFAULT_SECTION,
) -> Tuple[bool, str]:
    """Manages the carsten.omacheck entry in bar.layout specifically.

    Other widgets/sections and unknown config keys are left untouched. The
    entry in plugins[] is ALWAYS ensured (regardless of `enabled`), because
    per Omarchy's PluginRegistry.isEnabled() a plugin only stays active if it
    is referenced either in bar.layout OR in plugins[] — otherwise removing
    it from the bar would also disable the desktop service (Service.qml).
    """
    shell_config_path = shell_config_path or OMARCHY_SHELL_CONFIG_PATH
    if not shell_config_path.is_file():
        return False, f"{shell_config_path} not found — live bar not changed"

    try:
        with open(shell_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as err:
        return False, f"Invalid shell.json, not overwritten: {err}"

    if not isinstance(data, dict):
        return False, "Invalid shell.json (not an object), not overwritten"

    bar = data.get("bar")
    if not isinstance(bar, dict):
        return False, "shell.json has no valid 'bar' section"
    layout = bar.get("layout")
    if not isinstance(layout, dict):
        return False, "shell.json has no valid 'bar.layout' section"

    changed = False
    found = False
    for sec in BAR_SECTIONS:
        entries = layout.get(sec)
        if not isinstance(entries, list):
            continue
        kept: List[Any] = []
        for entry in entries:
            if _bar_entry_id(entry) == PLUGIN_ID:
                found = True
                if enabled:
                    kept.append(entry)  # already present: keep position/options
                else:
                    changed = True  # removed
            else:
                kept.append(entry)
        layout[sec] = kept

    if enabled and not found:
        target = layout.get(section)
        if not isinstance(target, list):
            target = []
        target.append({"id": PLUGIN_ID})
        layout[section] = target
        changed = True

    # Keep the desktop service (kind "service") alive regardless of bar status.
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        plugins = []
    if not any(_bar_entry_id(e) == PLUGIN_ID for e in plugins):
        plugins = plugins + [{"id": PLUGIN_ID}]
        data["plugins"] = plugins
        changed = True
    else:
        data["plugins"] = plugins

    if not changed:
        return True, "Bar widget status already up to date"

    try:
        temp_fd, temp_path = tempfile.mkstemp(
            dir=shell_config_path.parent, prefix=".omacheck_shell_tmp_", text=True
        )
        with os.fdopen(temp_fd, "w", encoding="utf-8") as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False)
            tf.write("\n")
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(temp_path, shell_config_path)
    except Exception as err:
        return False, f"Error writing shell.json: {err}"

    return True, f"Bar widget {'enabled' if enabled else 'disabled'}"


def apply_bar_widget_setting(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Applies the saved widgets.bar_enabled preference to the live bar.

    Only reads the preference, never changes config.json. Meant for the
    installer (e.g. `import omacheck; omacheck.apply_bar_widget_setting(config)`).
    """
    enabled = bool(config.get("widgets", {}).get("bar_enabled", False))
    return set_bar_widget_enabled(enabled)


# ==============================================================================
# CLI handlers & subcommands
# ==============================================================================


def cmd_status(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, mode_desc = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    total_tasks = sum(len(n.tasks) for n in notes)
    open_tasks = sum(sum(1 for t in n.tasks if not t.completed) for n in notes)
    pinned = config["categories"].get("pinned", [])
    categories = sorted({n.category for n in notes} | set(pinned))

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
    print(f"Mode:             {mode_desc}")
    print(f"Notes path:       {notes_dir}")
    print(f"Total notes:      {len(notes)}")
    print(f"Categories:       {', '.join(categories) if categories else 'None'}")
    print(f"Open tasks:       {open_tasks} / {total_tasks}")
    return 0


def cmd_tasks(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, mode_desc = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    # Filter by category
    if args.category:
        notes = [n for n in notes if n.category.lower() == args.category.lower()]

    all_tasks: List[Task] = []
    for n in notes:
        for t in n.tasks:
            if not args.all and t.completed:
                continue
            all_tasks.append(t)

    pinned = config["categories"].get("pinned", [])
    # ALL_CATEGORIES_LABEL is a reserved sentinel meaning "no filter" (always
    # prepended below) — exclude it here so a real folder/pinned category
    # that happens to be named "All" doesn't produce a duplicate tab.
    categories = sorted(
        ({n.category for n in scan_notes(notes_dir)} | set(pinned)) - {ALL_CATEGORIES_LABEL}
    )

    if args.json:
        out = {
            "mode": mode_desc,
            "notes_dir": str(notes_dir),
            "selected_category": args.category or ALL_CATEGORIES_LABEL,
            "categories": [ALL_CATEGORIES_LABEL] + categories,
            "tasks_count": len(all_tasks),
            "notes": [n.to_dict() for n in notes],
            "tasks": [t.to_dict() for t in all_tasks],
        }
        print(json.dumps(out, indent=2))
        return 0

    if not all_tasks:
        print("No open tasks found.")
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


def _resolve_task_target(task_id: str, notes: List[Note]) -> Tuple[Optional[Path], Optional[int]]:
    """Resolves a task_id to (file_path, line_number) via scanned notes, or via
    a raw 'path:line' fallback (e.g. for a task in a file outside notes_dir).
    Returns (None, None) if neither resolves."""
    for n in notes:
        for t in n.tasks:
            if t.id == task_id:
                return Path(t.file_path), t.line_number
    if ":" in task_id:
        path_str, line_str = task_id.rsplit(":", 1)
        p = Path(path_str)
        if p.is_file() and line_str.isdigit():
            return p, int(line_str)
    return None, None


def cmd_toggle(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, _ = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    file_path, line_number = _resolve_task_target(args.task_id, notes)
    if file_path is None:
        msg = f"Task with ID '{args.task_id}' not found."
        if args.json:
            print(json.dumps({"success": False, "message": msg}))
        else:
            sys.stderr.write(f"Error: {msg}\n")
        return 1

    ok, msg = toggle_task(file_path, line_number, config["tasks"]["append_completion_date"])
    if args.json:
        print(json.dumps({"success": ok, "message": msg, "task_id": args.task_id}))
    else:
        print(msg)
    return 0 if ok else 1


def cmd_delete(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    notes_dir, _ = resolve_notes_directory(config)
    notes = scan_notes(notes_dir, config["categories"]["default_category"])

    file_path, line_number = _resolve_task_target(args.task_id, notes)
    if file_path is None:
        msg = f"Task with ID '{args.task_id}' not found."
        if args.json:
            print(json.dumps({"success": False, "message": msg}))
        else:
            sys.stderr.write(f"Error: {msg}\n")
        return 1

    ok, msg = delete_task(file_path, line_number)
    if args.json:
        print(json.dumps({"success": ok, "message": msg, "task_id": args.task_id}))
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
        print(msg if ok else f"Error: {msg}", file=sys.stdout if ok else sys.stderr)
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
        print(msg if ok else f"Error: {msg}", file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_categories(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    if args.add:
        ok, msg = add_category(args.add, args.config)
        if args.json:
            print(json.dumps({"success": ok, "message": msg}))
        else:
            print(msg if ok else f"Error: {msg}", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if args.remove:
        notes_dir, _ = resolve_notes_directory(config)
        ok, msg = remove_category(
            args.remove, args.config, notes_dir, config["categories"]["default_category"]
        )
        if args.json:
            print(json.dumps({"success": ok, "message": msg}))
        else:
            print(msg if ok else f"Error: {msg}", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

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

    # Pinned categories show up even before any note exists in them.
    for name in config["categories"].get("pinned", []):
        cat_stats.setdefault(name, {"notes": 0, "open_tasks": 0, "total_tasks": 0})

    if args.json:
        print(json.dumps(cat_stats, indent=2))
        return 0

    if not cat_stats:
        print("No categories yet.")
        return 0

    print("=== Categories ===")
    for cat, stats in sorted(cat_stats.items()):
        print(f"📁 {cat:<15} ({stats['notes']} notes, {stats['open_tasks']}/{stats['total_tasks']} tasks)")
    return 0


def _write_config_pref(section: str, key: str, value: Any, config_path: Path, json_output: bool) -> Optional[str]:
    """Sets config[section][key] raw in config.json, all other keys untouched.

    Returns None on success, else an error message (already printed).
    """
    raw, err = _load_config_file_strict(config_path)
    if raw is None:
        if json_output:
            print(json.dumps({"success": False, "message": err}))
        else:
            sys.stderr.write(f"Error: {err}\n")
        return err

    sect = raw.get(section)
    if not isinstance(sect, dict):
        sect = {}
    sect[key] = value
    raw[section] = sect

    save_ok, save_msg = save_config(raw, config_path)
    if not save_ok:
        if json_output:
            print(json.dumps({"success": False, "message": save_msg}))
        else:
            sys.stderr.write(f"Error: {save_msg}\n")
        return save_msg
    return None


def cmd_settings(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    live_ok: Optional[bool] = None
    live_msg = ""
    # Only relevant for a plain "settings --json" with no flags: merged default view.
    preference = bool(config.get("widgets", {}).get("bar_enabled", False))
    desktop_preference = bool(config.get("widgets", {}).get("desktop_enabled", True))
    storage_mode_preference = str(config.get("storage", {}).get("mode", "standalone"))

    if args.desktop_widget is not None:
        # Purely config.json-driven: Service.qml reads desktop_enabled
        # directly (Omarchy has no per-kind plugin enable/disable), so no
        # shell.json application is needed like for the bar widget.
        enabled = args.desktop_widget == "on"
        if _write_config_pref("widgets", "desktop_enabled", enabled, args.config, args.json) is not None:
            return 1
        desktop_preference = enabled

    if args.storage_mode is not None:
        if _write_config_pref("storage", "mode", args.storage_mode, args.config, args.json) is not None:
            return 1
        storage_mode_preference = args.storage_mode

    if args.bar_widget is not None:
        enabled = args.bar_widget == "on"
        if _write_config_pref("widgets", "bar_enabled", enabled, args.config, args.json) is not None:
            return 1
        live_ok, live_msg = set_bar_widget_enabled(enabled)
        preference = enabled

    elif args.apply:
        # Equally strict: --apply must never silently treat a broken
        # config.json as "false" and apply that.
        raw, err = _load_config_file_strict(args.config)
        if raw is None:
            if args.json:
                print(json.dumps({"success": False, "message": err}))
            else:
                sys.stderr.write(f"Error: {err}\n")
            return 1

        widgets = raw.get("widgets")
        preference = bool(widgets.get("bar_enabled", False)) if isinstance(widgets, dict) else False
        live_ok, live_msg = set_bar_widget_enabled(preference)

    data = {
        "widgets": {
            "bar_enabled_preference": preference,
            "bar_enabled_live": read_bar_widget_live_state(),
            "desktop_enabled_preference": desktop_preference,
        },
        "storage": {
            "mode_preference": storage_mode_preference,
        },
    }
    if live_ok is not None:
        data["widgets"]["bar_widget_write_ok"] = live_ok
        data["widgets"]["bar_widget_message"] = live_msg

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        pref = data["widgets"]["bar_enabled_preference"]
        live = data["widgets"]["bar_enabled_live"]
        live_str = "unknown" if live is None else ("on" if live else "off")
        print(f"Bar widget (saved preference): {'on' if pref else 'off'}")
        print(f"Bar widget (actual bar state): {live_str}")
        if live_ok is not None:
            print(live_msg)
        print(f"Desktop widget: {'on' if desktop_preference else 'off'}")
        print(f"Storage mode:   {storage_mode_preference}")

    if args.bar_widget is not None or args.apply:
        return 0 if live_ok else 1
    return 0


def launch_gui(config: Dict[str, Any]) -> int:
    """Opens the app window in the already-running omarchy-shell.

    The app is a `panel`-kind entry point of this same plugin
    (plugin/AppPanel.qml), loaded in-process like every other Omarchy panel
    (see omarchy.menu) — not a separate `quickshell -p` process. Toggling
    (rather than only summoning) matches the bar widget's own click
    behavior: open on the first call, close on the next.
    """
    if not shutil.which("omarchy-shell"):
        sys.stderr.write("Error: The GUI requires omarchy-shell to be running.\n")
        return 1
    return subprocess.call(["omarchy-shell", "shell", "toggle", PLUGIN_ID])


def cmd_gui(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    return launch_gui(config)


def main() -> int:
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--json", action="store_true", help="Format output as JSON")
    common_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to config.json")

    parser = argparse.ArgumentParser(
        prog="omacheck",
        description="OmaCheck — notes & to-do engine for Omarchy Linux",
        parents=[common_parser],
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # gui / app
    p_gui = subparsers.add_parser("gui", parents=[common_parser], help="Launches the native Omarchy app")
    p_gui.set_defaults(func=cmd_gui)

    p_app = subparsers.add_parser("app", parents=[common_parser], help="Launches the native Omarchy app")
    p_app.set_defaults(func=cmd_gui)

    # status
    p_status = subparsers.add_parser("status", parents=[common_parser], help="Shows storage and notes status")
    p_status.set_defaults(func=cmd_status)

    # tasks
    p_tasks = subparsers.add_parser("tasks", parents=[common_parser], help="Lists all tasks / checkboxes")
    p_tasks.add_argument("-c", "--category", help="Filter by category")
    p_tasks.add_argument("-a", "--all", action="store_true", help="Also show completed tasks")
    p_tasks.set_defaults(func=cmd_tasks)

    # toggle
    p_toggle = subparsers.add_parser("toggle", parents=[common_parser], help="Toggles a checkbox (- [ ] <-> - [x])")
    p_toggle.add_argument("task_id", help="Task ID (e.g. sprint:8 or file.md:8)")
    p_toggle.set_defaults(func=cmd_toggle)

    # delete
    p_delete = subparsers.add_parser("delete", parents=[common_parser], help="Deletes a checkbox task")
    p_delete.add_argument("task_id", help="Task ID (e.g. sprint:8 or file.md:8)")
    p_delete.set_defaults(func=cmd_delete)

    # add
    p_add = subparsers.add_parser("add", parents=[common_parser], help="Adds a new checkbox task")
    p_add.add_argument("text", help="Task text")
    p_add.add_argument("-c", "--category", help="Category of the note")
    p_add.add_argument("-n", "--note", help="Note name (default: Tasks)")
    p_add.add_argument("-p", "--priority", choices=["high", "medium", "low"], help="Priority")
    p_add.add_argument("-d", "--due", help="Due date (YYYY-MM-DD)")
    p_add.add_argument("-t", "--tag", help="Tag (without #)")
    p_add.set_defaults(func=cmd_add)

    # note create
    p_note = subparsers.add_parser("create-note", parents=[common_parser], help="Creates a new note")
    p_note.add_argument("title", help="Note title")
    p_note.add_argument("-c", "--category", help="Category of the note")
    p_note.add_argument("--content", help="Initial text content")
    p_note.set_defaults(func=cmd_create_note)

    # categories
    p_cats = subparsers.add_parser("categories", parents=[common_parser], help="Lists all categories")
    p_cats.add_argument("--add", metavar="NAME", help="Pin a new category, even before it has a note")
    p_cats.add_argument(
        "--remove", metavar="NAME", help="Un-pin a category (fails if it still has notes)"
    )
    p_cats.set_defaults(func=cmd_categories)

    # settings
    p_settings = subparsers.add_parser(
        "settings", parents=[common_parser], help="Shows/changes settings (bar widget, desktop widget, storage mode)"
    )
    p_settings.add_argument(
        "--bar-widget",
        choices=["on", "off"],
        help="Enable/disable the bar widget (persists + applies to the live bar)",
    )
    p_settings.add_argument(
        "--desktop-widget",
        choices=["on", "off"],
        help="Enable/disable the desktop widget (permanent on the wallpaper)",
    )
    p_settings.add_argument(
        "--storage-mode",
        choices=["standalone", "obsidian"],
        help="Store notes under ~/Documents/OmaCheck (standalone) or in an Obsidian vault",
    )
    p_settings.add_argument(
        "--apply",
        action="store_true",
        help="Apply saved preferences to the live bar without changing them (for the installer)",
    )
    p_settings.set_defaults(func=cmd_settings)

    args = parser.parse_args()
    if not args.command:
        # Default action: show tasks
        args.category = None
        args.all = False
        config = load_config(args.config)
        return cmd_tasks(args, config)

    config = load_config(args.config)
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
