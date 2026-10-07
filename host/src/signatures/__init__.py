# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON Web Signatures with nothing but `pow`, `hashlib` and `hmac`: RS256 and ES256 verification, RS256
signing, compact JWS, and a cached JWKS. The host runs on Pyodide, where the `cryptography` package would add
tens of megabytes to the startup snapshot. No Django import: the turn runner uses it too."""
