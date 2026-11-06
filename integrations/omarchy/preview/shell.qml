import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import "plugin" as Plugin

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
      if (captures === 2) Qt.quit()
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
    implicitHeight: Style.space(160)
    color: Commons.Color.background
    Item {
      anchors.centerIn: parent
      width: Style.space(480)
      height: states.height
      Column {
        id: states
        width: parent.width
        height: Style.space(120)
        Rectangle {
          width: parent.width
          height: parent.height
          color: Commons.Color.bar.background
          Row {
            anchors.centerIn: parent
            spacing: 0
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: empty; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Empty"; color: Commons.Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: pending; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Pending mail"; color: Commons.Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: meeting; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Meeting soon"; color: Commons.Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
            Item {
              width: states.width / 4; height: Style.space(80)
              Plugin.BarWidget { id: both; helper: mockHelper; anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(16) }
              Text { anchors.horizontalCenter: parent.horizontalCenter; y: Style.space(56); text: "Both"; color: Commons.Color.foreground; font.pixelSize: Style.font.bodySmall }
            }
          }
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
      if (!popupWidget.previewUpdateAction.visible || !popupWidget.previewUpdateAction.enabled) {
        console.log("CAPTURE_FAILED=update-visibility")
        Qt.quit()
        return
      }
      capture(popupWidget.previewPopup.previewCard, "omarchy-plugin.png")
      capture(states, "omarchy-plugin-indicators.png")
    }
  }
  Timer { interval: 10000; running: true; onTriggered: { console.log("CAPTURE_FAILED=timeout"); Qt.quit() } }
}
