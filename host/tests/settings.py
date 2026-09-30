# SPDX-License-Identifier: AGPL-3.0-or-later
import os

os.environ.setdefault("DJANGO_DEBUG", "1")
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")
os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:9911/v1")
os.environ.setdefault("LLM_API_KEY", "dummy-test-key")

from config.settings import *  # noqa: F403
