import QtQuick
import QtQuick.Controls as Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "local.spark-mail"
  manageIpc: false
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  property var emails: []
  property string status: "Read the inbox..."
  property var events: []
  property string eventsLabel: "Today"
  property string eventsStatus: "Read the calendar..."
  property var eventStartsMs: []
  property double clockMs: Date.now()
  property string reminderStatus: ""
  property bool remindersOk: true
  readonly property bool calendarRemindersEnabled: setting("calendarReminders", true) !== false
  readonly property bool hasPendingMail: emails.length > 0
  readonly property double nextMeetingMs: {
    var next = 0
    var limit = clockMs + 15 * 60000
    for (var i = 0; i < eventStartsMs.length; i++) {
      var start = eventStartsMs[i]
      if (typeof start === "number" && start >= clockMs && start <= limit && (next === 0 || start < next)) next = start
    }
    return next
  }
  readonly property bool meetingSoon: nextMeetingMs > 0
  readonly property string iconTooltip: {
    var text = hasPendingMail ? "Spark · Pending email in inbox" : "Spark · " + status
    if (meetingSoon) text += " · Meeting in " + Math.ceil((nextMeetingMs - clockMs) / 60000) + " min"
    if (reminderStatus) text += " · " + reminderStatus
    return text
  }
  readonly property color contentForeground: Color.popups.text
  property string helper: decodeURIComponent(Qt.resolvedUrl("helper.py").toString().replace(/^file:\/\//, ""))

  function refresh() {
    if (fetch.running) return
    fetch.command = ["python3", root.helper, "list", root.calendarRemindersEnabled ? "--reminders" : "--no-reminders"]
    fetch.running = true
  }
  function open() {
    controller.show()
    refresh()
  }
  function openSpark() {
    if (!launch.running) launch.running = true
    close()
  }
  function openMessage(id) {
    if (openEmail.running) return
    openEmail.command = ["python3", root.helper, "open-email", id]
    openEmail.running = true
    close()
  }
  function openCalendar() {
    if (!calendar.running) calendar.running = true
    close()
  }

  Process {
    id: fetch
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          root.emails = result.emails
          root.status = result.status
          root.events = result.events || []
          root.eventsLabel = result.events_label || "Today"
          root.eventsStatus = result.events_status || "Cannot read the Spark calendar"
          root.eventStartsMs = result.event_starts_ms || []
          root.clockMs = Date.now()
          root.reminderStatus = result.reminder_status || ""
          root.remindersOk = result.reminders_ok !== false
        } catch (error) {
          root.emails = []
          root.status = "Cannot read the Spark inbox"
          root.events = []
          root.eventsStatus = "Cannot read the Spark calendar"
          root.eventStartsMs = []
          root.reminderStatus = "Calendar reminders are unavailable"
          root.remindersOk = false
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
  Process {
    id: openEmail
    onExited: function(code) {
      if (code !== 0) { root.status = "Cannot open the email"; root.controller.show() }
    }
  }
  Process {
    id: calendar
    command: ["python3", root.helper, "open-calendar"]
    onExited: function(code) {
      if (code !== 0) { root.status = "Cannot open the Spark calendar"; root.controller.show() }
    }
  }
  Timer {
    interval: 60000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
  Timer {
    interval: 15000
    running: true
    repeat: true
    onTriggered: root.clockMs = Date.now()
  }
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰇮"
    active: root.hasPendingMail
    activeColor: Color.accent
    tooltipText: root.iconTooltip
    onPressed: function(b) {
      if (b === Qt.MiddleButton) root.openSpark()
      else root.toggle()
    }
    Rectangle {
      visible: root.meetingSoon
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.rightMargin: Style.space(1)
      anchors.topMargin: Style.space(1)
      width: Style.space(11)
      height: width
      radius: width / 2
      color: Color.bar.background
      Text {
        anchors.centerIn: parent
        text: "󰃭"
        textFormat: Text.PlainText
        color: Color.urgent
        font.family: Style.font.family
        font.pixelSize: Style.font.iconSmall
      }
    }
  }
  component EntryCard: Rectangle {
    id: card
    required property string titleText
    required property string detailText
    required property string metadataText
    required property string iconText
    required property string tooltipText
    property color foreground: Color.popups.text
    signal activated()

    implicitHeight: Math.max(Style.space(60), labels.implicitHeight + Style.space(24))
    height: implicitHeight
    radius: Style.cornerRadius
    color: hover.pressed ? Style.pressedFillFor(foreground, Color.accent)
      : hover.containsMouse ? Style.hoverFillFor(foreground, Color.accent)
      : Util.alpha(foreground, 0.035)
    border.width: Style.spacing.hairline
    border.color: Util.alpha(hover.containsMouse ? Color.accent : foreground, hover.containsMouse ? 0.3 : 0.08)

    Rectangle {
      id: icon
      anchors.left: parent.left
      anchors.leftMargin: Style.spacing.rowPaddingX
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(32)
      height: width
      radius: Style.cornerRadius
      color: Util.alpha(Color.accent, 0.08)
      Text {
        anchors.centerIn: parent
        text: card.iconText
        textFormat: Text.PlainText
        color: Color.accent
        font.family: Style.font.family
        font.pixelSize: Style.font.icon
      }
    }
    Column {
      id: labels
      anchors.left: icon.right
      anchors.leftMargin: Style.space(12)
      anchors.right: metadata.left
      anchors.rightMargin: Style.space(12)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)
      Text {
        width: parent.width
        text: card.titleText
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: card.foreground
        font.pixelSize: Style.font.body
        font.weight: Font.DemiBold
      }
      Text {
        width: parent.width
        text: card.detailText
        visible: text.length > 0
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Util.alpha(card.foreground, 0.72)
        font.pixelSize: Style.font.bodySmall
      }
    }
    Text {
      id: metadata
      anchors.right: parent.right
      anchors.rightMargin: Style.spacing.rowPaddingX
      anchors.verticalCenter: parent.verticalCenter
      width: Math.min(implicitWidth, card.width * 0.25)
      text: card.metadataText
      textFormat: Text.PlainText
      horizontalAlignment: Text.AlignRight
      elide: Text.ElideRight
      color: Util.alpha(card.foreground, 0.68)
      font.pixelSize: Style.font.caption
      lineHeight: 1.3
    }
    MouseArea {
      id: hover
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: card.activated()
    }
    PanelToolTip {
      visible: hover.containsMouse
      text: card.tooltipText
    }
  }

  component SectionHeader: Item {
    id: section
    required property string label
    required property string detail
    property color foreground: Color.popups.text
    implicitHeight: heading.implicitHeight + Style.space(8)
    height: implicitHeight
    Text {
      id: heading
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: section.label
      textFormat: Text.PlainText
      color: section.foreground
      font.pixelSize: Style.font.bodySmall
      font.weight: Font.DemiBold
    }
    Text {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: section.detail
      textFormat: Text.PlainText
      color: Util.alpha(section.foreground, 0.62)
      font.pixelSize: Style.font.caption
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
    contentHeight: popup.fittedContentHeight(header.height + Style.space(16) + content.implicitHeight, popup.screenH * 0.8)

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onReturnRequested: root.openSpark()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      Item {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(heading.implicitHeight, openButton.implicitHeight) + Style.space(8)
        Column {
          id: heading
          anchors.left: parent.left
          anchors.right: openButton.left
          anchors.rightMargin: Style.space(16)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(4)
          Text {
            id: headerTitle
            width: parent.width
            text: "Spark"
            textFormat: Text.PlainText
            color: root.contentForeground
            font.pixelSize: Style.font.heading
            font.weight: Font.DemiBold
          }
          Text {
            width: parent.width
            text: "Mail & calendar"
            textFormat: Text.PlainText
            color: Util.alpha(root.contentForeground, 0.62)
            font.pixelSize: Style.font.caption
          }
        }
        Button {
          id: openButton
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          text: "Open Spark ↗"
          foreground: Color.accent
          fontFamily: headerTitle.font.family
          fontSize: Style.font.bodySmall
          bordered: true
          onClicked: root.openSpark()
        }
      }
      Flickable {
        id: flick
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.topMargin: Style.space(16)
        anchors.bottom: parent.bottom
        contentWidth: width
        contentHeight: content.implicitHeight
        interactive: contentHeight > height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Controls.ScrollBar.vertical: Controls.ScrollBar {
          id: scrollBar
          policy: Controls.ScrollBar.AsNeeded
          visible: flick.interactive
          width: Style.space(3)
          padding: 0
          contentItem: Rectangle {
            implicitWidth: Style.space(3)
            radius: width / 2
            color: Util.alpha(root.contentForeground, scrollBar.pressed ? 0.6 : 0.28)
          }
          background: Item {}
        }
        Column {
          id: content
          width: flick.width - (scrollBar.visible ? Style.space(10) : 0)
          spacing: Style.spacing.rowGap
          SectionHeader {
            width: parent.width
            label: "Inbox"
            detail: root.emails.length ? root.emails.length + " shown" : ""
          }
          Text {
            visible: root.emails.length === 0 || root.status !== "Inbox"
            width: parent.width
            text: fetch.running && root.emails.length === 0 ? "Read the inbox..." : root.status
            textFormat: Text.PlainText
            color: Util.alpha(root.contentForeground, 0.72)
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
            padding: Style.spacing.rowPaddingX
          }
          Repeater {
            model: root.emails
            EntryCard {
              required property var modelData
              width: content.width
              titleText: modelData.sender
              detailText: modelData.subject || "(No subject)"
              metadataText: modelData.date.replace(" ", "\n")
              iconText: "󰇮"
              tooltipText: "Open email in Spark"
              foreground: root.contentForeground
              onActivated: root.openMessage(modelData.id)
            }
          }
          Item {
            width: parent.width
            height: Style.space(8)
          }
          SectionHeader {
            width: parent.width
            label: "Calendar"
            detail: root.eventsLabel
          }
          Text {
            visible: !root.remindersOk
            width: parent.width
            text: root.reminderStatus
            textFormat: Text.PlainText
            color: Color.urgent
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
            padding: Style.spacing.rowPaddingX
          }
          Text {
            visible: root.events.length === 0
            width: parent.width
            text: fetch.running ? "Read the calendar..." : root.eventsStatus
            textFormat: Text.PlainText
            color: Util.alpha(root.contentForeground, 0.72)
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.Wrap
            padding: Style.spacing.rowPaddingX
          }
          Repeater {
            model: root.events
            EntryCard {
              required property var modelData
              width: content.width
              titleText: modelData.title
              detailText: modelData.location || ""
              metadataText: modelData.time
              iconText: "󰃭"
              tooltipText: "Open calendar in Spark"
              foreground: root.contentForeground
              onActivated: root.openCalendar()
            }
          }
        }
      }
    }
  }
}
