# Receiver protocol and observations

These notes describe the format verified on one Monster Pusat mouse with a
Compx `260d:1074` USB receiver. They are not a specification for all Compx,
Nordic, or Pusat devices. The original local implementation referenced
[Fan4Metal/mouse_tray](https://github.com/Fan4Metal/mouse_tray).

## Discovery and transport

The reader scans `/sys/class/hidraw/hidraw*`, matches the HID device's vendor and
product ID, and selects a descriptor containing usage page `0xFF02` and report
ID `0x08`. The descriptor search is a byte-pattern heuristic, not a complete
HID descriptor parser. Multiple identical receivers are not explicitly supported;
the first matching collection is selected.

A 17-byte feature request is sent using `HIDIOCSFEATURE`. Replies are read from
the same hidraw file descriptor with a two-second input-wait deadline. This
deadline bounds the select/read loop, not a kernel-level ioctl stall. A new file
descriptor is opened for every query. Discovery is repeated on every query so
changes in hidraw numbering do not leave a cached stale device path.

See the Linux kernel's [hidraw documentation](https://docs.kernel.org/hid/hidraw.html)
for the underlying ioctl and read interface.

## Request

```text
08 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 49
```

- Byte 0: report ID `0x08`.
- Byte 1: battery subcommand `0x04`.
- Final byte: chosen so the unsigned sum of all 17 bytes modulo 256 is `0x55`.

## Reply

Offsets are zero-based and include the report ID.

| Byte(s) | Interpretation in the current reader |
| --- | --- |
| 0 | Report ID, accepted as `0x08` or `0x09`; `0x09` observed |
| 1 | Echoed subcommand `0x04` |
| 2–4 | Unknown / unused |
| 5 | Raw status byte; meaning not established (`0x02` observed) |
| 6 | Device-reported percentage, constrained to 0–100 |
| 7 | Cable flag, interpreted as nonzero = connected |
| 8–9 | Candidate little-endian millivolt field from the original implementation; only zero observed, interpretation unverified |
| 10–15 | Unknown / unused |
| 16 | Checksum byte; full report sum modulo 256 must be `0x55` |

The reader rejects incomplete/overlong reports, wrong IDs or subcommands,
invalid checksums, and percentages over 100. Other input reports are skipped.
It does not use the status byte to infer charge completion or physical link health.
Shorter or differently checksummed firmware formats need investigation before support.

## Captured cable transition

Observed on 2026-11-08 on Ubuntu 26.04.1 LTS / x86_64:

```text
Cable disconnected, 100%:
09 04 00 00 00 02 64 00 00 00 00 00 00 00 00 00 e2

Cable connected, 95%:
09 04 00 00 00 02 5f 01 00 00 00 00 00 00 00 00 e6
```

During a roughly one-minute observation with reads every two seconds, the wired
report stayed at 95%. After cable removal it switched back to the 100% report
and remained stable. Only bytes 6, 7, and 16 changed. Both checksums are valid;
status stayed `0x02` and the candidate voltage field stayed zero.

This establishes a difference in **reported** level by connection mode on the
tested device. It does not establish which percentage is more accurate, whether
the receiver caches values, or whether a five-point offset exists at other levels.
The application therefore does not add or subtract a fixed correction.

## Open questions

- Exact retail model name and firmware revision of the tested mouse.
- Meaning of status `0x02` and whether other values indicate sleep or disconnection.
- Whether the presumed voltage field is meaningful on any compatible firmware.
- Whether the connected flag distinguishes charging from a fully charged cable connection.
- Whether wireless reports are cached by the receiver after the mouse sleeps.
- Packet layout and ioctl portability across additional receivers and architectures.

When contributing captures, specify receiver ID, mouse model, OS/architecture,
connection mode, timing, and the complete raw report. Do not attach unrelated
hardware serial numbers or private environment files.
