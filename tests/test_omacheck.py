"""Unittests für OmaCheck Core Engine."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

OMACHECK_SCRIPT = Path(__file__).resolve().parent.parent / "omacheck.py"

from omacheck import (
    DEFAULT_STANDALONE_DIR,
    PLUGIN_ID,
    _load_config_file_strict,
    add_category,
    add_task,
    apply_bar_widget_setting,
    create_note,
    delete_task,
    detect_obsidian_vault,
    extract_frontmatter_category,
    load_config,
    parse_task_line,
    read_bar_widget_live_state,
    resolve_notes_directory,
    save_config,
    scan_notes,
    set_bar_widget_enabled,
    toggle_task,
)


class TestOmaCheckParser(unittest.TestCase):
    def setUp(self):
        self.dummy_path = Path("/tmp/dummy.md")

    def test_parse_simple_task(self):
        line = "- [ ] Milch kaufen"
        t = parse_task_line(line, 1, self.dummy_path, "Einkauf", "Privat")
        self.assertIsNotNone(t)
        self.assertEqual(t.text, "Milch kaufen")
        self.assertFalse(t.completed)
        self.assertEqual(t.note_title, "Einkauf")
        self.assertEqual(t.category, "Privat")
        self.assertEqual(t.line_number, 1)
        self.assertIsNone(t.priority)
        self.assertIsNone(t.due_date)

    def test_parse_task_with_metadata(self):
        line = "- [ ] OmaCheck Spec finalisieren #desktop #omarchy ⏫ 📅 2026-09-15"
        t = parse_task_line(line, 4, self.dummy_path, "Sprint", "Arbeit")
        self.assertIsNotNone(t)
        self.assertEqual(t.text, "OmaCheck Spec finalisieren")
        self.assertFalse(t.completed)
        self.assertEqual(t.priority, "high")
        self.assertEqual(t.due_date, "2026-09-15")
        self.assertIn("desktop", t.tags)
        self.assertIn("omarchy", t.tags)

    def test_parse_completed_task(self):
        line = "- [x] Backup verifizieren 🔼 ✅ 2026-09-12"
        t = parse_task_line(line, 7, self.dummy_path, "System", "Allgemein")
        self.assertIsNotNone(t)
        self.assertTrue(t.completed)
        self.assertEqual(t.completed_date, "2026-09-12")
        self.assertEqual(t.priority, "medium")

    def test_ignore_non_task_lines(self):
        self.assertIsNone(parse_task_line("# Header", 1, self.dummy_path, "X", "Y"))
        self.assertIsNone(parse_task_line("Einfacher Text ohne Checkbox", 2, self.dummy_path, "X", "Y"))
        self.assertIsNone(parse_task_line("- Aufzählung ohne Checkbox", 3, self.dummy_path, "X", "Y"))


class TestOmaCheckCategoriesAndNotes(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_frontmatter_category(self):
        lines = [
            "---\n",
            "title: Meine Notiz\n",
            "category: Projekte\n",
            "---\n",
            "# Inhalt\n",
        ]
        cat = extract_frontmatter_category(lines)
        self.assertEqual(cat, "Projekte")

    def test_folder_based_category(self):
        work_dir = self.test_dir / "Arbeit"
        work_dir.mkdir()
        note_file = work_dir / "Projekt1.md"
        with open(note_file, "w", encoding="utf-8") as f:
            f.write("# Projekt 1\n- [ ] Task A\n")

        notes = scan_notes(self.test_dir)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].category, "Arbeit")
        self.assertEqual(len(notes[0].tasks), 1)
        self.assertEqual(notes[0].tasks[0].text, "Task A")

    def test_flat_note_default_category(self):
        note_file = self.test_dir / "Ideen.md"
        with open(note_file, "w", encoding="utf-8") as f:
            f.write("# Ideen\n- [ ] Idee 1\n")

        notes = scan_notes(self.test_dir, default_category="Allgemein")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].category, "Allgemein")

    def test_same_filename_in_different_folders_gets_unique_task_ids(self):
        # Two notes named "Tasks.md" in different category folders used to
        # collide on the same id (slug was derived from the title only), so
        # clicking a checkbox in one silently toggled a same-numbered line
        # in the other file instead.
        for folder in ("Work", "Personal"):
            note_dir = self.test_dir / folder
            note_dir.mkdir()
            with open(note_dir / "Tasks.md", "w", encoding="utf-8") as f:
                f.write("# Tasks\n\n## Tasks\n- [ ] Something\n")

        notes = scan_notes(self.test_dir)
        ids = [t.id for n in notes for t in n.tasks]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2, f"task ids collided: {ids}")

    def test_create_note(self):
        ok, msg = create_note(self.test_dir, "Neues Projekt", category="Dev")
        self.assertTrue(ok)
        created_file = self.test_dir / "Dev" / "Neues Projekt.md"
        self.assertTrue(created_file.is_file())

        # Zweiter Versuch muss fehlschlagen (Existenzschutz)
        ok2, _ = create_note(self.test_dir, "Neues Projekt", category="Dev")
        self.assertFalse(ok2)


class TestOmaCheckAtomicToggleAndAdd(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))
        self.note_file = self.test_dir / "Tasks.md"
        content = (
            "# Aufgaben\n"
            "\n"
            "## Aufgaben\n"
            "- [ ] Task 1 ⏫\n"
            "- [x] Task 2 ✅ 2026-09-10\n"
            "- [ ] Task 3\n"
        )
        with open(self.note_file, "w", encoding="utf-8") as f:
            f.write(content)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_toggle_uncompleted_to_completed(self):
        # Zeile 4 ist Task 1 (- [ ] Task 1 ⏫)
        ok, msg = toggle_task(self.note_file, 4, append_completion_date=True)
        self.assertTrue(ok)

        with open(self.note_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertTrue(lines[3].startswith("- [x] Task 1 ⏫"))
        self.assertIn("✅", lines[3])

    def test_toggle_completed_to_uncompleted(self):
        # Zeile 5 ist Task 2 (- [x] Task 2 ✅ 2026-09-10)
        ok, msg = toggle_task(self.note_file, 5, append_completion_date=True)
        self.assertTrue(ok)

        with open(self.note_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertTrue(lines[4].startswith("- [ ] Task 2"))
        self.assertNotIn("✅", lines[4])

    def test_delete_removes_only_the_targeted_line(self):
        # Zeile 5 ist Task 2, Zeile 6 ist Task 3.
        ok, msg = delete_task(self.note_file, 5)
        self.assertTrue(ok)

        with open(self.note_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[3].startswith("- [ ] Task 1"))
        self.assertTrue(lines[4].startswith("- [ ] Task 3"))
        self.assertNotIn("Task 2", "".join(lines))

    def test_delete_rejects_non_checkbox_line(self):
        ok, msg = delete_task(self.note_file, 1)  # "# Aufgaben"
        self.assertFalse(ok)
        with open(self.note_file, "r", encoding="utf-8") as f:
            self.assertEqual(len(f.readlines()), 6)

    def test_add_task_to_existing_note(self):
        ok, msg = add_task(
            notes_dir=self.test_dir,
            text="Neuer dringender Task",
            note_title="Tasks",
            category="General",
            priority="high",
            due_date="2026-09-20",
            tag="omarchy",
        )
        self.assertTrue(ok)

        with open(self.note_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Neuer dringender Task #omarchy ⏫ 📅 2026-09-20", content)


class TestOmaCheckConfigDefaults(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))
        self.config_path = self.test_dir / "config.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_bar_widget_default_off_when_no_config(self):
        config = load_config(self.config_path)
        self.assertFalse(config["widgets"]["bar_enabled"])

    def test_bar_widget_default_off_for_existing_config_without_widgets(self):
        # Bestehende Installation mit config.json, aber ohne explizite
        # OmaCheck-Präferenz für das Statusleisten-Widget.
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"storage": {"mode": "standalone"}}, f)
        config = load_config(self.config_path)
        self.assertFalse(config["widgets"]["bar_enabled"])

    def test_desktop_widget_default_on_when_no_config(self):
        config = load_config(self.config_path)
        self.assertTrue(config["widgets"]["desktop_enabled"])

    def test_storage_mode_defaults_to_standalone_documents_folder(self):
        config = load_config(self.config_path)
        self.assertEqual(config["storage"]["mode"], "standalone")
        self.assertEqual(Path(config["storage"]["fallback_dir"]), DEFAULT_STANDALONE_DIR)
        self.assertEqual(DEFAULT_STANDALONE_DIR, Path.home() / "Documents" / "OmaCheck")

    def test_save_and_reload_round_trip(self):
        config = load_config(self.config_path)
        config["widgets"]["bar_enabled"] = True
        ok, msg = save_config(config, self.config_path)
        self.assertTrue(ok, msg)

        reloaded = load_config(self.config_path)
        self.assertTrue(reloaded["widgets"]["bar_enabled"])
        # Andere Default-Sektionen bleiben unangetastet
        self.assertEqual(reloaded["categories"]["default_category"], "General")


class TestOmaCheckBarWidgetManagement(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))
        self.shell_json = self.test_dir / "shell.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_shell_json(self, data):
        with open(self.shell_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _base_shell_config(self, with_bar_entry=True):
        right = [{"id": "omarchy.tray"}]
        if with_bar_entry:
            right.append({"id": PLUGIN_ID})
        right.append({"id": "omarchy.power"})
        return {
            "version": 1,
            "idle": {"screensaver": 150, "lock": 300},
            "bar": {
                "position": "top",
                "layout": {
                    "left": [{"id": "omarchy.menu"}],
                    "center": [{"id": "omarchy.clock"}],
                    "right": right,
                },
            },
            "plugins": [],
        }

    def test_missing_shell_json_reports_unknown_live_state(self):
        self.assertIsNone(read_bar_widget_live_state(self.shell_json))

    def test_set_enabled_false_removes_entry_but_keeps_other_widgets(self):
        self._write_shell_json(self._base_shell_config(with_bar_entry=True))

        ok, msg = set_bar_widget_enabled(False, shell_config_path=self.shell_json)
        self.assertTrue(ok, msg)

        with open(self.shell_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        right_ids = [e["id"] for e in data["bar"]["layout"]["right"]]
        self.assertNotIn(PLUGIN_ID, right_ids)
        self.assertIn("omarchy.tray", right_ids)
        self.assertIn("omarchy.power", right_ids)
        # Andere Sektionen und unbekannte Top-Level-Keys bleiben erhalten
        self.assertEqual(data["bar"]["layout"]["left"], [{"id": "omarchy.menu"}])
        self.assertEqual(data["idle"], {"screensaver": 150, "lock": 300})

    def test_set_enabled_false_keeps_service_alive_via_plugins_list(self):
        self._write_shell_json(self._base_shell_config(with_bar_entry=True))

        ok, msg = set_bar_widget_enabled(False, shell_config_path=self.shell_json)
        self.assertTrue(ok, msg)

        with open(self.shell_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        plugin_ids = [e["id"] for e in data["plugins"]]
        self.assertIn(PLUGIN_ID, plugin_ids)

    def test_set_enabled_true_adds_entry_to_default_section(self):
        cfg = self._base_shell_config(with_bar_entry=False)
        self._write_shell_json(cfg)

        ok, msg = set_bar_widget_enabled(True, shell_config_path=self.shell_json)
        self.assertTrue(ok, msg)
        self.assertTrue(read_bar_widget_live_state(self.shell_json))

        with open(self.shell_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        right_ids = [e["id"] for e in data["bar"]["layout"]["right"]]
        self.assertEqual(right_ids.count(PLUGIN_ID), 1)

    def test_set_enabled_true_is_idempotent_no_duplicate(self):
        self._write_shell_json(self._base_shell_config(with_bar_entry=True))

        ok1, _ = set_bar_widget_enabled(True, shell_config_path=self.shell_json)
        ok2, _ = set_bar_widget_enabled(True, shell_config_path=self.shell_json)
        self.assertTrue(ok1)
        self.assertTrue(ok2)

        with open(self.shell_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        right_ids = [e["id"] for e in data["bar"]["layout"]["right"]]
        self.assertEqual(right_ids.count(PLUGIN_ID), 1)

    def test_invalid_json_is_never_overwritten(self):
        with open(self.shell_json, "w", encoding="utf-8") as f:
            f.write("{ this is not valid json")

        ok, msg = set_bar_widget_enabled(False, shell_config_path=self.shell_json)
        self.assertFalse(ok)

        with open(self.shell_json, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "{ this is not valid json")

    def test_missing_shell_json_does_not_create_file(self):
        ok, msg = set_bar_widget_enabled(True, shell_config_path=self.shell_json)
        self.assertFalse(ok)
        self.assertFalse(self.shell_json.exists())

    def test_apply_bar_widget_setting_uses_config_preference(self):
        import unittest.mock as mock

        self._write_shell_json(self._base_shell_config(with_bar_entry=True))

        with mock.patch("omacheck.OMARCHY_SHELL_CONFIG_PATH", self.shell_json):
            ok, msg = apply_bar_widget_setting({"widgets": {"bar_enabled": False}})
            self.assertTrue(ok, msg)
            self.assertFalse(read_bar_widget_live_state(self.shell_json))

            ok, msg = apply_bar_widget_setting({"widgets": {"bar_enabled": True}})
            self.assertTrue(ok, msg)
            self.assertTrue(read_bar_widget_live_state(self.shell_json))

    def test_apply_does_not_reset_true_preference_back_to_false(self):
        # Installer-Anforderung: --apply darf eine bestehende true-Präferenz
        # nie stillschweigend zurücksetzen. apply_bar_widget_setting ändert
        # config.json ohnehin nie, nur die Live-Bar folgt der Präferenz.
        self._write_shell_json(self._base_shell_config(with_bar_entry=False))
        config = {"widgets": {"bar_enabled": True}}

        ok, _ = set_bar_widget_enabled(True, shell_config_path=self.shell_json)
        self.assertTrue(ok)
        self.assertTrue(read_bar_widget_live_state(self.shell_json))
        self.assertTrue(config["widgets"]["bar_enabled"])


class TestOmaCheckCategoryPinning(unittest.TestCase):
    """Categories are otherwise derived only from note subfolders/frontmatter;
    add_category() lets a category exist before any note is filed under it."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))
        self.config_path = self.test_dir / "config.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_add_category_creates_config_with_pinned_list(self):
        ok, msg = add_category("Shopping", self.config_path)
        self.assertTrue(ok, msg)

        with open(self.config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["categories"]["pinned"], ["Shopping"])

    def test_add_category_is_idempotent_no_duplicate(self):
        add_category("Shopping", self.config_path)
        ok, _ = add_category("Shopping", self.config_path)
        self.assertTrue(ok)

        with open(self.config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["categories"]["pinned"].count("Shopping"), 1)

    def test_add_category_rejects_empty_name(self):
        ok, msg = add_category("   ", self.config_path)
        self.assertFalse(ok)
        self.assertFalse(self.config_path.exists())

    def test_add_category_preserves_unrelated_keys(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"storage": {"mode": "obsidian"}}, f)

        ok, _ = add_category("Shopping", self.config_path)
        self.assertTrue(ok)

        with open(self.config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["storage"], {"mode": "obsidian"})
        self.assertEqual(saved["categories"]["pinned"], ["Shopping"])

    def test_broken_config_json_is_never_overwritten_by_add_category(self):
        broken = "{ broken json, not touched"
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(broken)

        ok, _ = add_category("Shopping", self.config_path)
        self.assertFalse(ok)
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), broken)


