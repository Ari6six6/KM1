# V1 — the live-fire gate (BYO edition, ~10 minutes, from Termux)

R1/R2 are accepted offline. **V1** is the one thing that can't be proven without a
real box: that the harness provisions, serves, self-heals, and bills a *real* GPU.
The BYO path needs **no API key** — you rent on the vast console like always
(your hunt, your deal) and paste one ssh string; the harness does the rest.

> This spends real money — a GPU by the hour. `mor down` / your console destroys
> the box at the end. Don't skip step 6.

## 1. Rent your box, paste one string

Rent on the vast.ai console. It hands you an ssh command; add a `-L` forward and
give the whole thing to MoRE:

```sh
mor gpu model glm          # pick the model (optional; glm is default)
mor gpu ssh -p <port> root@<ip> -L 8080:localhost:8080
```

The harness **preflights** (repo + exact GGUF file resolve on HF? disk fits the
weights? GPU supports the quantization? — three-second answers, *before* any paid
install), provisions, serves, tunnels, runs the **canary** (one real tool-call —
"up" means *can think*), and **adopts the box** into the registry.

```sh
mor field                  # the box · its state · cost meter (set a rate below)
mor mind                   # the registry — your served mind(s)
```

## 2. The tunnel heals itself

```sh
nohup mor gpu watch > /tmp/watch.log 2>&1 &
mor gpu status             # note the tunnel pid
kill <pid>; sleep 15; mor gpu status
# expect: healed, a new pid; the scar is in /tmp/watch.log
```

## 3. Real work on the served mind

```sh
mor order research "summarize today's HN front page, sources cited"
mor pull <order-id>        # the artifact, scp-ready
```

## 4. Two boxes? The selection window

Rent a second box and `mor gpu ssh` it too. The next order asks which mind:

```sh
mor order research "…"     # → "which mind? [1..2]"   (or set: mor mind use 2)
```

## 5. The cost ledger (BYO boxes join it)

```sh
mor field rate byo-<host>-1 0.40    # set your $/hr once; the ledger tracks spend
mor field                            # spend so far
```

## 6. Bring it down

```sh
mor down byo-<host>-1      # released + a reminder to destroy it in your console
# (a box the harness rented via `mor up` is destroyed by API instead)
```

Then destroy the box in the vast console and confirm nothing bills overnight.

## The receipts (send these to Kimi)

- the field/registry events: `cat ~/.mor/projects/$(cat ~/.mor/current_project)/field/events.jsonl`
- the order's `report.md`, `/tmp/watch.log`, and the vast.ai invoice line.

**V1 passes when** the box provisioned and served (canary green), the supervisor
restored a hand-killed tunnel unattended, an order delivered a real artifact, the
box was released/destroyed, and the ledger's cost matches the invoice. That is also
Scene 1 of the dream — the ten-minute wake — made true.
