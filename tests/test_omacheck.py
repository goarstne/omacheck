"""Unittests für OmaCheck Core Engine."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from omacheck import (
    add_task,
    create_note,
    detect_obsidian_vault,
    extract_frontmatter_category,
    parse_task_line,
    resolve_notes_directory,
    scan_notes,
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

    def test_add_task_to_existing_note(self):
        ok, msg = add_task(
            notes_dir=self.test_dir,
            text="Neuer dringender Task",
            note_title="Tasks",
            category="Allgemein",
            priority="high",
            due_date="2026-09-20",
            tag="omarchy",
        )
        self.assertTrue(ok)

        with open(self.note_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Neuer dringender Task #omarchy ⏫ 📅 2026-09-20", content)


if __name__ == "__main__":
    unittest.main()
