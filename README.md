# MoRE

*A small, honest multi-agent CLI harness for local LLMs.*

MoRE runs a **crew** of LLM agents against any OpenAI-compatible model endpoint —
your own GPU box, a local server, or a hosted API. The agents share one workspace
and one transcript, take turns by addressing each other by name, use a handful of
real, sandboxed tools, and **you** steer from the top. It's the Python standard
library only — nothing to install to run it — and it ships with an offline
stand-in so you can watch it move on a fresh clone.

But it's more than a chat loop. It does durable **work orders** that deliver files;
runs headless as a **daemon** that survives its own `kill -9`; **owns its GPU
compute** with a wallet-safe cost ledger; **remembers** its work and keeps a daily
ritual; works a **night shift** that improves its own source under a benchmark it
cannot game, and *wonders* — waking into questions no one asked; and renders itself
as one **page you can point at**. Every subsystem is an append-only event log you
can `cat`, every claim is covered by a test, and every piece runs offline (labelled
`DEMO`) until you give it a model. Jump to [a day in the realm](#a-day-in-the-realm)
for the whole arc in nine commands.

```sh
git clone https://github.com/Ari6six6/KM1.git
cd KM1
./mor-cli                 # run in place, no install
```
```
you> summarize the python files in the workspace
operator → lead: summarize the python files in the workspace
lead → worker: worker, list and read the .py files and report what each does.
worker → lead: three files: cli.py (entry point), db.py (storage), api.py (routes).
lead → operator: The workspace has three modules — a CLI entry point, a storage
                 layer, and an HTTP routes file. Want a deeper look at any one?
```

---

## Install

**You don't need to install anything.** Just run it from inside the folder
(needs Python 3.10+):

```sh
cd KM1
./mor-cli
```

Everywhere below, `mor <thing>` is shorthand for `./mor-cli <thing>` run from the
project folder. They are the same — use `./mor-cli` if you haven't installed.

<details>
<summary>Optional: a global <code>mor</code> command</summary>

If you'd rather type `mor` from anywhere, either add an alias:

```sh
echo "alias mor=\"$HOME/KM1/mor-cli\"" >> ~/.bashrc && source ~/.bashrc
```

…or install it (on modern Debian/Ubuntu, use a venv or pipx — a bare
`pip install` is blocked by the OS):

```sh
python3 -m venv .venv && . .venv/bin/activate && pip install -e .   # venv
# or:  pipx install .                                               # isolated
```
</details>

Verify (optional):

```sh
python3 -m pytest -q            # 171 tests, no model or network needed
```

---

## Deploy on a Vast.ai GPU — one command

**You rent the box** on Vast.ai (your hunt, your deal — it hands you an SSH command
like `ssh -p 24439 root@1.2.3.4`). Add a `-L` port forward and give the whole thing
to MoRE — this is the primary path:

```sh
mor gpu model qwen                                         # pick a model (optional)
mor gpu ssh -p 24439 root@1.2.3.4 -L 8080:localhost:8080   # do everything
```

That single command reaches the box (retrying while it's still booting), detects
the GPUs, **preflights** (does the model repo + exact file resolve on Hugging Face?
does the disk fit the weights? does the GPU support the quantization? — each a
three-second answer *before* any paid install), picks a VRAM/context tier, installs
vLLM (or builds llama.cpp for GGUF), launches the server **with tool-calling
enabled**, opens the SSH tunnel, runs a **canary** (one real tool-call — "up" means
*can think*, not just *lists models*), and adopts the box into the mind registry.
Then it points the harness at `http://localhost:8080/v1` for you. Confirm and go:

```sh
mor ping        # ✓ answered in 12.3s: pong
mor             # start working
```

Manage it:

```sh
mor gpu model           # list the catalog · mor gpu model <key> to pick
mor gpu status          # is the tunnel live? what's served?
mor gpu watch           # keep the tunnel alive automatically (self-healing, backoff)
mor gpu off             # drop the tunnel (leaves the server running on the box)
mor gpu down            # stop the server AND drop the tunnel
```

For an unattended box, `mor gpu watch` (or `nohup mor gpu watch &`) re-dials the
tunnel by itself the moment it drops — no more noticing it's down and typing
`reconnect`.

The model catalog lives in `mor/models.py` — edit it to add your own (repo,
served name, VRAM floor, context tiers, vLLM vs llama.cpp). The bundled rows are a
starting set; confirm a repo resolves before you lean on it.

### Bring-your-own endpoint

Already have a server running (local Ollama, a hosted API, a box you provisioned
by hand)? Skip `gpu` entirely:

```sh
mor config --base-url http://localhost:8080/v1 --model your-model
mor ping
```

> If you serve a model yourself, enable tool-calling or the crew can talk but not
> act. For vLLM: `--enable-auto-tool-choice --tool-call-parser hermes`. (`mor gpu`
> already does this for you.)
>
> **Running MoRE *on* the GPU box?** Cleanest way to let the crew use the shell
> freely — the box is disposable. `pip install -e .` on the box and
> `mor config --base-url http://localhost:8080/v1`.

### Containerized

Run the whole harness in a container so the shell is isolated by construction:

```sh
docker build -t more .
docker run --rm -it \
  -e MOR_BASE_URL=http://your-gpu-box:8080/v1 \
  -e MOR_MODEL=your-model \
  -e MOR_SHELL=host \
  -v "$PWD":/work -e MOR_WORKSPACE=/work \
  -v more-state:/root/.mor \
  more
```

---

## The crew

Three agents by default, deliberately generic:

| agent        | does                                            | web  |
|--------------|-------------------------------------------------|------|
| `lead`       | coordinates, delegates, speaks with you         | no   |
| `researcher` | gathers information, including from the web     | yes  |
| `worker`     | hands-on file and (opt-in) shell work           | no   |

**How a round works.** You give a task; it goes to the `lead`. Each agent ends
its line by naming who should speak next, and that agent goes next. Only the
`lead` speaks with you — when it turns to you, the round is done. A hard turn cap
means every round ends.

**Make it yours.** `/crew init` writes an editable `crew.json` in the project.
Change the names, roles, prompts, tools, and who may reach the web. Agents are
plain data, not fixed roles.

---

## Work orders

A chat round *talks*; a **work order** *delivers*. An order is a durable,
resumable unit of work that the crew executes through the shared transcript and
finishes with an **artifact** — a file you can read, run, or `scp`:

```sh
mor order research "the 3 best-maintained python http libraries, with sources"
mor order build    "a script that dedupes a csv by column, with a test"
mor order fetch    "every PDF linked from <page>"
mor orders                       # every order, its state, its brief
mor pull <order-id>              # print the artifact path(s), scp-ready
```

Three kinds — **research** (a sourced answer), **build** (code + a test in the
workspace), **fetch** (pull and save from the web) — differ only in how the work
is framed and which face leads; the order object is the same.

A **watch** is a recurring order — standing work the daemon runs on a schedule,
whether or not you're looking:

```sh
mor watch "that repo's issues, tell me what changed" 6h
mor watches                      # every watch, its interval, when it last ran
mor unwatch <id>
```

The daemon's scheduler fires each watch when it's due, with no client attached —
the realm working the night shift.

Each order lives under `orders/<id>/` as an **append-only event log**
(`received → planned → executing → verifying → delivered | failed`); its state is
a *projection* of those events, so a restart resumes it exactly. The delivered
`report.md` carries the crew's conclusion and the Hall that produced it. With no
model attached the flow still runs and delivers, labelled **DEMO**.

> The order is the unit of work; the shared transcript is the unit of being — the
> crew's words are the narration, the artifact is the product.

### The Gate — an order that can catch itself being wrong

`verifying` is no longer a file-size check. Each order freezes an acceptance
**rubric** at `planned` — an event on the log, never a line in the Hall, so the
crew can't read its own exam — then **scores** the artifact against it: a vector of
named sub-scores (facts present, forbidden claims absent, sources cited, files
produced, tests passing) aggregated to one scalar. On a shortfall the order loops
`verifying → executing`, carrying the failing components forward as coaching, up to
a bounded retry budget, and **delivers the best attempt** (never a regression); on
exhaustion it fails *with* the best score and the critique — a stop with a reason,
not a graveyard.

The gate only *blocks* where it has earned the right to. `mor calibrate` scores a
corpus of known-good and known-poisoned reports (`bench/fixtures/`) to measure the
critic's discrimination **D** and place the cut **θ** — Neyman–Pearson, at the
(1−α) quantile of poison, licensed only if the true-accept power holds at 1−β. Two
realm-wide knobs are the Master's to turn: **α**, the acceptable-lie rate, and
**β**, the acceptable retry-tax. With no calibration behind a kind (offline, or one
whose fixtures aren't written yet) the gate runs **advisory** — it scores and
flags, but delivers as before, so the DEMO promise holds. `mor gate` shows every
measuring stick's state.

**Build needs no model at all.** A build order is judged by an **acceptance test**
frozen at `planned` — its content recorded to the log, then *restored over whatever
the worker left* before it runs, so a crew can't weaken its own exam (the Forge's
untouchable-judge law, ported to the order via the event log). Because the verdict
is an exit code, the build gate calibrates and **arms entirely offline** — a build
that writes `return a - b` for `add` is caught and bounced on your laptop, no GPU,
no tokens.

### Headless — the daemon

A REPL is a session; a daemon is a presence. `mored` owns the realm and runs
orders **in its own process**, so the work continues whether or not you're
watching. Because an order's state is a projection of its event log, a daemon
that is killed and restarted rebuilds every order's state from the log **and
re-runs any order left mid-flight to completion** — it records a `resumed` event
so the log keeps the scar. Works in the dark, survives its own death.

```sh
mor daemon                 # run the daemon in the foreground
nohup mor daemon &         # …or headless, for the night shift
mor status                 # is it up? what's it holding?
```

It speaks a small, token-authed, loopback HTTP+SSE API (stdlib only): submit an
order, list orders, fetch one, or stream an order's Hall live as the crew works.
The token lives at `$MOR_HOME/daemon_token`.

---

## The Field — the realm owns its compute

The operator rents GPUs by the hour, and the Field owns them so he never holds a
dead box or a surprise bill:

```sh
mor up            # rent + serve a box, start the cost meter
mor field         # its state and dollars spent, to the cent
mor down          # drain, destroy, print the final bill
```

Lifecycle: **cold → renting → provisioning → serving → draining → dead**, kept as
an event log so state is a projection you can trust. It carries the facts/effects
discipline the whole project builds toward: renting is an **effect** dispatched
under an idempotency key; replay never re-fires it; on startup the Field
**reconciles** against provider ground truth. So a crash between "intent: rent"
and "fact: rented" resolves to **exactly one box, never two** — the wallet test,
and it's enforced by a test.

Two providers behind one interface: a file-backed **DEMO** provider (the default —
`mor up` runs the whole lifecycle with a simulated box, no GPU, no spend) and the
real **vast.ai** adapter (set `MOR_VAST_KEY` or `vast_api_key`). The real
provisioning bones in `mor gpu` slot in as the *provisioning* step; the Field is
the state machine, cost ledger, and reconciliation around them.

**BYO is the primary path; `mor up` is the opt-in auto-rent.** You usually rent on
the vast console yourself and paste one `mor gpu ssh` string (above); `mor up` is
there when you'd rather the harness rent for you. Either way the box joins one
**mind registry**, and when more than one mind is serving, a run asks which:

```sh
mor mind                 # the served boxes · which one is active
mor mind use 2           # route runs to box 2
mor field rate byo-… 0.40   # give a BYO box a $/hr so it joins the cost ledger
mor down byo-…           # release a BYO box (destroy it in your console)
```

---

## Memory

The realm remembers its own work. Every face's turn is seeded with the passages
most relevant to what's being discussed — drawn from **past order reports and the
project notes** (a lexical BM25 leg, stdlib only) — so it cites what it learned
last week without being told where to look. Query it yourself:

```sh
mor recall "is the north road passable"
```

It reads only the realm's own memory (reports, notes), never arbitrary workspace
files, so nothing private leaks in through the back door. Embeddings and
model-assisted extraction are a later layer; the retrieval seam is here now.

### light and dark — the day

Retrieval carries *facts*; the day's ritual carries *identity*.

```sh
mor light        # open a day — the Chant that crossed the night is posted first
# … work …
mor dark         # close it — fold the day's Hall into the Chant and the walls
```

At **dark**, the day's shared transcript is folded into one small thing that
crosses the night — the **Chant** (the realm's memory of who it was that day) — and
each face rewrites its two **walls** (inside: who I am; outside: what it makes of
the others, an earned relation). At **light** the Chant is posted and each face
wakes to *persona + walls + last Chant* — a blank slate but for what the ritual
kept. It's all a **deterministic projection of the recorded Hall**: the same day
always folds to the same Chant and walls, byte for byte. A served model may later
*voice* the Chant richer; the ground is always the projection, never invention.

---

## The night shift — the Forge and the Dreaming

The realm works the day and earns the night. Three organs in one dusk window,
each separately verifiable, in this order:

**The Benchmarks** — the judge. A hash-pinned, external, task-level suite that
publishes one number and is green before any mutant exists.

```sh
mor bench run          # score the realm · mor bench list · mor bench pin
```

**The Forge** — strength. One quarantined improvement per cycle, judged only by
the benchmark, kept only on a measured gain. Three laws, enforced by construction:

```sh
mor forge once         # a quarantined self-improvement · mor forge log
```

- **Quarantine** — the improver works in a git worktree, never the live tree; keep
  is a merge, reject discards the worktree. A kept change takes effect at restart,
  never mid-flight.
- **The untouchable judge** — `bench/` and `tests/` are *restored* from the
  pristine tree before judging, so a mutant that weakens a test is judged by the
  original. A benchmark gain won by gaming the test is neutralized and rejected.
- **External fitness** — the only fitness term is the benchmark delta. JUICE =
  Δbenchmark, and nothing self-awardable.

**The Dreaming** — wonder. At dusk the realm folds the day into a small knowledge
graph and recombines it into *questions no one asked while awake* — bridges
(what connects two islands?), negations (which of two contradictions is true?),
syntheses (are these two things the same?). The questions seed the next dawn and
aim the Forge. Curiosity aims; the benchmark decides.

```sh
mor dark               # fold the day (Chant + walls), then dream the questions
mor light              # dawn: post the Chant + the night's questions
mor report             # the morning page: work, cost, forge verdicts, questions
```

Everything here runs **DEMO/offline** with the label until a served mind is
attached; the benchmark's score is real either way.

### Point at it — the Cathedral

The realm renders itself as one **self-contained page** — no network, no
dependency, so it opens on a phone. Two windows: the **mind** (the knowledge graph
as a constellation computed in pure Python, the night's dream, the Chant, the day
in the Hall) and the **operation** (orders, the JUICE curve, burn rate).

```sh
mor cathedral            # write cathedral.html · or `mor daemon`, then GET /cathedral
```

And the pantheon is yours — `mor crew personas` writes the scripture's cast
(General · Wizard · Warrior) as an editable `crew.json`. Names are your skin; the
Hall and the rails are the bones underneath.

---

## The tools, and the rails

Each agent gets only the tools its definition lists. Every tool returns a plain
observation the agent reads on its next step.

- **`read_file`, `write_file`, `list_dir`, `search`** — sandboxed to the
  workspace. A path that escapes it is refused; long files page instead of
  truncating silently.
- **`run_shell`** — off by default. Three modes (`mor config --shell …`):
  - `off` — refused.
  - `container` *(recommended)* — runs in a disposable Docker/Podman container
    with only the workspace mounted and **no network**. If no runtime is
    running, it refuses rather than silently touching the host. Allow network
    for a build with `mor config --shell-net bridge`.
  - `host` — runs directly on the host in the workspace dir. Unsandboxed; only
    sensible when MoRE itself is already in a throwaway box/container.
- **`web_fetch`** — the crew's way onto the public web:
  - only agents marked `can_egress` (the `researcher`) get it;
  - **open by default** — it can fetch any public site with no per-domain
    permission. (Prefer a whitelist? `mor config --web gated`, then
    `mor allow <domain>`.)
  - always SSRF-guarded — public web only, never the host's loopback/LAN or a
    cloud-metadata address. This never asks you anything; it just refuses;
  - one hop — redirects are reported, not followed;
  - anything it returns is flagged **tainted**, and a round that leaned on
    outside data says so when it reports back.
- **`remember`** — appends a durable note to the project's memory, shown to the
  crew next session.
- **forged tools — the Yard.** A tool the crew writes (`run(args)`) never runs in
  the realm's process. The **Yard** runs it as a subprocess over a tiny JSON RPC,
  under CPU / memory / wall-clock limits, so a forged tool can crash, loop, or bomb
  memory and the realm reaps it with a structured error and moves on. `mor yard`.
  (Full network/filesystem jailing — `--cap-drop ALL --network internal` inside a
  body — is the container layer that slots onto this same subprocess seam when a
  runtime is present; without one the tool is out-of-process and bounded but not
  network-isolated, which the Yard states rather than pretends.)

---

## A day in the realm

The pieces fit into one arc — this is the whole thing, end to end:

```sh
mor gpu ssh -p 24439 root@1.2.3.4 -L 8080:localhost:8080   # a body: paste your box's ssh string
mor light                                                  # open the day (posts last night's Chant)
mor order research "the 3 best python http libraries, sourced"   # do real work → an artifact
mor pull <order-id>                                        # the file, scp-ready
mor watch "that repo's issues, what changed" 6h            # standing work, on a schedule
mor forge on                                               # let the night improve the realm
mor dark                                                   # close the day: fold the Chant, then dream
mor report                                                 # the morning page: work · cost · forge · questions
mor cathedral                                              # render the whole realm as one page you can point at
```

Run `mor daemon` (or `nohup mor daemon &`) and it does the night shift for you —
watches fire, orders resume, the tunnel self-heals — whether or not you're looking.

## Command reference

Run `mor` with no arguments for the interactive shell; inside it every command is
also a slash-command (`/order …`). From a terminal it's `mor <command>`. They are
the same surface.

**Work**

| command | what |
|---|---|
| `<text>` / `mor run "<task>"` | give the crew a task (one round, or one-shot then exit) |
| `mor order <kind> "<brief>"` | a work order → an artifact. kinds: `research` · `build` · `fetch` |
| `mor orders` · `mor pull <id>` | list orders and their state · print an order's artifact path(s) |
| `mor watch "<what>" <every>` | a recurring order (`90s`/`30m`/`6h`/`1d`) · `mor watches` · `mor unwatch <id>` |
| `mor recall "<query>"` | what the realm remembers from its own past work |

**The day & the night shift**

| command | what |
|---|---|
| `mor light` · `mor dark` | open a day (post the Chant) · close it (fold Chant + walls, then dream) |
| `mor report` | the morning page: orders, cost, forge verdict/JUICE, the dream's questions |
| `mor bench run\|list\|pin` | the benchmark suite — the judge the Forge must satisfy |
| `mor calibrate [kind]` | measure the Gate on the poison corpus → arm it or leave it advisory |
| `mor gate` | every measuring stick's state: armed/advisory, D · θ · power · n |
| `mor forge once\|log` | one quarantined self-improvement, judged by the benchmark |
| `mor cathedral` | render the realm as one self-contained page (also served at `/cathedral`) |

**Compute — a body for the crew**

| command | what |
|---|---|
| `mor gpu ssh <ssh…>` | provision + serve a model on your box (preflight → canary → adopt) |
| `mor gpu model\|status\|watch\|reconnect\|off\|down` | pick a model · status · self-heal the tunnel · reconnect · drop · stop |
| `mor up` · `mor down [box]` | opt-in auto-rent a box · destroy (rented) or release (BYO) |
| `mor field [rate <box> <$/hr>]` | boxes, state, cost to the cent · set a BYO box's rate |
| `mor mind [use <n\|label>]` | the mind registry — which served box a run routes to |

**Headless & tooling**

| command | what |
|---|---|
| `mor daemon` · `mor status` | run the headless daemon · is one alive, and what's it holding |
| `mor yard list\|run <name> [json]` | run a forged tool, jailed (never in the realm's process) |
| `mor crew init\|personas` · `mor agents` | write a crew.json (generic · or the pantheon) · list the crew |
| `mor config …` · `mor model` · `mor ping` | set endpoint/shell/web · show how it reaches the model · test it |
| `mor allow <domain>` · `mor deny <domain>` | open/close a domain (only when `--web gated`) |
| `mor note <text>` · `mor notes` | add / show a durable project note |
| `mor project [name]` | show, switch, or create a project · `mor help` · `mor quit` |

Environment overrides (handy for one-off runs and containers): `MOR_BASE_URL`,
`MOR_MODEL`, `MOR_API_KEY`, `MOR_SHELL`, `MOR_WORKSPACE`, `MOR_HOME`, `MOR_VAST_KEY`,
`HF_TOKEN` (gated repos), `MOR_DAEMON_URL`.

---

## Where things live

Everything is plain files under `$MOR_HOME` (default `~/.mor`) — no database, no
binary state. Every subsystem's state is an **append-only event log**, and what you
see is a projection of it, so a crash never leaves a torn realm:

```
~/.mor/
  config.json                     # endpoint + settings
  daemon_token                    # the daemon's shared secret (0600)
  current_project
  projects/<name>/
    workspace/                    # the shared workspace (unless -C / MOR_WORKSPACE)
    sessions/<timestamp>.jsonl    # full transcript of each session (the Hall)
    notes.md                      # durable project memory
    allow.json                    # the web allowlist
    crew.json                     # (optional) your custom crew / persona pack
    orders/<id>/                  # one work order: events.jsonl · hall.jsonl · report.md
    watches.json                  # recurring orders
    field/
      events.jsonl                # compute lifecycle: intents / effects / facts, box registry
      fake_provider.json          # the DEMO provider's simulated boxes
    mind.json                     # the active mind (which serving box a run routes to)
    realm/
      events.jsonl                # the night's ledger: bench scores, forge verdicts, dream questions
      day.json · last_chant.md · walls.json · chants/   # the day ritual (Chant + walls)
      dream.json                  # the night's questions, seeded for dawn
    forged/<name>.py              # forged tools (run jailed by the Yard)
    cathedral.html                # the rendered "point at it" page
bench/                            # (in the repo) the benchmark tasks + MANIFEST.sha256 — the judge
```

Inspect it, edit it, delete it — it's just files. `cat` any `events.jsonl` to read
exactly what the realm did and why.

---

## A note on what this is

MoRE began as a much larger, heavily-themed project ("Masters of the Realm") — an
organism described in nine books that the runtime did not actually contain. It was
amputated to the part that was truly a working harness, and then the organism was
grown back on those bones, one law-abiding stone at a time: a streaming,
cancellable mind; work as durable, resumable **orders**; a headless **daemon** that
survives its own death; a **Field** that owns its compute with a wallet-safe
ledger; **memory** and the day's ritual (the Chant, the walls); the **watch** that
never sleeps; a hash-pinned **benchmark** judge; a **Forge** that improves the
source under quarantine, judged only by a benchmark it cannot reach (JUICE =
Δbenchmark); a **Dreaming** that wakes the realm into its own questions; a **Yard**
that runs forged code jailed, never in-process; and a **Cathedral** that renders
the whole thing as one page you can point at.

The difference between this and the books is that everything here is enforced by
construction and covered by a test — the elaborate layers describe something that
exists. The full history, and every round of the argument that shaped it, is in
git; the earliest design lives on the `claude/setup-from-scratch` branch.

*The day is for answers. The night is for questions. Where there was data, there
will be data.* &#9651;
