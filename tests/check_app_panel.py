"""Quickshell/QtTest smoke check for the app panel's open/close lifecycle.

Verifies the fix for the "closing the app makes it unreachable" bug: a
host-initiated close() must not call shell.hide() again (no feedback loop),
while a user-initiated close (window X button -> visible=false) must call
shell.hide() so the shell's summon/hide/toggle bookkeeping stays in sync.

Run: python3 tests/check_app_panel.py (requires Quickshell and QtTest).
"""
import os
from pathlib import Path
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory(prefix="omacheck-panel-") as directory:
    root = Path(directory)
    home = root / "home"
    notes = home / "Documents" / "OmaCheck"
    notes.mkdir(parents=True)
    binary = home / ".local/bin/omacheck"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        "#!/usr/bin/env python3\nimport os, sys\n"
        f"os.execv(sys.executable, [sys.executable, {str(PROJECT / 'omacheck.py')!r}, *sys.argv[1:]])\n"
    )
    binary.chmod(0o755)
    shell = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")) / "shell"
    for module in ("Commons", "Ui"):
        (root / module).symlink_to(shell / module, target_is_directory=True)

    source_path = PROJECT / "AppPanel.qml" if (PROJECT / "AppPanel.qml").exists() else PROJECT / "plugin/AppPanel.qml"
    source = source_path.read_text()
    source = source.replace("import QtQuick\n", "import QtQuick\nimport QtTest\n", 1)
    checks = '''
    QtObject {
      id: fakeShell
      property int hideCallCount: 0
      property string lastHideId: ""
      function hide(id) { hideCallCount++; lastHideId = id }
    }

    TestCase {
      name: "AppPanelLifecycle"; when: true
      function test_lifecycle() {
        compare(window.visible, false)

        root.open("{}")
        compare(window.visible, true)

        root.shell = fakeShell
        // User-initiated close (window X button): must tell the host.
        window.visible = false
        compare(fakeShell.hideCallCount, 1)
        compare(fakeShell.lastHideId, "carsten.omacheck")

        // Host-initiated re-open, then host-initiated close: must NOT
        // call shell.hide() again (that would be a feedback loop).
        root.open("{}")
        compare(window.visible, true)
        root.close()
        compare(window.visible, false)
        compare(fakeShell.hideCallCount, 1)

        console.log("APP_PANEL_LIFECYCLE_OK"); finishTimer.start()
      }
    }
    Timer { id: finishTimer; interval: 100; onTriggered: Qt.quit() }
    '''
    source = source[:source.rfind("}")] + checks + "}\n"
    (root / "AppPanel.qml").write_text(source)
    (root / "shell.qml").write_text(
        "import QtQuick\nimport Quickshell\nFloatingWindow {\n"
        "implicitWidth: 320; implicitHeight: 200\n"
        "AppPanel { anchors.fill: parent }\n}\n"
    )
    env = dict(os.environ, HOME=str(home), QT_QPA_PLATFORM="offscreen",
               QT_QUICK_BACKEND="software", PYTHONDONTWRITEBYTECODE="1")
    env.pop("WAYLAND_DISPLAY", None)
    result = subprocess.run(["quickshell", "-p", str(root), "--no-color"],
                            env=env, capture_output=True, text=True, timeout=20)
    output = result.stdout + result.stderr
    assert result.returncode == 0 and "APP_PANEL_LIFECYCLE_OK" in output, output
    print("App panel: open/close lifecycle and shell.hide() sync passed.")
