"""RabbitMQ user-log publisher (Phase 4, vendored into the Main Backend).

Publishes logout-aside, asynchronous user events to the ``user_logs`` exchange
consumed by the mongo-log-service worker. The publisher contract is strict:

- ``publish_user_log`` NEVER raises; a down broker fails fast and returns a
  ``PublishResult`` with ``success=False`` so business operations continue.
- Event envelopes (``UserLogEvent``) reject sensitive data before publish.

See ``app/services/user_events.py`` for the high-level helpers that business
services should call.
"""