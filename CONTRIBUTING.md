# Contributing

Bug reports, tested register observations, translations, and pull requests are welcome.

When reporting a register-map difference, include the exact KAISAI model, firmware version when available, register address, raw value, expected meaning, and whether the observation was read-only. Remove hostnames, IP addresses, and other private network information before attaching diagnostics.

Before opening a pull request, run:

```text
python -m pytest
ruff check .
python -m compileall custom_components
```

Do not add arbitrary Modbus writes. Profiles may change encoding and addresses for existing semantic controls, but write authorization must remain in the integration's hard-coded allowlist.
