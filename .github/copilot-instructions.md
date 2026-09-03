# Copilot review guidance for u3/api

When reviewing pull requests in this repository, prioritise:

1. **Security**: injection (SQL, command, template), authentication and authorization
   gaps, unsafe deserialisation, hard-coded secrets, insecure defaults, missing input
   validation at external boundaries, SSRF, path traversal.
2. **Correctness**: error handling paths, race conditions, null and undefined handling.
3. **Dependencies**: new packages should be justified; flag unpinned or unmaintained ones.
4. **Workflows**: any change under `.github/workflows` must keep least-privilege
   `permissions:` and must not use `pull_request_target` with a checkout of PR code.

Keep comments concrete: quote the line, explain the risk, propose a fix.
