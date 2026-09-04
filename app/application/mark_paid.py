"""Compatibility alias — payment recording lives in record_payment."""

from app.application.record_payment import record_payment

__all__ = ["record_payment"]
