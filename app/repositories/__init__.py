"""Data access.

Repositories own SQL. Services own decisions. Nothing above this layer writes a
query, so when the Database Engineer needs to review the access patterns there
is exactly one place to look.
"""
