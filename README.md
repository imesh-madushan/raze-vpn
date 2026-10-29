# raze VPN

A VPN manager for Noctalia and Dux Shell, with top-bar controls, multiple named VLESS profiles, guided settings, a full JSON editor, connectivity checks, logs and local-source updates.

## Install

Supported setup: CachyOS/Arch Linux with systemd, sing-box and either Noctalia 5.x (plugin API 24+) or Dux Shell 2.x. Dux uses GTK 4, libadwaita 1.5+ and Python GObject for the full manager window. Other distributions require adaptation of the installer.

```bash
bash setup.sh
```

Run as your normal desktop account. Setup installs missing OS packages, installs the application and scoped system helper, and adds the available shell widgets. Administrator authentication is requested when needed. Setup is repeatable and preserves existing installed profiles and selections. It does not connect the VPN or enable a boot service. In Dux, setup installs and enables the widget when Dux is running, adds it to enabled bars, and restarts Dux to show it.

**A fresh installation contains no VPN credentials or profiles.** Open the top-bar VPN panel → Manage profiles → Add profile, then enter your own VLESS link or a sing-box JSON file path.

## Profiles and UI

Noctalia's panel shows a status box with a live session timer, an exit-IP card (checked automatically once per connection; latency included, with a copy button), and the active profile. Choosing a different profile while connected offers **Switch & reconnect**. The Noctalia top-bar label can be set to icon only, `VPN`, or the profile name under Settings → Top bar label. Its indicator sends desktop notifications on connect, disconnect, failed start and an IPv6-still-enabled warning.

In Noctalia, click the VPN indicator for Connect/Disconnect, profile management, an HTTPS/exit-IP check, settings and logs. Right-click it for a quick toggle. In Dux, click the VPN bar widget for status and Connect/Disconnect, then **Open VPN manager** for the full GTK window. `vpn gui` opens the matching interface: Noctalia's panel when Noctalia is active, or the GTK window in Dux or another desktop. Opening either interface never connects or disconnects.

Profiles can be added, selected, duplicated, renamed, deleted and edited. Imports support one TLS-enabled VLESS connection over TCP or WebSocket. Unsupported URI parameters, Reality links and subscription bundles are rejected. JSON imports use the VLESS outbound with the managed IPv4-only routing template.

Guided settings cover server, port, TLS server name, transport, WebSocket host/path, certificate verification and optional UUID replacement. **Edit full JSON** validates syntax, sing-box compatibility, required routing settings and file revisions before saving. Successful edits create private backups. Invalid edits leave the existing profile unchanged. Edits and profile selections apply on the next connection; they do not interrupt the active session.

The JSON editor preserves advanced fields but requires an IPv4-only `singtun0` inbound with automatic/strict routing, the local SOCKS listener at `127.0.0.1:10808`, `dns.strategy = "ipv4_only"`, and a VLESS outbound tagged `vpn`. Connected profiles cannot be deleted or renamed; the final remaining profile cannot be deleted.

## Command line

```bash
vpn gui
vpn list
vpn start work
vpn stop
vpn status
vpn status --json
vpn check
vpn logs
vpn diagnose
vpn add work
vpn select work
vpn duplicate work travel
vpn rename travel remote
vpn edit work
vpn edit-json work
vpn delete remote
```

The command is installed at `~/.local/bin/vpn`; use that full path if the directory is absent from your PATH. `vpn add` prompts privately for a link or JSON path. Avoid placing credentials in shell arguments. `vpn edit-json` uses `$EDITOR`, defaulting to `nano`, on a private temporary copy.

## Updates

```bash
vpn update --check
vpn update
vpn update /path/to/newer/project
```

Settings → Tool updates provides the same source/version check and opens the updater in a terminal. Code changes are detected even without a version bump. Updates preserve installed profiles, backups and logs, and do not reconnect the active VPN.

Updates use the source folder recorded by the last successful setup. No hosted release server or Git remote is configured. Keep the project locally or supply the path to a newer copy.

## Networking and local data

During a connection, a root-owned supervisor saves the current IPv6 settings and disables IPv6. Sing-box runs as the desktop user with only network-administration/raw-socket capabilities and `NoNewPrivileges`. Public IPv4 traffic uses the tunnel; private/local destinations route directly. Disconnecting restores ordinary networking and the previous IPv6 settings.

The supervisor restores IPv6 on normal shutdown, startup failure, SIGINT, SIGTERM and SIGHUP. A root-only state file supports recovery after forced termination. A reboot reapplies OS defaults. Individual application connections may need to reconnect after network changes. This is not a persistent kill switch.

Personal runtime data is stored **outside this source project**:

| Location | Contents |
|---|---|
| `~/.config/raze-vpn/profiles` | User-entered private profiles |
| `~/.config/raze-vpn/backups` | Private profile backups |
| `~/.local/state/raze-vpn` | Logs, checks and installation metadata |
| `~/.local/share/raze-vpn/app` | Installed application code |
| `~/.local/share/noctalia/plugins/raze-vpn` | Installed Noctalia plugin |
| `~/.config/dms/plugins/razeVpn` | Installed Dux widget |

The installed service uses `raze-vpn.service`; system helpers and the scoped Polkit action are root-owned. No passwords are stored by the authorization broker. Profiles must remain locally available for the VPN to operate. Logs may contain connection destinations. Neither profiles nor logs are exported into the project or USB source copy.

The connection indicator reflects process/tunnel state. Check now separately verifies HTTPS and tries to discover the exit IP; unavailable IP-discovery providers are distinguished from failed HTTPS connectivity. Results expire after one minute. Forced IPv6 tests fail intentionally while the IPv4-only tunnel is active. Unauthenticated HTTP endpoint probes do not establish authenticated streaming reliability or access to every application.

## Development and source distribution

```bash
python3 -m unittest discover -s tests -v
noctalia plugins lint plugin
python3 tools/backup-usb.py /path/to/mounted/usb
```

Noctalia fixes panel size at open time (no runtime resize), so the panel height is set by `height` in `plugin/plugin.toml`; pages longer than that scroll. Noctalia UI code lives in `plugin/`; the Dux bar widget lives in `dux-plugin/`; the GTK manager lives in `src/gui.py`. Both interfaces use the same Python backend and private profiles. Installers are in `installer/`, and tests in `tests/`.

The USB helper copies only production source files (an allow-list in the script) into `PROJECTS/raze-vpn`, verifies every copied file byte by byte and flushes writes. It refuses unmounted destinations. It does not collect installed profiles, logs, machine snapshots or binaries. A source project copy is not a personal VPN-account backup; add your credentials separately after a clean OS installation.

Test fixtures use synthetic credentials and example domains. Runtime dependencies are installed through the OS package manager instead of shipping machine-specific binaries. The application source is MIT licensed; dependency packages retain their own licenses.
