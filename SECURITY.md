# Security Policy

## Supported Versions

Attorney.AI is under active development. Security fixes are applied to the
latest `master` branch.

| Version | Supported |
| ------- | --------- |
| `master` (latest) | ✅ |
| older commits | ❌ |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you believe you have found a security vulnerability, report it privately:

1. **Preferred:** Use GitHub's [Private Vulnerability Reporting](https://github.com/muhammadusamahoyrr/fyp/security/advisories/new)
   (Security tab → *Report a vulnerability*).
2. Alternatively, email **muhammadusamahoyrr@gmail.com** with the subject
   line `SECURITY: Attorney.AI`.

Please include, where possible:

- A description of the vulnerability and its impact
- Steps to reproduce (proof-of-concept, affected endpoint/file)
- Any suggested remediation

## What to Expect

- **Acknowledgement** of your report within **72 hours**.
- An assessment and, if confirmed, a remediation timeline.
- Credit in the release notes once a fix ships, if you would like it.

## Scope

This policy covers the application code in this repository (backend API,
AI pipeline, and frontend). It does **not** cover:

- Vulnerabilities in third-party dependencies (report those upstream; we
  track them via Dependabot).
- Issues that require a compromised host, physical access, or self-inflicted
  misconfiguration.

## Handling of Secrets

No credentials belong in this repository. All secrets are supplied at runtime
via environment variables (`.env`, which is git-ignored). If you discover a
committed secret, please report it privately so it can be rotated.
