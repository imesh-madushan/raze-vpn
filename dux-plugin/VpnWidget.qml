import QtQuick
import Quickshell
import Quickshell.Io
import qs.Common
import qs.DCommon.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root
    layerNamespacePlugin: "raze-vpn"

    readonly property string command: (Quickshell.env("HOME") || "") + "/.local/bin/vpn"
    property var vpnState: ({active: false, profile: "", active_profile: "", profiles: [], installed: false})
    property string notice: ""
    property bool busy: false

    function refresh() {
        Proc.runCommand("razeVpn.status", [root.command, "status", "--json"], (stdout, exitCode) => {
            if (exitCode !== 0) {
                root.notice = "Could not read VPN status"
                return
            }
            try {
                root.vpnState = JSON.parse(stdout)
                if (!root.busy) root.notice = ""
            } catch (error) {
                root.notice = "Invalid VPN status"
            }
        }, 0, 10000, root)
    }

    function control(action) {
        if (root.busy) return
        root.busy = true
        root.notice = "Confirm authorization if asked…"
        Proc.runCommand("razeVpn.control", [root.command, action], (stdout, exitCode) => {
            root.busy = false
            root.notice = exitCode === 0 ? "" : "VPN operation failed. Open manager → Logs."
            root.refresh()
        }, 0, Proc.noTimeout, root)
    }

    // The tunnel interface appearing or disappearing is the on/off signal, so wait for netlink
    // events instead of polling. The full status runs on that signal and while the popout is open.
    Process {
        id: linkWatch
        command: ["ip", "-o", "monitor", "link"]
        running: root.surfaceLive
        stdout: SplitParser {
            onRead: line => { if (line.indexOf("singtun0") >= 0) root.refresh() }
        }
        onExited: restartWatch.start()
    }

    Timer {
        id: restartWatch
        interval: 5000
        onTriggered: linkWatch.running = root.surfaceLive
    }

    // Slow safety net in case the watcher dies or an event is missed.
    function probe() {
        Proc.runCommand("razeVpn.probe", ["test", "-e", "/sys/class/net/singtun0"], (stdout, exitCode) => {
            if ((exitCode === 0) !== !!root.vpnState.active) root.refresh()
        }, 0, 3000, root)
    }

    Timer {
        interval: 60000
        running: root.surfaceLive
        repeat: true
        onTriggered: root.probe()
    }
    Component.onCompleted: refresh()

    horizontalBarPill: Component {
        Row {
            spacing: Theme.spacingXS
            DIcon {
                name: "vpn_lock"
                size: root.iconSize
                color: root.vpnState.active ? Theme.primary : Theme.surfaceVariantText
                anchors.verticalCenter: parent.verticalCenter
            }
            StyledText {
                text: root.vpnState.active ? "VPN ON" : "VPN OFF"
                font.pixelSize: Theme.fontSizeSmall
                color: root.vpnState.active ? Theme.surfaceText : Theme.surfaceVariantText
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: 2
            DIcon {
                name: "vpn_lock"
                size: root.iconSize
                color: root.vpnState.active ? Theme.primary : Theme.surfaceVariantText
                anchors.horizontalCenter: parent.horizontalCenter
            }
            StyledText {
                text: root.vpnState.active ? "ON" : "OFF"
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceText
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }

    popoutWidth: 360
    popoutHeight: 260
    popoutContent: Component {
        PopoutComponent {
            id: popout
            Timer {
                interval: 3000
                running: root.interactionActive
                repeat: true
                onRunningChanged: if (running) root.refresh()
                onTriggered: root.refresh()
            }
            headerText: "VPN"
            detailsText: root.vpnState.active ? "Connected through " + (root.vpnState.active_profile || "VPN") : "Using normal network connection"
            showCloseButton: true

            Item {
                width: parent.width
                implicitHeight: content.implicitHeight + Theme.spacingL * 2
                Column {
                    id: content
                    width: parent.width - Theme.spacingL * 2
                    x: Theme.spacingL
                    y: Theme.spacingM
                    spacing: Theme.spacingM
                    StyledText {
                        width: parent.width
                        text: "Selected: " + (root.vpnState.profile || "No profile")
                        color: Theme.surfaceText
                        font.pixelSize: Theme.fontSizeMedium
                        elide: Text.ElideRight
                    }
                    StyledText {
                        width: parent.width
                        text: root.vpnState.active && !root.vpnState.ipv6_disabled ? "Warning: IPv6 is still enabled" : root.notice
                        visible: text !== ""
                        color: Theme.surfaceVariantText
                        wrapMode: Text.WordWrap
                    }
                    DButton {
                        width: parent.width
                        text: root.busy ? "Working…" : (root.vpnState.active ? "Disconnect" : "Connect")
                        enabled: !root.busy && root.vpnState.installed && (root.vpnState.active || root.vpnState.profiles.length > 0)
                        onClicked: root.control(root.vpnState.active ? "stop" : "start")
                    }
                    DButton {
                        width: parent.width
                        text: "Open VPN manager"
                        onClicked: {
                            Quickshell.execDetached([root.command, "gui"])
                            popout.closePopout()
                        }
                    }
                }
            }
        }
    }
}
