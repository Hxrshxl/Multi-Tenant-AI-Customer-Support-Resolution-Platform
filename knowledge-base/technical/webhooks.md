# Webhooks

## Delivery and retries

Webhooks are delivered at least once. A non-2xx response is retried with
exponential backoff for up to 24 hours.

Because delivery is at-least-once, **your endpoint must be idempotent**. Use
the `event_id` field to recognise a repeat and ignore it.

## Deliveries stopping suddenly

An endpoint that fails continuously for 24 hours is automatically disabled.
Re-enable it under **Settings > Webhooks** after fixing the endpoint. Events
that occurred while it was disabled are not replayed.

## Verifying signatures

Every request carries an `X-Signature` header. Verify it against your signing
secret before trusting the payload. Requests that fail verification should be
rejected, not logged and processed.
