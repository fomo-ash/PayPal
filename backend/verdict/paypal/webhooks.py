"""Webhook handling (Phase 2).

1. Verify every event with POST /v1/notifications/verify-webhook-signature (client.verify_webhook_signature).
2. Store the raw event in paypal_events (dedupe on event id). PayPal may deliver more than once.
3. Map the event to a state/ledger update. Webhooks CONFIRM what the money worker did; they
   never trigger money movement themselves.
"""

SUBSCRIBED_EVENTS = [
    "CHECKOUT.ORDER.APPROVED",
    "PAYMENT.AUTHORIZATION.CREATED",
    "PAYMENT.AUTHORIZATION.VOIDED",
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.DENIED",
    "PAYMENT.CAPTURE.REFUNDED",
    "PAYMENT.PAYOUTSBATCH.SUCCESS",
    "PAYMENT.PAYOUTSBATCH.DENIED",
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
    "PAYMENT.PAYOUTS-ITEM.FAILED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED",
    "CUSTOMER.DISPUTE.CREATED",
    "CUSTOMER.DISPUTE.UPDATED",
    "CUSTOMER.DISPUTE.RESOLVED",
]
