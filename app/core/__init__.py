"""Cross-cutting concerns: correlation, logging and error handling.

Nothing in here knows about the support domain. Everything the rest of the
application inherits — how a request is traced, how a failure is shaped —
is defined once, here.
"""
