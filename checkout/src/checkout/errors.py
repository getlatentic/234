# SPDX-License-Identifier: AGPL-3.0-or-later
"""Expected refusals: what the model or the person can act on, with a stable code."""


class DomainError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConfigError(DomainError):
    """A setting the server refuses to start with. Its message never holds a secret."""

    def __init__(self, message: str) -> None:
        super().__init__("CONFIG", message)
