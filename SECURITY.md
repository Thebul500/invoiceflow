# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

Only the latest minor release receives security patches. We recommend always running the most recent version.

## Reporting a Vulnerability

If you discover a security vulnerability in InvoiceFlow, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities.
2. Email your report to **security@invoiceflow.dev** with:
   - A description of the vulnerability
   - Steps to reproduce the issue
   - The potential impact
   - Any suggested fixes (optional)
3. You will receive an acknowledgment within **48 hours**.
4. We aim to provide a fix or mitigation within **7 days** for critical issues.

## Scope

The following areas are in scope for security reports:

- Authentication and authorization bypass
- SQL injection or other injection attacks
- Sensitive data exposure (API keys, credentials, invoice data)
- File upload vulnerabilities in the invoice ingestion pipeline
- Insecure deserialization
- Server-side request forgery (SSRF)

## Disclosure Policy

- We follow coordinated disclosure. Please allow us reasonable time to address the issue before public disclosure.
- Contributors who report valid vulnerabilities will be credited in the release notes (unless they prefer to remain anonymous).
