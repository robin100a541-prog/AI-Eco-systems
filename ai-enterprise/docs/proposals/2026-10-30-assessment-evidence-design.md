# H5: proposed evidence boundary for readiness

**Engineering outline, not an approved decision or implemented fix.** H5 remains open.

The caller-provided `ready` boolean in AssessmentStore is not proof that any simulation ran. Merely
requiring a larger JSON object, a producer-name string, or a publicly computable checksum would leave
the same bypass. A fix must establish where the evidence comes from, not just its shape.

1. Snapshot all relevant inputs: initiative, platform, risk/readiness rules, tax/assessment settings,
   observed-demand sources, agent/market versions and seeds. Hash the complete snapshot.
2. The trusted runner must derive per-run measurements from its actual SQLite simulation database,
   after verifying the completed day range, currency separation, ledger and audit chain. Preserve
   immutable run evidence before temporary run databases are deleted.
3. Store run identifiers, scenario kind, input hash, covered dates, measurement inputs and outputs,
   plus audit/ledger evidence references. Attach an assessment only to those persisted runs.
4. Derive readiness from evidence: required normal, pessimistic and zero-sales runs, minimum run/day
   counts and applicable profitability/stop conditions. Public record APIs must not promote arbitrary
   `ready=True` data. Founder approval is separate from evidence validation and cannot replace it.
5. Mark existing assessments without sufficient evidence as unverified; preserve history but require
   re-evaluation. Changing any relevant input must invalidate approval. The SIM-only scenario exception
   must never authorize a production assessment.
6. Test actual positive/negative runs, missing/forged IDs, wrong snapshots, incomplete runs, changed
   configuration, stale approved records and restart behavior. Fixtures may mock the trusted runner,
   but a fake caller JSON flag must remain rejected by the production API.

The Python process and database owner are presently trusted: actors with arbitrary SQL/Python access
can also rewrite guards or impersonate founders. Agent-facing tools must not expose that authority.
If adversarial Python execution is part of the intended threat model, the runner/evidence writer needs
process isolation and authenticated capabilities as a separate architectural change.

This should be a focused, reviewed follow-up, not a cosmetic flag-validation change. It does not
change any risk policy, approve a pilot or claim to close H5.
