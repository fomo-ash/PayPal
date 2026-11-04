"""Log in with PayPal (OpenID Connect) (Phase 4).

Flow: redirect to PayPal's authorize URL with scope "openid email https://uri.paypal.com/services/paypalattributes"
→ callback with ?code= → POST /v1/oauth2/token (grant_type=authorization_code)
→ GET /v1/identity/oauth2/userinfo?schema=paypalv1.1 → payer_id, email, verified status.

payer_id becomes users.paypal_payer_id and is used as the Payouts receiver (recipient_type
PAYPAL_ID), so payouts always land in a real account (no "unclaimed" money).
One graded submission per payer_id per job stops fake-account probing (loophole W8).
"""