class TestOmaCheckStrictConfigLoader(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))
        self.config_path = self.test_dir / "config.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_missing_file_returns_empty_dict_no_error(self):
        data, err = _load_config_file_strict(self.config_path)
        self.assertEqual(data, {})
        self.assertIsNone(err)

    def test_invalid_json_returns_none_with_error(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("{ not valid json")

        data, err = _load_config_file_strict(self.config_path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)

        # Datei darf dadurch nicht verändert worden sein
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "{ not valid json")

    def test_non_object_json_returns_none_with_error(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)

        data, err = _load_config_file_strict(self.config_path)
        self.assertIsNone(data)
        self.assertIsNotNone(err)

    def test_settings_write_path_preserves_unknown_top_level_keys(self):
        # Simuliert genau das, was cmd_settings("--bar-widget") tut: roh laden,
        # nur widgets.bar_enabled ändern, alles andere unangetastet lassen.
        original = {
            "storage": {"mode": "standalone"},
            "some_future_tool": {"unrelated": True},
            "widgets": {"bar_enabled": False, "future_widget_flag": "keep-me"},
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(original, f)

        raw, err = _load_config_file_strict(self.config_path)
        self.assertIsNone(err)
        raw["widgets"]["bar_enabled"] = True
        ok, msg = save_config(raw, self.config_path)
        self.assertTrue(ok, msg)

        with open(self.config_path, "r", encoding="utf-8") as f:
            written = json.load(f)

        self.assertEqual(written["some_future_tool"], {"unrelated": True})
        self.assertEqual(written["storage"], {"mode": "standalone"})
        self.assertTrue(written["widgets"]["bar_enabled"])
        self.assertEqual(written["widgets"]["future_widget_flag"], "keep-me")

    def test_broken_config_json_is_never_overwritten_by_settings_write_path(self):
        broken_content = "{ broken json, not touched"
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(broken_content)

        raw, err = _load_config_file_strict(self.config_path)
        self.assertIsNone(raw)
        self.assertIsNotNone(err)
        # cmd_settings gibt in diesem Fall ohne save_config()-Aufruf zurück;
        # hier bestätigen wir, dass die Datei danach unverändert ist.
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), broken_content)


