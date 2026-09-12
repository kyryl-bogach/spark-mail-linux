import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "local.spark-mail"
  ipcTarget: moduleName
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  property var emails: []
  property string status: "Read the inbox..."
  readonly property string helper: decodeURIComponent(Qt.resolvedUrl("helper.py").toString().replace(/^file:\/\//, ""))

  function refresh() {
    if (!fetch.running) fetch.running = true
  }
  function open() {
    controller.show()
    refresh()
  }
  function openSpark() {
    if (!launch.running) launch.running = true
    close()
  }

  Process {
    id: fetch
    command: ["python3", root.helper, "list"]
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          root.emails = result.emails
          root.status = result.status
        } catch (error) {
          root.emails = []
          root.status = "Cannot read the Spark inbox"
        }
      }
    }
  }
  Process {
    id: launch
    command: ["python3", root.helper, "open"]
    onExited: function(code) {
      if (code !== 0) { root.status = "Cannot open Spark"; root.controller.show() }
    }
  }
  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰇮"
    tooltipText: "Spark inbox"
    onPressed: function(b) {
      if (b === Qt.MiddleButton) root.openSpark()
      else root.toggle()
    }
  }
  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keys
    contentWidth: popup.fittedContentWidth(Style.space(520))
    contentHeight: popup.fittedContentHeight(Math.min(Style.space(600), content.implicitHeight))

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onReturnRequested: root.openSpark()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Column {
          id: content
          width: parent.width
          spacing: Style.space(8)
          Item {
            width: parent.width
            height: Style.space(36)
            Text {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              text: "Inbox"
              color: root.barForeground
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Rectangle {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              width: openLabel.implicitWidth + Style.space(20)
              height: Style.space(32)
              radius: Style.cornerRadius
              color: openHover.containsMouse ? Style.hoverFillFor(root.barForeground, Color.accent) : "transparent"
              Text {
                id: openLabel
                anchors.centerIn: parent
                text: "Open Spark ↗"
                color: Color.accent
                font.pixelSize: Style.font.bodySmall
              }
              MouseArea {
                id: openHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openSpark()
              }
            }
          }
          Rectangle {
            width: parent.width
            height: Style.spacing.hairline
            color: root.barForeground
            opacity: 0.12
          }
          Text {
            visible: root.emails.length === 0 || root.status !== "Inbox"
            width: parent.width
            text: fetch.running ? "Read the inbox..." : root.status
            textFormat: Text.PlainText
            color: root.barForeground
            font.pixelSize: Style.font.body
            wrapMode: Text.Wrap
            padding: Style.space(8)
            opacity: 0.7
          }
          Repeater {
            model: root.emails
            Rectangle {
              required property var modelData
              width: content.width
              height: row.implicitHeight + Style.space(20)
              radius: Style.cornerRadius
              color: hover.containsMouse ? Style.hoverFillFor(root.barForeground, Color.accent) : "transparent"
              Column {
                id: row
                anchors.centerIn: parent
                width: parent.width - Style.space(16)
                spacing: Style.space(4)
                Item {
                  width: parent.width
                  height: senderLabel.implicitHeight
                  Text {
                    id: senderLabel
                    anchors.left: parent.left
                    anchors.right: dateLabel.left
                    anchors.rightMargin: Style.space(16)
                    text: modelData.sender.replace(/\s*<.*$/, "").replace(/^"|"$/g, "")
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: root.barForeground
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  Text {
                    id: dateLabel
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.date
                    textFormat: Text.PlainText
                    color: root.barForeground
                    font.pixelSize: Style.font.bodySmall
                    opacity: 0.55
                  }
                }
                Text {
                  width: parent.width
                  text: modelData.subject || "(No subject)"
                  textFormat: Text.PlainText
                  elide: Text.ElideRight
                  color: root.barForeground
                  font.pixelSize: Style.font.body
                }
              }
              MouseArea {
                id: hover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.openSpark()
              }
            }
          }

        }
      }
    }
  }
}
