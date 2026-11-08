import concurrent.futures
import unittest
from unittest.mock import Mock, patch

import mouse_battery as core
import mouse_tray as tray


def report(percent=70, wired=False):
    data = bytearray(17)
    data[0:2] = bytes([9, 4])
    data[5:8] = bytes([2, percent, int(wired)])
    data[-1] = (0x55 - sum(data)) & 255
    return bytes(data)


class ReaderTests(unittest.TestCase):
    def test_request_and_real_receiver_report(self):
        self.assertEqual(len(core.make_request()), 17)
        self.assertEqual(sum(core.make_request()) & 255, 0x55)
        reading = core.parse(bytes.fromhex('09 04 00 00 00 02 64 00 00 00 00 00 00 00 00 00 e2'))
        self.assertEqual((reading.percent, reading.wired), (100, False))

    def test_invalid_reports_are_rejected(self):
        for size in range(17):
            with self.subTest(size=size), self.assertRaises(ValueError):
                core.parse(report()[:size])
        for bad in (report(255), report()[:-1] + b'\x01', bytes(17), report() + b'\x00'):
            with self.assertRaises(ValueError):
                core.parse(bad)

    def test_unrelated_and_bad_packets_are_skipped(self):
        with patch.object(core.os, 'open', return_value=12), \
             patch.object(core.os, 'close') as close, \
             patch.object(core.fcntl, 'ioctl'), \
             patch.object(core.select, 'select', return_value=([12], [], [])), \
             patch.object(core.os, 'read', side_effect=[b'\x01\x02', report()[:7], report(45)]):
            self.assertEqual(core.query_battery('/dev/mock').percent, 45)
            close.assert_called_once_with(12)

    def test_rediscovery_on_every_query(self):
        with patch.object(core, 'battery_hidraw', side_effect=['/dev/hidraw1', '/dev/hidraw8']), \
             patch.object(core.os, 'open', side_effect=FileNotFoundError()) as opened:
            for _ in range(2):
                with self.assertRaises(core.BatteryError):
                    core.query_battery()
            self.assertEqual([c.args[0] for c in opened.call_args_list],
                             ['/dev/hidraw1', '/dev/hidraw8'])

    def test_permission_error_is_actionable(self):
        with patch.object(core.os, 'open', side_effect=PermissionError()):
            with self.assertRaisesRegex(core.BatteryError, 'erişim izni'):
                core.query_battery('/dev/mock')

    def test_timeout_closes_fd(self):
        with patch.object(core.os, 'open', return_value=12), \
             patch.object(core.os, 'close') as close, \
             patch.object(core.fcntl, 'ioctl'), \
             patch.object(core.select, 'select', return_value=([], [], [])):
            with self.assertRaisesRegex(core.BatteryError, 'yanıt vermedi'):
                core.query_battery('/dev/mock')
            close.assert_called_once_with(12)

    def test_disconnect_closes_fd(self):
        with patch.object(core.os, 'open', return_value=12), \
             patch.object(core.os, 'close') as close, \
             patch.object(core.fcntl, 'ioctl'), \
             patch.object(core.select, 'select', return_value=([12], [], [])), \
             patch.object(core.os, 'read', return_value=b''):
            with self.assertRaises(core.BatteryError):
                core.query_battery('/dev/mock')
            close.assert_called_once_with(12)


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.app = tray.MouseBatteryIndicator.__new__(tray.MouseBatteryIndicator)
        for name in ('indicator', 'item', 'connection', 'updated', 'refresh'):
            setattr(self.app, name, Mock())
        self.app.busy = False
        self.app.closed = False
        self.app.last_reading = None
        self.app.last_success = None
        self.app.last_notify = None
        self.app.candidate = None
        self.app.confirm_source = None
        self.icon = patch.object(tray, 'icon_path_for', return_value='test-icon')
        self.icon.start()
        self.addCleanup(self.icon.stop)

    def test_only_one_inflight_read_and_nonrepeating_callback(self):
        self.app.executor = Mock()
        self.app.executor.submit.return_value = concurrent.futures.Future()
        self.assertFalse(self.app.request_update())
        self.assertFalse(self.app.request_update())
        self.app.executor.submit.assert_called_once_with(tray.query_battery)

    def test_error_hides_stale_percentage(self):
        self.app.last_success = '12:00:00'
        self.assertFalse(self.app.apply_result(None, 'USB alıcı bulunamadı'))
        self.app.indicator.set_label.assert_called_with('—', '')
        self.app.updated.set_label.assert_called_with('Son başarılı ölçüm: 12:00:00')

    def test_low_threshold_cooldown_and_recovery(self):
        with patch.object(tray.shutil, 'which', return_value='/usr/bin/notify-send'), \
             patch.object(tray.subprocess, 'Popen') as notify:
            self.app.notify_low(core.parse(report(25)))
            notify.assert_not_called()
            self.app.notify_low(core.parse(report(19)))
            self.app.notify_low(core.parse(report(18)))
            self.assertEqual(notify.call_count, 1)
            self.app.notify_low(core.parse(report(18, True)))
            self.assertIsNone(self.app.last_notify)

    def test_cable_removal_updates_icon_without_confirmation_delay(self):
        self.app.last_reading = core.parse(report(95, True))
        with patch.object(tray.GLib, 'timeout_add_seconds') as schedule:
            self.assertFalse(self.app.apply_result(core.parse(report(100, False)), None))
        schedule.assert_not_called()
        self.app.indicator.set_label.assert_called_with('100%', '')
        tray.icon_path_for.assert_called_with(100, False)
        self.assertFalse(self.app.last_reading.wired)

    def test_confirmation_result_still_notifies(self):
        self.app.last_reading = core.parse(report(50))
        self.app.notify_low = Mock()
        with patch.object(tray.GLib, 'timeout_add_seconds', return_value=123):
            self.assertFalse(self.app.apply_result(core.parse(report(10)), None))
            self.app.notify_low.assert_not_called()
            self.assertFalse(self.app.apply_result(core.parse(report(11)), None))
        self.assertEqual(self.app.last_reading.percent, 11)
        self.app.notify_low.assert_called_once()


if __name__ == '__main__':
    unittest.main()
