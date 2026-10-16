"""Process-level runtime setup.

Currently one concern: the event loop. See ADR-005.

psycopg's async mode refuses to run on asyncio's ``ProactorEventLoop``, which is
the default on Windows. Production runs on Linux where the default is already a
selector loop, so this is a development-only fix — but without it the
application reports a perfectly healthy database as unreachable, which is
indistinguishable from a real outage.

This must run *before* the event loop is created. Anything that starts the app
without going through here (a bare ``uvicorn app.main:create_app`` in an IDE,
for example) will reproduce the original error on Windows.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import warnings

logger = logging.getLogger(__name__)


def configure_event_loop_policy() -> None:
    """Select an asyncio event loop that the database driver can use.

    No-op on anything other than Windows.
    """
    if sys.platform != "win32":
        return

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:  # pragma: no cover - non-Windows guard
        return

    # Event loop policies are deprecated from Python 3.14 onward, but remain
    # the only way to influence a loop that someone else (uvicorn) creates.
    # When a supported replacement exists, this is the thing to revisit.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        asyncio.set_event_loop_policy(selector_policy())

    logger.debug("selector event loop policy applied for psycopg compatibility")
