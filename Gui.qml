pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui

FloatingWindow {
  id: root
  objectName: "omacheckWindow"
  title: "OmaCheck"
  color: Color.background
  implicitWidth: 1000
  implicitHeight: 850
  minimumSize: Qt.size(680, 580)

  readonly property var typography: Style.font
  readonly property string binPath: Quickshell.env("OMACHECK_BACKEND") || (Quickshell.env("HOME") + "/.local/bin/omacheck")

  property var rawData: ({})
  property var allNotes: []
  property var allTasks: []
  property var categories: ["Alle"]
  property string selectedCategory: "Alle"
  property var selectedNote: null
  property string searchQuery: ""
  property bool showCompleted: true
  property bool loading: false

  function refresh() {
    if (fetchProc.running) return
    loading = true
    fetchProc.command = [binPath, "tasks", "--json", "--all"]
    fetchProc.running = true
  }

  function toggleTask(taskId) {
    if (toggleProc.running) return
    toggleProc.command = [binPath, "toggle", taskId]
    toggleProc.running = true
  }

  function addTask(text, priority) {
    if (!text || text.trim() === "" || addProc.running) return
    var args = [binPath, "add", text.trim()]
    if (selectedNote && selectedNote.title) {
      args.push("-n")
      args.push(selectedNote.title)
    }
    if (selectedCategory !== "Alle") {
      args.push("-c")
      args.push(selectedCategory)
    }
    if (priority && priority !== "normal") {
      args.push("-p")
      args.push(priority)
    }
    addProc.command = args
    addProc.running = true
  }

  function createNewNote(title, category) {
    if (!title || title.trim() === "" || createNoteProc.running) return
    var cat = (category && category !== "Alle") ? category : (selectedCategory !== "Alle" ? selectedCategory : "Allgemein")
    createNoteProc.command = [binPath, "create-note", title.trim(), "-c", cat]
    createNoteProc.running = true
  }

  function openInObsidian() {
    openObsidianProc.command = ["xdg-open", "obsidian://open"]
    openObsidianProc.running = true
  }

  function openFile(filePath) {
    if (!filePath) return
    openEditorProc.command = ["xdg-open", filePath]
    openEditorProc.running = true
  }

  function filteredNotes() {
    var list = allNotes
    if (selectedCategory !== "Alle") {
      list = list.filter(n => n.category === selectedCategory)
    }
    if (searchQuery.trim() !== "") {
      var q = searchQuery.toLowerCase().trim()
      list = list.filter(n => n.title.toLowerCase().includes(q) || n.tasks.some(t => t.text.toLowerCase().includes(q)))
    }
    return list
  }

  function filteredTasks() {
    var list = []
    if (selectedNote && selectedNote.tasks) {
      list = selectedNote.tasks
    } else {
      list = (selectedCategory === "Alle") ? allTasks : allTasks.filter(t => t.category === selectedCategory)
    }
    if (!showCompleted) {
      list = list.filter(t => !t.completed)
    }
    if (searchQuery.trim() !== "") {
      var q = searchQuery.toLowerCase().trim()
      list = list.filter(t => t.text.toLowerCase().includes(q) || t.note_title.toLowerCase().includes(q))
    }
    return list
  }

  Component.onCompleted: refresh()

  // Theme-Dateien live überwachen wie in Omasync
  FileView {
    id: themeColors
    property string previous: ""
    path: Color.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: { const raw = text(); if (raw !== previous) { previous = raw; Color.loadColors(raw) } }
  }
  FileView {
    id: themeStyle
    property string previous: ""
    path: Color.currentThemePath + "/shell.toml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: { const raw = text(); if (raw !== previous) { previous = raw; Color.loadShell(raw); Style.scheduleRefresh() } }
  }

  // Prozesse
  Process {
    id: fetchProc
    stdout: StdioCollector { id: fetchStdout }
    stderr: StdioCollector { id: fetchStderr }
    onExited: function(code) {
      root.loading = false
      if (code === 0) {
        var raw = String(fetchStdout.text || "").trim()
        if (raw.length > 0) {
          try {
            var data = JSON.parse(raw)
            root.rawData = data
            root.allNotes = data.notes || []
            root.allTasks = data.tasks || []
            root.categories = data.categories || ["Alle"]
            if (root.allNotes.length > 0) {
              if (!root.selectedNote) {
                root.selectedNote = root.allNotes[0]
              } else {
                var found = root.allNotes.find(n => n.file_path === root.selectedNote.file_path)
                root.selectedNote = found || root.allNotes[0]
              }
            } else {
              root.selectedNote = null
            }
          } catch (e) {
            console.warn("Gui JSON parse error:", e)
          }
        }
      }
    }
  }

  Process { id: toggleProc; onExited: function(c) { root.refresh() } }
  Process {
    id: addProc
    onExited: function(c) {
      taskInputField.text = ""
      root.refresh()
    }
  }
  Process {
    id: createNoteProc
    onExited: function(c) {
      newNoteInput.text = ""
      noteDialog.visible = false
      root.refresh()
    }
  }
  Process { id: openObsidianProc }
  Process { id: openEditorProc }

  // Komponenten im exakten Omasync-Stil
  component Caption: Text {
    textFormat: Text.PlainText
    color: Color.foreground
    font.family: root.typography.family
    font.pixelSize: root.typography.body
    wrapMode: Text.WordWrap
  }
  component Action: Ui.Button {
    focusable: true
    bordered: true
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: clicked()
  }
  component Choice: Ui.Toggle {
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.checkable: true
    Accessible.checked: checked
    Accessible.onToggleAction: clicked()
    opacity: enabled ? 1 : 0.45
  }

  FocusScope {
    anchors.fill: parent
    focus: true
    Rectangle { anchors.fill: parent; color: Color.background }

    Controls.ScrollView {
      id: page
      anchors.fill: parent
      clip: true
      contentWidth: availableWidth
      contentHeight: mainColumn.height + Style.space(48)
      Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

      ColumnLayout {
        id: mainColumn
        x: Style.space(24)
        y: Style.space(24)
        width: page.availableWidth - Style.space(48)
        height: implicitHeight
        spacing: Style.space(16)

        // 1. Kopfbereich (Omasync Titel-Layout)
        RowLayout {
          Layout.fillWidth: true
          ColumnLayout {
            Layout.fillWidth: true
            spacing: Style.space(2)
            Caption {
              text: "OmaCheck"
              font.pixelSize: root.typography.displayLarge
              font.bold: true
            }
            Caption {
              text: "Universelle Notizen & Aufgaben · " + (root.rawData.mode ? "Modus: " + root.rawData.mode : "Laden...")
              opacity: 0.7
            }
          }
          Action {
            text: "⟳ Aktualisieren"
            onClicked: root.refresh()
          }
          Action {
            text: "In Obsidian öffnen ↗"
            onClicked: root.openInObsidian()
          }
          Action {
            text: "+ Neue Notiz"
            selected: noteDialog.visible
            onClicked: noteDialog.visible = !noteDialog.visible
          }
        }

        // Dialog für neue Notiz (im Omasync Inline-Stil)
        Rectangle {
          id: noteDialog
          visible: false
          Layout.fillWidth: true
          implicitHeight: noteDialogRow.implicitHeight + Style.space(16)
          radius: Style.cornerRadius > 0 ? Style.cornerRadius : Style.space(8)
          color: Qt.rgba(Color.foreground.r, Color.foreground.g, Color.foreground.b, 0.05)
          border.width: Style.normalBorderWidth > 0 ? Style.normalBorderWidth : 1
          border.color: Style.normalBorderColor

          RowLayout {
            id: noteDialogRow
            anchors.fill: parent
            anchors.margins: Style.space(12)
            spacing: Style.space(10)

            Caption { text: "Neue Notiz in '" + (root.selectedCategory === "Alle" ? "Allgemein" : root.selectedCategory) + "':"; font.bold: true }

            Ui.TextField {
              id: newNoteInput
              Layout.fillWidth: true
              placeholderText: "Titel der Notiz..."
              onAccepted: root.createNewNote(newNoteInput.text, root.selectedCategory)
            }

            Action {
              text: "Erstellen"
              onClicked: root.createNewNote(newNoteInput.text, root.selectedCategory)
            }
            Action {
              text: "Abbrechen"
              onClicked: noteDialog.visible = false
            }
          }
        }

        // 2. Kategorien-Tabs (wie Export/Import Tabs in Omasync)
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Caption {
            text: "Kategorien:"
            font.bold: true
            Layout.alignment: Qt.AlignVCenter
          }

          Controls.ScrollView {
            Layout.fillWidth: true
            implicitHeight: Style.space(38)
            contentHeight: catButtonsRow.height
            contentWidth: catButtonsRow.width
            clip: true
            Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

            Row {
              id: catButtonsRow
              spacing: Style.space(6)

              Repeater {
                model: root.categories
                delegate: Action {
                  required property string modelData
                  text: modelData
                  selected: root.selectedCategory === modelData
                  onClicked: {
                    root.selectedCategory = modelData
                    root.selectedNote = null
                    root.refresh()
                  }
                }
              }
            }
          }
        }

        // 3. Such- und Schnelleingabeleiste (Omasync Formular-Grid)
        GridLayout {
          Layout.fillWidth: true
          columns: root.width > 780 ? 2 : 1
          columnSpacing: Style.space(18)
          rowSpacing: Style.space(10)

          ColumnLayout {
            Layout.fillWidth: true
            Caption { text: "Suche" }
            Ui.TextField {
              id: searchField
              Layout.fillWidth: true
              placeholderText: "Notizen & Aufgaben filtern..."
              Accessible.name: "Suche"
              onTextChanged: root.searchQuery = text
            }
          }

          ColumnLayout {
            Layout.fillWidth: true
            Caption { text: "Schnell-Eingabe für " + (root.selectedNote ? "'" + root.selectedNote.title + "'" : "'" + root.selectedCategory + "'") }
            RowLayout {
              Layout.fillWidth: true
              spacing: Style.space(6)
              Ui.TextField {
                id: taskInputField
                Layout.fillWidth: true
                placeholderText: "Neue Aufgabe eingeben..."
                Accessible.name: "Aufgabe eingeben"
                onAccepted: root.addTask(taskInputField.text)
              }
              Action {
                text: "+ Hinzufügen"
                onClicked: root.addTask(taskInputField.text)
              }
            }
          }
        }

        // 4. Hauptbereich: 2-Spalten Layout
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(18)

          // Spalte A: Notizen (Breite 300px)
          ColumnLayout {
            Layout.preferredWidth: Style.space(300)
            Layout.alignment: Qt.AlignTop
            spacing: Style.space(8)

            RowLayout {
              Layout.fillWidth: true
              Caption {
                text: "Notizen (" + root.filteredNotes().length + ")"
                font.bold: true
                Layout.fillWidth: true
              }
              Action {
                text: "Alle zeigen"
                selected: root.selectedNote === null
                onClicked: root.selectedNote = null
              }
            }

            Controls.ScrollView {
              id: noteScroll
              Layout.fillWidth: true
              Layout.preferredHeight: Style.space(480)
              clip: true
              contentWidth: availableWidth
              Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

              Column {
                width: noteScroll.availableWidth
                spacing: Style.space(4)

                Repeater {
                  model: root.filteredNotes()
                  delegate: Action {
                    id: noteBtn
                    required property var modelData
                    width: parent.width
                    text: noteBtn.modelData.title + " (" + noteBtn.modelData.tasks.filter(t => !t.completed).length + " offen)"
                    selected: root.selectedNote && root.selectedNote.file_path === noteBtn.modelData.file_path
                    onClicked: root.selectedNote = noteBtn.modelData
                  }
                }

                Caption {
                  visible: root.filteredNotes().length === 0
                  text: "Keine Notizen gefunden."
                  opacity: 0.5
                  y: Style.space(16)
                }
              }
            }
          }

          // Spalte B: Aufgaben & Checkboxen (Omasync Choice Liste)
          ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignTop
            spacing: Style.space(8)

            RowLayout {
              Layout.fillWidth: true
              Caption {
                text: (root.selectedNote ? root.selectedNote.title + " · " : "") + root.filteredTasks().filter(t => !t.completed).length + " von " + root.filteredTasks().length + " Aufgaben offen"
                font.bold: true
                Layout.fillWidth: true
              }
              Action {
                text: root.showCompleted ? "Erledigte verbergen" : "Erledigte anzeigen"
                onClicked: root.showCompleted = !root.showCompleted
              }
              Action {
                visible: root.selectedNote !== null
                text: "Datei öffnen ↗"
                onClicked: if (root.selectedNote) root.openFile(root.selectedNote.file_path)
              }
            }

            Controls.ScrollView {
              id: taskListScroll
              Layout.fillWidth: true
              Layout.preferredHeight: Style.space(480)
              clip: true
              contentWidth: availableWidth
              Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

              Column {
                width: taskListScroll.availableWidth
                spacing: Style.space(4)

                Repeater {
                  model: root.filteredTasks()
                  delegate: Choice {
                    id: taskToggle
                    required property var modelData
                    width: parent.width
                    label: taskToggle.modelData.text
                    description: {
                      var parts = []
                      if (taskToggle.modelData.priority) parts.push("Priorität: " + taskToggle.modelData.priority)
                      if (taskToggle.modelData.due_date) parts.push("📅 " + taskToggle.modelData.due_date)
                      if (taskToggle.modelData.note_title) parts.push("📁 " + taskToggle.modelData.category + "/" + taskToggle.modelData.note_title)
                      if (taskToggle.modelData.tags && taskToggle.modelData.tags.length > 0) parts.push("#" + taskToggle.modelData.tags.join(" #"))
                      return parts.join(" · ")
                    }
                    checked: taskToggle.modelData.completed
                    onClicked: root.toggleTask(taskToggle.modelData.id)
                  }
                }

                Caption {
                  visible: root.filteredTasks().length === 0
                  text: "Keine Aufgaben vorhanden."
                  opacity: 0.5
                  y: Style.space(20)
                }
              }
            }
          }
        }
      }
    }
  }
}
