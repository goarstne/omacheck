"""Quickshell/QtTest smoke check with isolated notes and an injected write failure.

Run: python3 tests/check_ui.py (requires Quickshell and QtTest).
"""
import os
from pathlib import Path
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix="omacheck-ui-") as directory:
    root = Path(directory)
    home = root / "home"
    notes = home / "Documents" / "OmaCheck"
    notes.mkdir(parents=True)
    (notes / "Test.md").write_text("- [ ] Test task\n- [x] Done\n")
    binary = home / ".local/bin/omacheck"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\nimport os, sys\n"
        "if sys.argv[1:3] == ['add', 'Do not lose this']:\n"
        "    sys.exit('Test: write access denied')\n"
        f"os.execv(sys.executable, [sys.executable, {str(PROJECT / 'omacheck.py')!r}, *sys.argv[1:]])\n"
    )
    binary.chmod(0o755)
    shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
    for module in ("Commons", "Ui"):
        (root / module).symlink_to(shell / module, target_is_directory=True)
    source = (PROJECT / "plugin/DesktopWidgetView.qml").read_text()
    source = source.replace("import QtQuick\n", "import QtQuick\nimport QtTest\n", 1)
    source = source.replace('id: taskCheck\n', 'id: taskCheck\n            objectName: "task-" + modelData.text\n')
    source = source.replace('id: deleteBtn\n', 'id: deleteBtn\n              objectName: "delete-" + taskRow.modelData.text\n')
    source = source.replace('id: catRemove\n', 'id: catRemove\n                objectName: "catdelete-" + catRow.modelData\n')
    checks = '''
    TestCase {
      name: "Desktop"; when: true
      function findByName(item, name) {
        if (item.objectName === name) return item
        for (var i = 0; i < item.children.length; i++) {
          var found = findByName(item.children[i], name); if (found) return found
        }
        return null
      }
      function findTask(item) { return findByName(item, "task-Test task") }
      function test_interaction() {
        tryVerify(function() { return root.tasksList.length === 2 && !root.loading }, 3000)
        var task = findTask(root)
        verify(task !== null); verify(!task.checked)
        mouseClick(task, task.indicator.x + 8, task.indicator.y + 8)
        tryVerify(function() { return root.tasksList[0].completed && !root.loading }, 3000)
        task = findTask(root); task.forceActiveFocus(); keyClick(Qt.Key_Space)
        tryVerify(function() { return !root.tasksList[0].completed && !root.loading }, 3000)
        taskInputField.text = "Do not lose this"; taskInputField.accepted()
        tryVerify(function() { return root.errorText.length > 0 }, 3000)
        compare(taskInputField.text, "Do not lose this")
        taskInputField.text = "New task"; taskInputField.accepted()
        tryVerify(function() { return root.tasksList.length === 3 && !root.loading }, 3000)
        compare(taskInputField.text, ""); compare(root.errorText, "")

        var deleteBtn = findByName(root, "delete-New task")
        verify(deleteBtn !== null)
        deleteBtn.forceActiveFocus()
        keyClick(Qt.Key_Space)
        tryVerify(function() { return root.tasksList.length === 2 && !root.loading }, 3000)
        verify(findByName(root, "task-New task") === null)

        newCategoryField.text = "Temp"; newCategoryField.accepted()
        tryVerify(function() { return root.categoriesList.indexOf("Temp") !== -1 && !root.loading }, 3000)
        var catDelete = findByName(root, "catdelete-Temp")
        verify(catDelete !== null)
        catDelete.forceActiveFocus()
        keyClick(Qt.Key_Space)
        tryVerify(function() { return root.categoriesList.indexOf("Temp") === -1 && !root.loading }, 3000)

        console.log("DESKTOP_UI_OK"); finishTimer.start()
      }
    }
    Timer { id: finishTimer; interval: 100; onTriggered: Qt.quit() }
    '''
    source = source[:source.rfind("}")] + checks + "}\n"
    (root / "DesktopWidgetView.qml").write_text(source)
    (root / "shell.qml").write_text(
        "import QtQuick\nimport Quickshell\nFloatingWindow {\n"
        "implicitWidth: 320; implicitHeight: 400\n"
        "DesktopWidgetView { anchors.fill: parent }\n}\n"
    )
    env = dict(os.environ, HOME=str(home), QT_QPA_PLATFORM="offscreen",
               QT_QUICK_BACKEND="software", PYTHONDONTWRITEBYTECODE="1")
    env.pop("WAYLAND_DISPLAY", None)
    result = subprocess.run(["quickshell", "-p", str(root), "--no-color"],
                            env=env, capture_output=True, text=True, timeout=20)
    output = result.stdout + result.stderr
    assert result.returncode == 0 and "DESKTOP_UI_OK" in output, output
    print("Desktop UI: mouse, keyboard, add and write failure passed.")
