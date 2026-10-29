#!/usr/bin/env python3
"""Desktop-independent GTK/libadwaita manager for the VPN backend."""
import argparse
import os
import threading

# The software renderer uses far less memory than the GPU one for this mostly static window.
os.environ.setdefault('GSK_RENDERER', 'cairo')

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk

import controller
import profiles

PAGES = [('main', 'VPN', 'network-vpn-symbolic'),
         ('profiles', 'Profiles', 'view-list-symbolic'),
         ('settings', 'Settings', 'emblem-system-symbolic'),
         ('json', 'JSON', 'text-x-script-symbolic'),
         ('logs', 'Logs', 'utilities-terminal-symbolic'),
         ('updates', 'Updates', 'software-update-available-symbolic')]

CSS = b'''
.hero { padding: 28px 20px 24px 20px; border-radius: 20px; }
.hero.on { background: alpha(@success_bg_color, 0.20); }
.hero.off { background: alpha(@window_fg_color, 0.06); }
.orb { border-radius: 999px; min-width: 96px; min-height: 96px; }
.orb.on { background: alpha(@success_bg_color, 0.35); color: @success_color; }
.orb.off { background: alpha(@window_fg_color, 0.10); color: alpha(@window_fg_color, 0.65); }
.orb image { -gtk-icon-size: 48px; }
.hero-state { font-size: 28px; font-weight: 800; }
.connect-btn { min-width: 200px; min-height: 48px; padding: 0 28px; font-weight: 700; }
.stat-card { padding: 12px 8px; border-radius: 16px; background: alpha(@window_fg_color, 0.06); }
.stat-value { font-size: 17px; font-weight: 700; }
.stat-key { font-size: 11px; opacity: 0.65; }
.code { font-family: monospace; font-size: 12px; padding: 8px; }
'''


def box(vertical=True, spacing=12):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                   spacing=spacing)


def label(text='', css=None, wrap=True):
    names = (css or '').split()
    item = Gtk.Label(label=text, xalign=0.5 if 'center' in names else 0, wrap=wrap)
    for name in names:
        if name != 'center':
            item.add_css_class(name)
    return item


def button(text, handler, css=None, icon=None):
    item = Gtk.Button()
    if icon and text:
        content = Adw.ButtonContent(label=text, icon_name=icon)
        item.set_child(content)
    elif icon:
        item.set_icon_name(icon)
    else:
        item.set_label(text)
    for name in (css or '').split():
        item.add_css_class(name)
    item.connect('clicked', handler)
    return item


def page(child, scroll=True):
    clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480, child=child)
    if scroll:
        child.set_valign(Gtk.Align.START)
    clamp.set_margin_top(16)
    clamp.set_margin_bottom(16)
    clamp.set_margin_start(14)
    clamp.set_margin_end(14)
    if not scroll:
        return clamp
    view = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    view.set_child(clamp)
    return view


def card_text(view_widget):
    frame = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    frame.add_css_class('card')
    frame.set_child(view_widget)
    return frame


