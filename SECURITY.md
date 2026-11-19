# Security Policy

RawiBumi is in beta and does not yet have a formal release-support matrix; only the latest version on `main` gets fixes.

This edition has no user accounts. Do not expose a RawiBumi server to an untrusted network without access control in front of it (see *Self-hosting* in the README).

## Reporting a vulnerability

Please do not publish exploitable security details in a public issue.

Until a dedicated private security-reporting workflow is configured, repository maintainers should enable and use GitHub's private vulnerability reporting/security advisory mechanism for security-sensitive reports.

## Sensitive engineering data

RawiBumi may eventually process commercially sensitive project files, component files, weather datasets, imagery, and geometry. Implementations should therefore follow these baseline rules:

- private engineering files remain private by default;
- credentials and API keys must never be stored in project data or committed to the repository;
- uploaded data must have explicit retention/deletion behavior;
- self-hosted operation must not require unnecessary telemetry;
- proprietary source files must not be redistributed without permission.
