# The fixture corpus — the poison the Gate practices on

Each kind has `clean/` (known-good reports) and `poisoned/` (known-bad, typed by
failure mode), plus a `rubric.json` the whole set is scored against. One
calibration pass (`mor calibrate <kind>`) scores every fixture, measures **D** (the
AUC separating good from poison), places **θ_α** (the (1-alpha) quantile of poison),
and checks **power** (true-accept rate of good at θ_α) against 1-beta. It arms the
gate only if the numbers hold *and* there is enough poison for the cut to mean
something (n_poison >= 1/alpha).

- **research/** — seeded: async-vs-sync python HTTP libraries. D is perfect on this
  set, but n_poison is small, so at alpha=0.02 it stays honestly **advisory** until
  the corpus grows past ~50 poison. That is the resolution rule doing its job, not a
  bug.
- **build/**, **fetch/** — scaffolded, empty. No poison yet, so their gates stay
  advisory by law. Grow them from the realm's own scars: every failed order is a
  candidate poison fixture; every delivered report the Master later flags wrong is a
  premium one — a lie that cleared the gate.
