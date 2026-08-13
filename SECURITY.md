# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting feature for security issues. Do not include live credentials, public Modbus endpoints, or unredacted Home Assistant diagnostics in a public issue.

## Network safety

This integration communicates locally over Modbus TCP. Modbus does not provide authentication or encryption, so devices and gateways should remain on a trusted network and TCP port 502 should not be exposed to the internet.

The integration intentionally limits writes to power, operating mode, heating target, cooling target, and optional DHW target. It does not provide an arbitrary-register write service.
