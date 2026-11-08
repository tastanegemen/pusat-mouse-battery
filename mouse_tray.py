#!/usr/bin/python3
"""A nonblocking GNOME AppIndicator for the Monster Pusat receiver."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import AyatanaAppIndicator3, GdkPixbuf, GLib, Gtk
from mouse_battery import BatteryError, query_battery

POLL_SECONDS = 5
LOW_BATTERY = 20
ICON_DIR = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'mouse-battery' / 'v2'


def icon_svg(percent, wired=False):
    color = '#94a3b8' if percent is None else ('#38bdf8' if wired else
             '#f87171' if percent < LOW_BATTERY else '#fbbf24' if percent < 40 else '#4ade80')
    height = 0 if percent is None else round(38 * percent / 100, 1)
    bolt = '<path d="M35 31 26 44h7l-4 11 13-16h-8l5-8Z" fill="#f8fafc" stroke="#0f172a" stroke-width="1.5"/>' if wired else ''
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
<defs><clipPath id="body"><rect x="14" y="3" width="36" height="58" rx="18"/></clipPath></defs>
<rect x="14" y="3" width="36" height="58" rx="18" fill="#1e293b"/>
<g clip-path="url(#body)"><rect x="14" y="{61-height}" width="36" height="{height}" fill="{color}"/></g>
<rect x="14" y="3" width="36" height="58" rx="18" fill="none" stroke="{color}" stroke-width="3"/>
<path d="M32 4v21M15 26h34" stroke="{color}" stroke-width="2"/>
<rect x="28" y="10" width="8" height="12" rx="4" fill="{color}"/>{bolt}</svg>'''


def icon_path_for(percent, wired):
    bucket = None if percent is None else max(0, min(100, percent))
    path = ICON_DIR / f'mouse-{bucket}-{int(wired)}.png'
    try:
        if not path.exists():
            ICON_DIR.mkdir(parents=True, exist_ok=True)
            loader = GdkPixbuf.PixbufLoader.new_with_type('svg')
            loader.write(icon_svg(bucket, wired).encode())
            loader.close()
            loader.get_pixbuf().savev(str(path), 'png', [], [])
        return str(path)
    except Exception:
        logging.exception('Fare ikonu oluşturulamadı')
        return 'input-mouse-symbolic'


class MouseBatteryIndicator:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mouse-usb')
        self.busy = False
        self.closed = False
        self.last_reading = None
        self.last_success = None
        self.last_notify = None
        self.candidate = None
        self.confirm_source = None
        self.periodic_source = None
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            'mouse-battery', 'input-mouse-symbolic',
            AyatanaAppIndicator3.IndicatorCategory.SYSTEM_SERVICES)
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        self.item = Gtk.MenuItem(label='Monster Pusat · Pil okunuyor…')
        self.connection = Gtk.MenuItem(label='USB alıcı aranıyor')
        self.updated = Gtk.MenuItem(label='Henüz ölçüm yok')
        for item in (self.item, self.connection, self.updated):
            item.set_sensitive(False)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        self.refresh = Gtk.MenuItem(label='Şimdi yenile')
        self.refresh.connect('activate', self.on_manual_refresh)
        menu.append(self.refresh)
        quit_item = Gtk.MenuItem(label='Kapat')
        quit_item.connect('activate', self.on_quit)
        menu.append(quit_item)
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_icon_full(icon_path_for(None, False), 'Monster Pusat')
        self.indicator.set_label('…', '')
        self.request_update()
        self.periodic_source = GLib.timeout_add_seconds(POLL_SECONDS, self.tick)

    def request_update(self):
        if self.closed or self.busy:
            return False
        self.busy = True
        self.refresh.set_sensitive(False)
        future = self.executor.submit(query_battery)
        future.add_done_callback(self._worker_done)
        return False  # idle/timeouts must not repeat this request

    def _worker_done(self, future):
        try:
            result, error = future.result(), None
        except BatteryError as exc:
            result, error = None, str(exc)
        except Exception:
            logging.exception('Beklenmeyen pil okuma hatası')
            result, error = None, 'Pil okunurken beklenmeyen hata oluştu'
        if not self.closed:
            GLib.idle_add(self.apply_result, result, error)

    def apply_result(self, reading, error):
        if self.closed:
            return False
        self.busy = False
        self.refresh.set_sensitive(True)
        if error:
            self.candidate = None
            self.item.set_label('Monster Pusat · Pil bilgisi yok')
            self.connection.set_label(error)
            self.indicator.set_label('—', '')
            self.indicator.set_icon_full(icon_path_for(None, False), 'Pil bilgisi yok')
            if self.last_success:
                self.updated.set_label(f'Son başarılı ölçüm: {self.last_success}')
            return False
        previous = self.last_reading
        # A fresh cable flag updates immediately; only percentage jumps within
        # the same connection mode need a confirmation read.
        switch = previous is not None and reading.wired != previous.wired
        suspect = (previous is not None and not switch and
                   abs(reading.percent - previous.percent) > 12)
        if suspect and self.candidate is None:
            self.candidate = reading
            self.connection.set_label('Değişiklik doğrulanıyor…')
            self.confirm_source = GLib.timeout_add_seconds(3, self._confirm)
            return False
        # One additional fresh report bounds confirmation and avoids stale display.
        self.candidate = None
        self.last_reading = reading
        self.last_success = time.strftime('%H:%M:%S')
        self.item.set_label(f'Monster Pusat · %{reading.percent}')
        connection = 'USB kablosu bağlı' if reading.wired else '2.4 GHz kablosuz'
        if reading.millivolts:
            connection += f' · {reading.millivolts} mV'
        self.connection.set_label(connection)
        self.updated.set_label(f'Son ölçüm: {self.last_success}')
        self.indicator.set_label(f'{reading.percent}%{" ⚡" if reading.wired else ""}', '')
        self.indicator.set_icon_full(icon_path_for(reading.percent, reading.wired), connection)
        self.notify_low(reading)
        return False

    def notify_low(self, reading):
        if reading.wired or reading.percent >= LOW_BATTERY:
            self.last_notify = None
            return
        now = time.monotonic()
        if self.last_notify is not None and now - self.last_notify < 600:
            return
        notify = shutil.which('notify-send')
        if notify:
            try:
                subprocess.Popen([notify, '-u', 'critical', '-i', 'battery-low-symbolic',
                                  'Mouse pili azaldı', f'Pil %{reading.percent}. Lütfen şarj edin.'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.last_notify = now
            except OSError:
                logging.exception('Bildirim gönderilemedi')

    def _confirm(self):
        self.confirm_source = None
        self.request_update()
        return False

    def tick(self):
        self.request_update()
        return not self.closed

    def on_manual_refresh(self, _item):
        if self.confirm_source is not None:
            GLib.source_remove(self.confirm_source)
            self.confirm_source = None
        self.request_update()

    def on_quit(self, _item):
        self.closed = True
        for source in (self.confirm_source, self.periodic_source):
            if source is not None:
                GLib.source_remove(source)
        self.executor.shutdown(wait=False, cancel_futures=True)
        Gtk.main_quit()


def main():
    logging.basicConfig(level=logging.INFO)
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', Path.home() / '.cache' / 'mouse-battery'))
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'mouse-battery.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info('Mouse Battery zaten çalışıyor')
            return
        MouseBatteryIndicator()
        Gtk.main()


if __name__ == '__main__':
    main()