class VpnWindow(Adw.ApplicationWindow):
    def __init__(self, app, initial_page):
        super().__init__(application=app, title='VPN · raze')
        self.set_default_size(560, 760)
        self.busy = False
        self.polling = False
        self.rebuilding = False
        self.state = {}
        self.json_name = ''
        self.json_revision = ''
        self._make_ui()
        self.stack.set_visible_child_name(initial_page if initial_page in dict((p[0], 1) for p in PAGES) else 'main')
        self.refresh()
        GLib.timeout_add_seconds(5, self.poll)
        self.connect('notify::is-active', lambda *_: self.refresh() if self.is_active() else None)

    # ---- layout -------------------------------------------------------
    def _make_ui(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(self.get_display(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        view = Adw.ToolbarView()
        self.toasts.set_child(view)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='VPN manager', subtitle='raze'))
        self.spinner = Gtk.Spinner()
        header.pack_end(self.spinner)
        view.add_top_bar(header)

        self.banner = Adw.Banner()
        self.banner.set_button_label('Dismiss')
        self.banner.connect('button-clicked', lambda b: b.set_revealed(False))
        view.add_top_bar(self.banner)

        self.stack = Adw.ViewStack()
        view.set_content(self.stack)
        bar = Adw.ViewSwitcherBar(stack=self.stack)
        bar.set_reveal(True)
        view.add_bottom_bar(bar)
        builders = {'main': self._main_page, 'profiles': self._profiles_page, 'settings': self._settings_page,
                    'json': self._json_page, 'logs': self._logs_page, 'updates': self._updates_page}
        self.lazy = {}
        for key, title, icon in PAGES:
            if key in ('main', 'profiles'):
                self.stack.add_titled_with_icon(builders[key](), key, title, icon)
            else:
                # Built on first visit so closed pages cost no memory.
                holder = Gtk.Box(vexpand=True)
                self.lazy[key] = (holder, builders[key])
                self.stack.add_titled_with_icon(holder, key, title, icon)
        self.stack.connect('notify::visible-child-name', self.on_page)

    def _main_page(self):
        content = box(spacing=18)

        self.hero = box(spacing=10)
        self.hero.add_css_class('hero')
        self.orb = Gtk.Image(icon_name='network-vpn-disabled-symbolic', halign=Gtk.Align.CENTER)
        orb_box = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        orb_box.add_css_class('orb')
        orb_box.append(self.orb)
        self.orb_box = orb_box
        self.orb.set_hexpand(True)
        self.orb.set_vexpand(True)
        self.hero.append(orb_box)
        self.status = label('Loading…', 'hero-state center', wrap=False)
        self.status.set_halign(Gtk.Align.CENTER)
        self.hero.append(self.status)
        self.detail = label('', 'dim-label', True)
        self.detail.set_justify(Gtk.Justification.CENTER)
        self.detail.set_halign(Gtk.Align.CENTER)
        self.hero.append(self.detail)
        self.connect_btn = button('Connect', self.on_connect, 'pill suggested-action connect-btn')
        self.connect_btn.set_halign(Gtk.Align.CENTER)
        self.connect_btn.set_margin_top(8)
        self.hero.append(self.connect_btn)
        self.switch = button('Switch & reconnect', self.on_switch, 'pill')
        self.switch.set_halign(Gtk.Align.CENTER)
        self.switch.set_visible(False)
        self.hero.append(self.switch)
        content.append(self.hero)

        stats = Gtk.Box(spacing=10, homogeneous=True)
        self.stat_uptime = self._stat(stats, 'Session')
        self.stat_ipv6 = self._stat(stats, 'IPv6')
        self.stat_exit = self._stat(stats, 'IP')
        content.append(stats)

        group = Adw.PreferencesGroup(title='Profile')
        self.selection = Adw.ComboRow(title='Selected profile', model=Gtk.StringList.new([]))
        self.selection.set_subtitle('')
        self.selection.connect('notify::selected', self.on_select)
        group.add(self.selection)
        self.server = Adw.ActionRow(title='Server', subtitle='')
        self.server.add_prefix(Gtk.Image(icon_name='network-server-symbolic'))
        self.server.set_subtitle_selectable(True)
        group.add(self.server)
        content.append(group)

        check = Adw.PreferencesGroup(title='Connection check')
        self.exit_row = Adw.ActionRow(title='Not checked yet', subtitle='Tests HTTPS reachability and shows your IP')
        self.exit_row.add_prefix(Gtk.Image(icon_name='emblem-synchronizing-symbolic'))
        run = button('Run check', self.on_check, 'suggested-action')
        run.set_valign(Gtk.Align.CENTER)
        self.exit_row.add_suffix(run)
        check.add(self.exit_row)
        content.append(check)
        return page(content)

    def _stat(self, parent, key):
        card = box(spacing=2)
        card.add_css_class('stat-card')
        value = label('—', 'stat-value center', wrap=False)
        value.set_ellipsize(3)
        caption = label(key, 'stat-key center', wrap=False)
        card.append(value)
        card.append(caption)
        parent.append(card)
        return value

    def _profiles_page(self):
        content = box(spacing=18)
        self.profile_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.profile_list.add_css_class('boxed-list')
        self.profile_list.connect('row-activated', self.on_row_activated)
        group = Adw.PreferencesGroup(title='Profiles', description='Stored privately on this computer.')
        group.add(self.profile_list)
        content.append(group)
        actions = Gtk.Box(spacing=8, homogeneous=True)
        for text, icon, callback, css in [('Add', 'list-add-symbolic', self.on_add, 'suggested-action'),
                                          ('Duplicate', 'edit-copy-symbolic', self.on_duplicate, None),
                                          ('Rename', 'document-edit-symbolic', self.on_rename, None),
                                          ('Delete', 'user-trash-symbolic', self.on_delete, 'destructive-action')]:
            actions.append(button(text, callback, css, icon))
        content.append(actions)
        return page(content)

    def _settings_page(self):
        content = box(spacing=18)
        self.settings_title = Adw.PreferencesGroup(title='Connection',
                                                   description='Profile settings apply on the next connection.')
        self.fields = {}
        for key, title in [('server', 'Server'), ('port', 'Port'), ('sni', 'TLS server name'),
                           ('ws_host', 'WebSocket host'), ('ws_path', 'WebSocket path')]:
            row = Adw.EntryRow(title=title)
            self.settings_title.add(row)
            self.fields[key] = row
        content.append(self.settings_title)

        security = Adw.PreferencesGroup(title='Transport and security')
        self.transport = Adw.ComboRow(title='Transport', model=Gtk.StringList.new(['tcp', 'ws']))
        security.add(self.transport)
        self.tls_verify = Adw.SwitchRow(title='Verify TLS certificate')
        security.add(self.tls_verify)
        self.uuid = Adw.PasswordEntryRow(title='Replace UUID (optional)')
        security.add(self.uuid)
        content.append(security)
        save = button('Save profile settings', self.on_save_settings, 'pill suggested-action')
        save.set_halign(Gtk.Align.CENTER)
        content.append(save)
        return page(content)

    def _json_page(self):
        content = box(spacing=12)
        self.json_title = label('Full sing-box JSON. Saves are validated and backed up.', 'dim-label')
        content.append(self.json_title)
        self.json_editor = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.NONE)
        self.json_editor.add_css_class('code')
        content.append(card_text(self.json_editor))
        actions = Gtk.Box(spacing=8, homogeneous=True)
        actions.append(button('Reload', self.on_reload_json, None, 'view-refresh-symbolic'))
        actions.append(button('Validate and save', self.on_save_json, 'suggested-action', 'document-save-symbolic'))
        content.append(actions)
        return page(content, scroll=False)

    def _logs_page(self):
        content = box(spacing=12)
        self.logs = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.logs.add_css_class('code')
        content.append(card_text(self.logs))
        content.append(button('Refresh logs', self.on_logs, None, 'view-refresh-symbolic'))
        return page(content, scroll=False)

    def _updates_page(self):
        content = box(spacing=18)
        group = Adw.PreferencesGroup(title='Local source', description='Updates come from the installed project directory.')
        self.up_installed = Adw.ActionRow(title='Installed version', subtitle='—')
        self.up_project = Adw.ActionRow(title='Project version', subtitle='—')
        self.up_source = Adw.ActionRow(title='Source', subtitle='—')
        self.up_source.set_subtitle_selectable(True)
        self.up_state = Adw.ActionRow(title='Status', subtitle='Not checked')
        for row in (self.up_installed, self.up_project, self.up_source, self.up_state):
            group.add(row)
        content.append(group)
        actions = Gtk.Box(spacing=8, homogeneous=True)
        actions.append(button('Check project source', self.on_updates, None, 'view-refresh-symbolic'))
        actions.append(button('Open updater in terminal', self.on_launch_update, 'suggested-action',
                              'utilities-terminal-symbolic'))
        content.append(actions)
        return page(content)

    # ---- feedback -----------------------------------------------------
    def say(self, message, error=False):
        if error and message:
            self.banner.set_title(GLib.markup_escape_text(message))
            self.banner.set_revealed(True)
        elif message and message != 'Working…':
            self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=3))
        if not error and message in ('', None):
            self.banner.set_revealed(False)

    def task(self, work, done=None):
        if self.busy:
            return
        self.busy = True
        self.spinner.start()
        self.connect_btn.set_sensitive(False)

        def worker():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, str(exc)

            def finish():
                self.busy = False
                self.spinner.stop()
                if error:
                    self.say(error, True)
                else:
                    self.say('')
                    if done:
                        done(result)
                self.refresh()
                return False

            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        # Timer tick: skip the work while the window is hidden or on a page that shows no live state.
        if self.get_mapped() and self.stack.get_visible_child_name() in ('main', 'profiles'):
            self.refresh()
        return True

    def refresh(self):
        if self.polling:
            return True
        self.polling = True

        def worker():
            try:
                value, error = controller.snapshot(), None
            except Exception as exc:
                value, error = None, str(exc)

            def apply():
                self.polling = False
                if error:
                    self.say(error, True)
                elif value:
                    self.apply_state(value)
                return False

            GLib.idle_add(apply)

        threading.Thread(target=worker, daemon=True).start()
        return True

    @staticmethod
    def duration(seconds):
        seconds = int(seconds)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return '%dh %02dm' % (hours, minutes)
        return '%dm %02ds' % (minutes, secs) if minutes else '%ds' % secs

    def show_check(self, check):
        if not check:
            return
        if check.get('ok'):
            self.exit_row.set_title('HTTPS reachable')
            self.exit_row.set_subtitle('IP ' + GLib.markup_escape_text(check.get('ip') or 'unavailable'))
            self.stat_exit.set_text(check.get('ip') or '—')
        else:
            self.exit_row.set_title('Check failed')
            self.exit_row.set_subtitle(GLib.markup_escape_text(check.get('error', '')))
            self.stat_exit.set_text('failed')

    def apply_state(self, state):
        before = self.state.get('profile')
        previous_profiles = self.state.get('profiles', [])
        self.state = state
        active = state['active']
        for widget, on in ((self.hero, active), (self.orb_box, active)):
            widget.remove_css_class('off' if on else 'on')
            widget.add_css_class('on' if on else 'off')
        self.orb.set_from_icon_name('network-vpn-symbolic' if active else 'network-vpn-disabled-symbolic')
        self.status.set_text('Connected' if active else 'Disconnected')
        self.detail.set_text(('Protected via ' + (state.get('active_profile') or 'VPN')) if active
                             else 'Using your normal network connection.\nSettings are restored when the VPN stops.')
        self.stat_uptime.set_text(self.duration(state.get('uptime', 0)) if active else '—')
        self.stat_ipv6.set_text(('off' if state['ipv6_disabled'] else 'on') if active else 'normal')
        if not active:
            self.stat_exit.set_text('—')
        self.connect_btn.set_label('Disconnect' if active else 'Connect')
        self.connect_btn.remove_css_class('destructive-action' if not active else 'suggested-action')
        self.connect_btn.add_css_class('suggested-action' if not active else 'destructive-action')
        self.connect_btn.set_sensitive(not self.busy and state['installed'] and (active or bool(state['profiles'])))
        self.switch.set_visible(active and state['profile'] != state['active_profile'])
        self.switch.set_sensitive(not self.busy)
        self.server.set_subtitle(GLib.markup_escape_text(state.get('server', '')))
        self.rebuilding = True
        names = state['profiles']
        self.selection.set_model(Gtk.StringList.new(names))
        if state['profile'] in names:
            self.selection.set_selected(names.index(state['profile']))
        self.rebuilding = False
        if active:
            self.show_check(state.get('check'))
        if previous_profiles != state.get('profiles') or before != state.get('profile'):
            self.rebuild_profiles()
        if before != state.get('profile'):
            self.load_settings()
            self.load_json()

    def rebuild_profiles(self):
        while row := self.profile_list.get_first_child():
            self.profile_list.remove(row)
        current = self.state.get('profile')
        running = self.state.get('active_profile')
        for name in self.state.get('profiles', []):
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), activatable=True)
            row.profile_name = name
            row.add_prefix(Gtk.Image(icon_name='emblem-ok-symbolic' if name == current else 'radio-symbolic'))
            if name == running:
                row.set_subtitle('In use')
            elif name == current:
                row.set_subtitle('Selected')
            self.profile_list.append(row)

    def on_row_activated(self, _, row):
        name = getattr(row, 'profile_name', None)
        if name and name != self.selected():
            self.select(name)

    def selected(self):
        return self.state.get('profile') or ''

    def select(self, name):
        self.task(lambda: profiles.manage('select', name), lambda _: self.refresh())

    def on_select(self, drop, _):
        if self.rebuilding:
            return
        item = drop.get_selected_item()
        if item and item.get_string() != self.selected():
            self.select(item.get_string())

    # ---- actions ------------------------------------------------------
    def on_connect(self, _):
        action = 'stop' if self.state.get('active') else 'start'
        self.task(lambda: controller.control(action))

    def on_switch(self, _):
        def work():
            controller.control('stop')
            return controller.control('start')
        self.task(work)

    def on_check(self, _):
        self.task(controller.check, self.show_check)

    def prompt(self, title, fields, callback, secret=False):
        dialog = Adw.AlertDialog(heading=title)
        group = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        group.add_css_class('boxed-list')
        entries = []
        for caption, initial in fields:
            row = Adw.PasswordEntryRow(title=caption) if secret and len(entries) == len(fields) - 1 \
                else Adw.EntryRow(title=caption)
            row.set_text(initial)
            group.append(row)
            entries.append(row)
        dialog.set_extra_child(group)
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('ok', title)
        dialog.set_response_appearance('ok', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('ok')

        def response(_, answer):
            if answer == 'ok':
                callback([entry.get_text().strip() for entry in entries])

        dialog.connect('response', response)
        dialog.present(self)

    def on_add(self, _):
        self.prompt('Add profile', [('Profile name', ''), ('VLESS link or JSON file path', '')],
                    lambda v: self.task(lambda: profiles.manage('add', v[0], v[1])), secret=True)

    def on_duplicate(self, _):
        if self.selected():
            self.prompt('Duplicate profile', [('New profile name', self.selected() + '-copy')],
                        lambda v: self.task(lambda: profiles.manage('duplicate', self.selected(), v[0])))

    def on_rename(self, _):
        if self.selected():
            name = self.selected()
            self.prompt('Rename profile', [('New profile name', name)],
                        lambda v: self.task(lambda: profiles.manage('rename', name, v[0],
                                                                     active=self.state.get('active_profile', ''))))

    def on_delete(self, _):
        if not self.selected():
            return
        name = self.selected()
        dialog = Adw.AlertDialog(heading='Delete ' + name + '?', body='A private backup will be kept.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('delete', 'Delete')
        dialog.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')

        def respond(_, response):
            if response == 'delete':
                self.task(lambda: profiles.manage('delete', name, active=self.state.get('active_profile', '')))

        dialog.connect('response', respond)
        dialog.present(self)

    def load_settings(self):
        if not self.selected() or 'settings' in self.lazy:
            return
        try:
            values = profiles.details(self.selected())
        except Exception as exc:
            self.say(str(exc), True)
            return
        self.settings_title.set_title(GLib.markup_escape_text('Connection · ' + self.selected()))
        for key, entry in self.fields.items():
            entry.set_text(values[key])
        self.transport.set_selected(1 if values['transport'] == 'ws' else 0)
        self.tls_verify.set_active(values['tls_verify'])
        self.uuid.set_text('')

    def on_save_settings(self, _):
        name = self.selected()
        if not name:
            return
        values = {'name': name, **{key: field.get_text().strip() for key, field in self.fields.items()},
                  'transport': 'ws' if self.transport.get_selected() == 1 else 'tcp',
                  'tls_verify': self.tls_verify.get_active(), 'uuid': self.uuid.get_text().strip()}
        self.task(lambda: profiles.manage('edit', name, values),
                  lambda _: (self.uuid.set_text(''), self.say('Profile saved')))

    def load_json(self):
        if 'json' in self.lazy:
            return
        if not self.selected():
            self.json_editor.get_buffer().set_text('')
            return
        try:
            data = profiles.json_details(self.selected())
        except Exception as exc:
            self.say(str(exc), True)
            return
        self.json_name = data['name']
        self.json_revision = data['revision']
        self.json_title.set_text('Editing ' + self.json_name + ' · saves are validated and backed up.')
        self.json_editor.get_buffer().set_text(data['content'])

    def on_reload_json(self, _):
        self.load_json()

    def on_save_json(self, _):
        if not self.json_name:
            return
        data = self.json_editor.get_buffer()
        start, end = data.get_bounds()
        value = {'content': data.get_text(start, end, False), 'revision': self.json_revision}
        self.task(lambda: profiles.manage('edit-json', self.json_name, value),
                  lambda _: (self.load_json(), self.say('JSON saved')))

    def on_logs(self, _):
        self.task(controller.logs_text, lambda value: self.logs.get_buffer().set_text(value))

    def on_updates(self, _):
        import updates

        def done(info):
            self.up_installed.set_subtitle(str(info['installed_version']))
            self.up_project.set_subtitle(str(info['source_version'] or 'missing'))
            self.up_source.set_subtitle(GLib.markup_escape_text(str(info['source'])))
            self.up_state.set_subtitle('Update available' if info['update_available']
                                       else 'Up to date' if info['available'] else 'Source missing')
        self.task(updates.status, done)

    def on_launch_update(self, _):
        import updates
        self.task(updates.launch, lambda result: self.say(result['message']))

    def on_page(self, *_):
        name = self.stack.get_visible_child_name()
        if name in self.lazy:
            holder, build = self.lazy.pop(name)
            holder.append(build())
        if name == 'settings':
            self.load_settings()
        elif name == 'json':
            self.load_json()
        elif name == 'logs':
            self.on_logs(None)
        elif name == 'updates':
            self.on_updates(None)


class VpnApplication(Adw.Application):
    def __init__(self, page):
        super().__init__(flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.page = page

    def do_activate(self):
        window = VpnWindow(self, self.page)
        window.present()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--page', choices=[p[0] for p in PAGES], default='main')
    args = parser.parse_args()
    return VpnApplication(args.page).run([])


if __name__ == '__main__':
    raise SystemExit(main())
