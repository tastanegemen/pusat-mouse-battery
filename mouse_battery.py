#!/usr/bin/python3
"""Read the battery report of the verified 260d:1074 Compx receiver."""
import argparse
from dataclasses import dataclass
import fcntl
import glob
import math
import os
from pathlib import Path
import select
import time

VID, PID = 0x260D, 0x1074
REPORT_SIZE = 17
HIDIOCSFEATURE = (3 << 30) | (REPORT_SIZE << 16) | (0x48 << 8) | 0x06


class BatteryError(Exception):
    """Device unavailable, inaccessible, or returning no valid battery report."""


@dataclass(frozen=True)
class BatteryReading:
    percent: int
    wired: bool
    millivolts: int
    status: int
    raw: bytes


def battery_hidraw():
    """Discover the vendor collection anew, including after USB reconnection."""
    for node in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        device = Path(node) / 'device'
        if f'{VID:04X}:{PID:04X}' not in device.resolve().name.upper():
            continue
        try:
            desc = (device / 'report_descriptor').read_bytes()
        except OSError:
            continue
        if b'\x06\x02\xff' in desc and b'\x85\x08' in desc:
            return '/dev/' + Path(node).name
    return None


def make_request():
    packet = bytearray(REPORT_SIZE)
    packet[0:2] = b'\x08\x04'
    packet[-1] = (0x55 - sum(packet)) & 0xff
    return bytes(packet)


def parse(reply):
    """Only accept the complete, checksummed format verified on this receiver."""
    if len(reply) != REPORT_SIZE:
        raise ValueError(f'Yanıt uzunluğu geçersiz: {len(reply)} (beklenen 17)')
    if reply[0] not in (8, 9) or reply[1] != 4:
        raise ValueError('Pil raporu değil')
    if sum(reply) & 0xff != 0x55:
        raise ValueError('Pil raporunun checksum değeri geçersiz')
    if reply[6] > 100:
        raise ValueError(f'Pil yüzdesi geçersiz: {reply[6]}')
    return BatteryReading(reply[6], bool(reply[7]), reply[8] | reply[9] << 8,
                          reply[5], bytes(reply))


def query_battery(node=None, timeout=2.0):
    node = node or battery_hidraw()
    if not node:
        raise BatteryError('USB alıcı bulunamadı')
    try:
        fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, HIDIOCSFEATURE, make_request())
            deadline = time.monotonic() + timeout
            invalid = None
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    break
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    continue
                if not data:
                    raise BatteryError('USB bağlantısı kesildi')
                if len(data) < 2 or data[0] not in (8, 9) or data[1] != 4:
                    continue
                try:
                    return parse(data)
                except ValueError as exc:
                    invalid = str(exc)
            raise BatteryError(invalid or 'Fare yanıt vermedi; uyuyor veya kapalı olabilir')
        finally:
            os.close(fd)
    except PermissionError as exc:
        raise BatteryError('USB erişim izni yok; install.sh ile udev kuralını kurun') from exc
    except OSError as exc:
        raise BatteryError(f'USB okuma hatası: {exc.strerror or exc}') from exc


def describe(reading):
    parts = ['kablo bağlı' if reading.wired else '2.4 GHz', 'checksum OK']
    if reading.millivolts:
        parts.append(f'{reading.millivolts} mV')
    return f"PİL %{reading.percent} ({', '.join(parts)})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', nargs='?', const=5.0, type=float,
                        help='belirtilen saniye aralığıyla tekrar oku (varsayılan 5)')
    parser.add_argument('--raw', action='store_true', help='ham raporu da yazdır')
    args = parser.parse_args()
    if args.watch is not None and (not math.isfinite(args.watch) or args.watch < 1):
        parser.error('--watch en az 1 saniye olmalı')
    try:
        while True:
            try:
                reading = query_battery()
                print(describe(reading), flush=True)
                if args.raw:
                    print('raw:', reading.raw.hex(' '), flush=True)
            except BatteryError as exc:
                print(str(exc), flush=True)
                if args.watch is None:
                    return 1
            if args.watch is None:
                return 0
            time.sleep(args.watch)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
