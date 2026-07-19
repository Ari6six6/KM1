# MoRE

*A small, honest multi-agent CLI harness for local LLMs.*

MoRE runs a **crew** of LLM agents against any OpenAI-compatible model endpoint —
your own GPU box, a local server, or a hosted API. The agents share one workspace
and one transcript, take turns by addressing each other by name, use a handful of
real, sandboxed tools, and **you** steer from the top. It's the Python standard
library only — nothing to install to run it — and it ships with an offline
stand-in so you can watch it move on a fresh clone.

```sh
git clone https://github.com/Ari6six6/MoRE.git
cd MoRE
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
cd MoRE
./mor-cli
```

Everywhere below, `mor <thing>` is shorthand for `./mor-cli <thing>` run from the
`MoRE` folder. They are the same — use `./mor-cli` if you haven't installed.

<details>
<summary>Optional: a global <code>mor</code> command</summary>

If you'd rather type `mor` from anywhere, either add an alias:

```sh
echo "alias mor=\"$HOME/MoRE/mor-cli\"" >> ~/.bashrc && source ~/.bashrc
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
python3 -m pytest -q            # 50 tests, no model or network needed
```

---

## Deploy on a Vast.ai GPU — one command

Rent a box on Vast.ai (it hands you an SSH command like
`ssh -p 24439 root@1.2.3.4`). Add a `-L` port forward to it and give the whole
thing to MoRE:

```sh
mor gpu model qwen                                         # pick a model (optional)
mor gpu ssh -p 24439 root@1.2.3.4 -L 8080:localhost:8080   # do everything
```

That single command reaches the box (retrying while it's still booting), detects
the GPUs, picks a VRAM/context tier, installs vLLM (or builds llama.cpp for GGUF
models), launches the server **with tool-calling enabled**, opens the SSH tunnel,
and waits — with a download bar — until the model answers. Then it points the
harness at `http://localhost:8080/v1` for you. Confirm and go:

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

---

## Commands

Run `mor` with no arguments for the shell; inside it:

```
<text>            give the crew a task
/order <kind> <brief>   run a work order (kind: research) → an artifact
/orders           list orders, their state, and their artifacts
/pull <id>        print an order's artifact paths (scp-ready)
/agents           list the crew and who can reach the web
/allow <domain>   open web access for a domain  (/allow with no arg shows the list)
/deny <domain>    close a domain again
/ping             check the model endpoint answers
/gpu ssh <ssh…>   provision + serve a model on a GPU box (see above)
/gpu model|status|off|down   pick a model · check · drop tunnel · stop the box
/note <text>      add a durable project note   ·  /notes  show them
/model            show how MoRE reaches the model
/project [name]   show, switch, or create a project
/crew init        write an editable crew.json
/help  ·  /quit
```

From the shell (scriptable):

```sh
mor run "audit the workspace for secrets and report"   # one task, then exit
mor order research "compare 3 http libraries, sources"  # a work order → an artifact
mor pull <order-id>                                     # the artifact path, scp-ready
mor -C ~/code/my-repo run "find the failing test"      # work on a real directory
mor config --base-url URL --model M --shell container   # configure
mor ping                                                # test the endpoint
mor allow docs.python.org                               # open one domain
```

Environment overrides (handy for one-off runs and containers): `MOR_BASE_URL`,
`MOR_MODEL`, `MOR_API_KEY`, `MOR_SHELL`, `MOR_WORKSPACE`, `MOR_HOME`.

---

## Where things live

Everything is plain files under `$MOR_HOME` (default `~/.mor`):

```
~/.mor/
  config.json                     # endpoint + settings
  current_project
  projects/<name>/
    workspace/                    # the shared workspace (unless -C / MOR_WORKSPACE)
    sessions/<timestamp>.jsonl    # full transcript of each session
    notes.md                      # durable project memory
    allow.json                    # the web allowlist
    crew.json                     # (optional) your custom crew
```

Inspect it, edit it, delete it — it's just files.

---

## A note on what this replaced

MoRE began as a much larger, heavily-themed project ("Masters of the Realm").
This is a deliberate reduction to the part that was actually a working harness: a
model client, a think→act tool loop, sandboxed tools with a real egress guard,
name-based turn-taking, and persistent memory. The elaborate layers on top —
self-modifying source, a knowledge graph, the nightly "dream," the rendered
"cathedral," and the rest — were removed. Nothing is lost: the full history is in
git, and the earlier design lives on the `claude/setup-from-scratch` branch. This
is the harness, rebuilt clean.
