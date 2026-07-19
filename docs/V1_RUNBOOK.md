# V1 — the live-fire gate (10 minutes, from Termux)

R1 is accepted offline. **V1** is the one thing that can't be proven without a real
vast.ai account: that the Field rents, serves, self-heals, and bills a *real* box.
Run this on the box (or your phone over SSH) with your key in hand; keep the
receipts.

> This spends real money — a GPU by the hour. `mor down` destroys the box at the
> end. Don't skip step 4.

## 0. Point MoRE at your key

```sh
export MOR_VAST_KEY=<your-vast-api-key>
# or persist it:  mor config  then set  vast_api_key  in ~/.mor/config.json
```

## 1. The ten-minute wake

```sh
mor up
mor field          # expect: state serving · mode vast · a real $/hr rate
```

`mor up` rents a box, provisions it (the `gpu.py` bones), serves the model, and
starts the cost meter. If provisioning needs the SSH hand-off, follow with
`mor gpu ssh <the ssh line vast gave you> -L 8080:localhost:8080` and then
`mor gpu watch` (next step).

## 2. The tunnel heals itself

In one shell:

```sh
mor gpu watch      # or:  nohup mor gpu watch &
```

In another, kill the tunnel by hand and watch it come back with **no human input**:

```sh
pkill -f "ssh -N"           # or: kill <the tunnel pid from ~/.mor/gpu.json>
# within a few seconds `mor gpu watch` logs: tunnel down → redialing → tunnel restored
mor ping                    # answers again
```

## 3. Bring it down, to the cent

```sh
mor down           # drains, destroys the box, prints the final bill
```

## 4. The receipts (send these to Kimi)

```sh
cat ~/.mor/projects/$(cat ~/.mor/current_project)/field/events.jsonl
```

- the **field `events.jsonl`** — intents, facts (with the real instance id),
  serving, destroy, and the bill;
- the **vast.ai invoice** for the session.

**V1 passes when** the box rented and served, the supervisor restored a
hand-killed tunnel unattended, the box was destroyed, and **the ledger bill
matches the vast.ai invoice to the cent**. That is also Scene 1 of the dream —
the ten-minute wake — made true.

## If something sticks

- `mor field` stuck at `renting`/`provisioning` after a crash → just run `mor up`
  again; it reconciles against provider ground truth and **adopts** the box rather
  than renting a second (the wallet test, live).
- Box won't serve → `mor gpu status`, `mor gpu reconnect`, or re-run `mor gpu ssh …`.
- Always finish with `mor down` (and confirm on the vast.ai console) so nothing
  bills overnight by accident.
