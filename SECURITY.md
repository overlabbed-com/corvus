# Security Policy

## Reporting a Vulnerability

We take the security of Corvus seriously. If you believe you've found a security vulnerability, please report it to us.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please open a private security advisory via GitHub:
1. Go to the [Security tab](https://github.com/overlabbed-com/corvus/security/advisories)
2. Click "Report a vulnerability"
3. Provide details about the vulnerability

Alternatively, you can email us directly (contact information available in the repository).

### What to Include

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigations

### Response Timeline

- **Acknowledgment:** Within 48 hours
- **Initial Assessment:** Within 5 business days
- **Resolution Target:** Based on severity (critical: 30 days, high: 60 days, medium: 90 days)

## Security Measures

Corvus implements the following security measures:

### Authentication & Authorization
- API key authentication with role-based access control
- Optional OIDC/JWT support
- Rate limiting (500 requests/minute/IP)

### Data Protection
- Secret sanitization in logs (14+ patterns)
- Audit logging on all administrative endpoints
- No secrets stored in git history

### Infrastructure
- Non-root container user
- Multi-stage Docker builds
- Parameterized SQL queries
- Input validation via Pydantic

### Dependencies
- Regular dependency audits via pip-audit
- Pinned secure versions in pyproject.toml
- SAST scanning with Semgrep and Bandit

## Secure Deployment Checklist

When deploying Corvus:

- [ ] Set `CORVUS_DEV_MODE=false` in production
- [ ] Generate strong API keys (256-bit random)
- [ ] Use HTTPS/TLS for all endpoints
- [ ] Configure firewall rules to restrict access
- [ ] Enable audit logging
- [ ] Regular dependency updates
- [ ] Backup SQLite database regularly

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest release | ✅ |
| Previous release | ✅ (30 days) |
| Older versions | ❌ |

## Security Updates

Security updates are released as soon as possible after a vulnerability is confirmed. We recommend:

1. Subscribe to release notifications
2. Apply security patches promptly
3. Review release notes for security-related changes

## Contact

- Security Email: (add your security contact email)
- GitHub Security Advisories: https://github.com/overlabbed-com/corvus/security/advisories