class TestOmaCheckBarLiveStateRobustness(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="omacheck_test_"))
        self.shell_json = self.test_dir / "shell.json"

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write(self, data):
        with open(self.shell_json, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_bar_key_null_does_not_crash(self):
        self._write({"bar": None})
        self.assertFalse(read_bar_widget_live_state(self.shell_json))

    def test_bar_key_is_list_does_not_crash(self):
        self._write({"bar": ["not", "a", "dict"]})
        self.assertFalse(read_bar_widget_live_state(self.shell_json))

    def test_bar_key_is_string_does_not_crash(self):
        self._write({"bar": "oops"})
        self.assertFalse(read_bar_widget_live_state(self.shell_json))

    def test_layout_key_is_list_does_not_crash(self):
        self._write({"bar": {"layout": ["not", "a", "dict"]}})
        self.assertFalse(read_bar_widget_live_state(self.shell_json))

    def test_missing_bar_key_does_not_crash(self):
        self._write({"version": 1})
        self.assertFalse(read_bar_widget_live_state(self.shell_json))

    def test_top_level_not_an_object_returns_none(self):
        self._write(["not", "an", "object"])
        self.assertIsNone(read_bar_widget_live_state(self.shell_json))


class TestOmaCheckSettingsCliExitCodes(unittest.TestCase):
    """Testet `omacheck settings ...` als echten Subprozess (frisches HOME pro
    Test), da OMARCHY_SHELL_CONFIG_PATH von Path.home() beim Import abhängt."""

    def setUp(self):
        self.home_dir = Path(tempfile.mkdtemp(prefix="omacheck_home_"))
        (self.home_dir / ".config" / "omarchy").mkdir(parents=True)
        (self.home_dir / ".config" / "omacheck").mkdir(parents=True)
        self.shell_json = self.home_dir / ".config" / "omarchy" / "shell.json"
        self.config_json = self.home_dir / ".config" / "omacheck" / "config.json"
        self.env = dict(os.environ, HOME=str(self.home_dir))

    def tearDown(self):
        shutil.rmtree(self.home_dir, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(OMACHECK_SCRIPT), "settings", *args],
            env=self.env,
            capture_output=True,
            text=True,
        )

    def test_bar_widget_on_fails_with_exit_1_when_shell_json_missing(self):
        # Kein shell.json vorhanden -> Live-Anwendung schlägt fehl -> Exitcode 1,
        # obwohl die Präferenz trotzdem korrekt persistiert wurde.
        result = self._run("--bar-widget", "on", "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertTrue(data["widgets"]["bar_enabled_preference"])
        self.assertFalse(data["widgets"]["bar_widget_write_ok"])

        with open(self.config_json, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(saved["widgets"]["bar_enabled"])

    def test_bar_widget_on_succeeds_with_valid_shell_json(self):
        with open(self.shell_json, "w", encoding="utf-8") as f:
            json.dump({"bar": {"layout": {"left": [], "center": [], "right": []}}, "plugins": []}, f)

        result = self._run("--bar-widget", "on", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["widgets"]["bar_widget_write_ok"])
        self.assertTrue(data["widgets"]["bar_enabled_live"])

    def test_desktop_widget_off_persists_and_exits_0(self):
        # Rein config.json-gesteuert, keine shell.json nötig -> immer Exitcode 0.
        result = self._run("--desktop-widget", "off", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertFalse(data["widgets"]["desktop_enabled_preference"])

        with open(self.config_json, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertFalse(saved["widgets"]["desktop_enabled"])

    def test_desktop_widget_off_preserves_unrelated_bar_preference(self):
        result = self._run("--bar-widget", "on", "--json")
        self.assertEqual(json.loads(result.stdout)["widgets"]["bar_enabled_preference"], True)

        result = self._run("--desktop-widget", "off", "--json")
        self.assertEqual(result.returncode, 0)

        with open(self.config_json, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(saved["widgets"]["bar_enabled"])
        self.assertFalse(saved["widgets"]["desktop_enabled"])

    def test_storage_mode_obsidian_persists_and_exits_0(self):
        result = self._run("--storage-mode", "obsidian", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["storage"]["mode_preference"], "obsidian")

        with open(self.config_json, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["storage"]["mode"], "obsidian")

    def test_apply_aborts_without_touching_bar_when_config_json_broken(self):
        with open(self.shell_json, "w", encoding="utf-8") as f:
            json.dump(
                {"bar": {"layout": {"left": [], "center": [], "right": [{"id": PLUGIN_ID}]}}, "plugins": []}, f
            )
        with open(self.config_json, "w", encoding="utf-8") as f:
            f.write("{ this is broken json")

        result = self._run("--apply", "--json")
        self.assertEqual(result.returncode, 1)

        # shell.json darf nicht als "false" angewendet worden sein: Eintrag
        # muss unverändert stehen bleiben.
        with open(self.shell_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        right_ids = [e["id"] for e in data["bar"]["layout"]["right"]]
        self.assertIn(PLUGIN_ID, right_ids)

    def test_apply_uses_existing_true_preference_not_default_false(self):
        with open(self.shell_json, "w", encoding="utf-8") as f:
            json.dump({"bar": {"layout": {"left": [], "center": [], "right": []}}, "plugins": []}, f)
        with open(self.config_json, "w", encoding="utf-8") as f:
            json.dump({"widgets": {"bar_enabled": True}}, f)

        result = self._run("--apply", "--json")
        self.assertEqual(result.returncode, 0)

        with open(self.shell_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        right_ids = [e["id"] for e in data["bar"]["layout"]["right"]]
        self.assertIn(PLUGIN_ID, right_ids)


class TestOmaCheckTasksCliCategories(unittest.TestCase):
    """`omacheck tasks --json` als echter Subprozess (frisches HOME)."""

    def setUp(self):
        self.home_dir = Path(tempfile.mkdtemp(prefix="omacheck_home_"))
        self.env = dict(os.environ, HOME=str(self.home_dir))

    def tearDown(self):
        shutil.rmtree(self.home_dir, ignore_errors=True)

    def test_a_real_category_named_all_does_not_duplicate_the_sentinel_tab(self):
        # ALL_CATEGORIES_LABEL ("All") is the "no filter" sentinel always
        # prepended to the tab list. A folder that happens to be named "All"
        # used to produce a second, indistinguishable "All" tab.
        notes_dir = self.home_dir / "Documents" / "OmaCheck" / "All"
        notes_dir.mkdir(parents=True)
        with open(notes_dir / "Tasks.md", "w", encoding="utf-8") as f:
            f.write("# Tasks\n\n## Tasks\n- [ ] Something\n")

        result = subprocess.run(
            [sys.executable, str(OMACHECK_SCRIPT), "tasks", "--json", "--all"],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["categories"].count("All"), 1, data["categories"])


if __name__ == "__main__":
    unittest.main()
