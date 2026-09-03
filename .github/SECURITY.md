# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting instead:
https://github.com/u3/api/security/advisories/new

You will get an acknowledgement within 3 business days. Please include steps to
reproduce, affected versions or commits, and any proof of concept you have.

## Supported versions

Only the `main` branch receives security fixes.

## Automated protections in this repository

- Dependabot security and version updates
- CodeQL code scanning on every pull request and weekly
- Secret scanning with push protection
- Dependency review on pull requests
- Branch ruleset on `main`: pull requests only, required reviews and status checks,
  signed commits, no force pushes or deletions
