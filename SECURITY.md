# Security

Goodtake v0.1 is a personal local application. Its native server binds to loopback by default;
Compose publishes only on `127.0.0.1`. It has no multi-user authentication and is not an internet
hosting product. The `--host 0.0.0.0` option exists for the container's internal listener.

State-changing API calls require `X-Goodtake: 1`. Browser writes must have the same Origin as the
studio. Host allowlisting limits DNS rebinding. User content is escaped, downloads use a closed
asset allowlist, source links are canonicalized to individual YouTube videos, and user media is not
part of the static web root. These measures do not replace authentication for public deployment.

API keys stay in environment variables or `GOODTAKE_HOME/keys.json` (mode 0600). They are not
returned by the settings API or included in guest kits. No analytics, third-party scripts or
automatic social posting are installed. Paid providers receive data only for the requested action;
see the README's data flow description.

For a vulnerability containing private details, use this repository's GitHub private vulnerability
reporting when available. Otherwise open a minimal issue requesting a private channel; do not
include credentials, exploitable recordings, personal data or attack payloads in a public report.
