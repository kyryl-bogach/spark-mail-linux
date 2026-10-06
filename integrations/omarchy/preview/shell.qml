import QtQuick
import Quickshell
import qs.Commons
import "plugin" as Plugin
import "notifications/components" as Notifications

ShellRoot {
  property int captures: 0
  readonly property string mockHelper: decodeURIComponent(Qt.resolvedUrl("mock_helper.py").toString().replace(/^file:\/\//, ""))

  function capture(item, name) {
    var accepted = item.grabToImage(function(result) {
      if (!result.saveToFile(Quickshell.env("SPARK_PREVIEW_OUT_DIR") + "/" + name)) {
        console.log("CAPTURE_FAILED=" + name)
        Qt.quit()
        return
      }
      captures++
      if (captures === 3) Qt.quit()
    }, Qt.size(Math.round(item.width * 2), Math.round(item.height * 2)))
    if (!accepted) { console.log("CAPTURE_FAILED=" + name); Qt.quit() }
  }

  PanelWindow {
    visible: true
    anchors.top: true
    anchors.left: true
    anchors.right: true
    screen: Quickshell.screens[0]
    implicitHeight: Style.bar.sizeHorizontal
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    Plugin.BarWidget {
      id: popupWidget
      anchors.right: parent.right
      anchors.rightMargin: Style.space(30)
      anchors.verticalCenter: parent.verticalCenter
      helper: mockHelper
    }
  }

  FloatingWindow {
    visible: true
    implicitWidth: Style.space(520)
    implicitHeight: Style.space(440)
    color: Color.background
    Item {
      anchors.centerIn: parent
      width: Style.space(480)
      height: states.height + Style.space(28) + reminders.height
      Column {
        id: states
        width: parent.width
        height: Style.space(120)
        Rectangle {
          width: parent.width
          height: parent.height
          color: Color.bar.background
          Row {
            anchors.centerIn: parent
            spacing: 0
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: empty; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Empty"; color: Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: pending; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Pending mail"; color: Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: meeting; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Meeting soon"; color: Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: both; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Both"; color: Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
          }
        }
      }
      Column {
        id: reminders
        anchors.top: states.bottom
        anchors.topMargin: Style.space(28)
        width: parent.width
        spacing: Style.space(12)
        Notifications.NotificationCard {
          width: parent.width
          app: "Spark Calendar"
          glyph: "󰃭"
          summary: "Meeting in 5 minutes"
          body: "Event: Design review"
          timestamp: Date.now()
          urgency: 1
          fontFamily: Style.font.family
          cornerRadius: Style.cornerRadius
        }
        Notifications.NotificationCard {
          width: parent.width
          app: "Spark Calendar"
          glyph: "󰃭"
          summary: "Meeting in 1 minute"
          body: "Event: Design review"
          timestamp: Date.now()
          urgency: 1
          fontFamily: Style.font.family
          cornerRadius: Style.cornerRadius
        }
      }
    }
  }

  Timer {
    id: ready
    interval: 100
    running: true
    repeat: true
    onTriggered: {
      if ([popupWidget, empty, pending, meeting, both].some(function(widget) {
        return widget.status !== "Inbox" || widget.emails.length !== 3 || widget.events.length !== 3
      })) return
      stop()
      popupWidget.controller.show()
      empty.emails = []; empty.status = "Inbox is empty"; empty.eventStartsMs = []
      pending.eventStartsMs = []
      meeting.emails = []; meeting.status = "Inbox is empty"; meeting.eventStartsMs = [Date.now() + 5 * 60000]
      both.eventStartsMs = [Date.now() + 5 * 60000]
      settle.start()
    }
  }
  Timer {
    id: settle
    interval: 300
    onTriggered: {
      capture(popupWidget.previewPopup.previewCard, "omarchy-plugin.png")
      capture(states, "omarchy-plugin-indicators.png")
      capture(reminders, "omarchy-plugin-reminders.png")
    }
  }
  Timer { interval: 10000; running: true; onTriggered: { console.log("CAPTURE_FAILED=timeout"); Qt.quit() } }
}
