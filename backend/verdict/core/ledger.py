"""Double-entry ledger (Phase 2).

Accounts: buyer_hold, platform_clearing, worker_payable, platform_fee, released.
Every PayPal event posts a balanced set of entries (Σ debit == Σ credit per job event):

  authorization created  $100   Dr buyer_hold          Cr platform_clearing (memo, off-balance)
  capture $81.50                Dr platform_clearing   Cr worker_payable 77.42, platform_fee 4.08
  remainder released $18.50     Dr platform_clearing   Cr released
  payout $77.42                 Dr worker_payable      Cr platform_clearing (cash out)
  void $100                     Dr platform_clearing   Cr released

Invariant tested in CI: for every job in a terminal state, every account nets to zero except
platform_fee (revenue) and released (returned to buyer).
"""
