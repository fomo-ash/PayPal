"""Jobs (Phase 2)
POST /jobs                       create draft (spec, examples, groups, min_score, amount)
POST /jobs/{id}/suite            upload hidden tests + reference solution (+ optional generator)
POST /jobs/{id}/validate         run reference + AI spec check → AWAITING_FUNDS or INVALID
POST /jobs/{id}/fund             create PayPal order (intent AUTHORIZE) → returns order id for the JS SDK
POST /jobs/{id}/fund/confirm     authorize approved order → FUNDED, seal suite hash → OPEN
GET  /jobs                       open jobs (public view: spec, examples, weights, suite hash)
GET  /jobs/{id}
POST /jobs/{id}/claim            worker accepts (Log in with PayPal required)
"""
