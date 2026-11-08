# Contributing

Bug reports, reproducible packet captures, and compatibility reports are welcome.
The current hardware support is intentionally limited to the verified receiver;
sharing a brand or chipset name is not enough to add a supported-device claim.

## Local checks

Install the system GI/GTK/AppIndicator dependencies listed in the README, then:

```bash
/usr/bin/python3 -m unittest discover -s tests -v
bash -n install.sh
/usr/bin/python3 -m py_compile mouse_battery.py mouse_tray.py
```

The unit tests mock USB I/O and UI objects. They require the GI libraries to
import the indicator module but do not start GTK or access physical devices.
Real-device checks are separate from unit tests and CI.

## Compatibility reports

Include:

- Distribution and version, CPU architecture, Python version, and desktop/session type.
- Mouse's retail model name, receiver vendor/product ID, and firmware if known.
- Whether you tested the CLI, icon, menu, notifications, and autostart separately.
- Exact steps and raw battery replies before and after a cable transition.
- Dependencies and permission setup used on distributions other than Ubuntu.

Use `python3 mouse_battery.py --raw` for captures. For CLI-only diagnostics,
quit the indicator temporarily so there is a single querying process.
A passing CI test is not a hardware-compatibility result.

## Changes

Keep protocol handling in `mouse_battery.py` and desktop presentation in
`mouse_tray.py`. Avoid blocking I/O on the GTK thread. Preserve one in-flight
query and nonrepeating GLib idle callbacks. Add focused regression tests for
behavioral fixes and document any new packet formats with actual captures.

Do not commit `.env`, passwords, machine-specific paths, logs, or hardware
serial numbers. The application has no credential configuration.

Contributions are provided under the repository's MIT license. Preserve
attribution and applicable licenses when bringing in third-party code or assets.
