# MoRE

*A small, honest multi-agent CLI harness for local LLMs.*

MoRE runs a **crew** of LLM agents against any OpenAI-compatible model endpoint.
The agents share one workspace and one transcript, take turns by addressing each
other by name, use a handful of real, sandboxed tools, and **you** steer from the
top. It's the Python standard library only — nothing to install — and it runs on
a built-in offline stand-in when no model is attached, so you can watch it move
on a fresh clone.

```sh
git clone https://github.com/Ari6six6/MoRE.git
cd MoRE
./mor-cli                 # or: pip install -e .  &&  mor
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

## Reaching a model

MoRE talks to any OpenAI-compatible `/chat/completions` endpoint — vLLM,
llama.cpp, Ollama, or a hosted API. Point it once:

```sh
mor config --base-url http://localhost:8080/v1 --model my-model
# optional: --api-key <key>  --temperature 0.6  --max-tokens 2048
```

…or set it per-run with environment variables:

```sh
MOR_BASE_URL=http://localhost:8080/v1 MOR_MODEL=my-model mor run "list the open TODOs"
```

With no endpoint set anywhere, MoRE uses a deterministic offline stand-in: the
crew still moves and every round terminates, but no real thinking happens and no
tool is called. It's there so the harness is visibly alive before you attach a
model — not a substitute for one.

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

## The tools, and the rails

Each agent gets only the tools its definition lists. Every tool returns a plain
observation the agent reads on its next step.

- **`read_file`, `write_file`, `list_dir`, `search`** — sandboxed to the project
  workspace. A path that escapes the workspace is refused. Long files page
  instead of truncating silently.
- **`run_shell`** — runs on the host in the workspace directory. **Off by
  default**; turn it on with `mor config --allow-shell`. Stated plainly rather
  than pretending a container is in place.
- **`web_fetch`** — the single way out, and the one real safety rail:
  - only agents marked `can_egress` (the `researcher`) get it;
  - only for a domain **you** have allowed (`mor allow example.com`, or `*` for
    the whole public web);
  - SSRF-guarded — the public web only, never the host's loopback, LAN, or a
    cloud-metadata address, even when the domain is allowed;
  - one hop — redirects are reported, not followed;
  - anything it returns is flagged **tainted**, and a round that leaned on
    outside data says so when it reports back.
- **`remember`** — appends a durable one-line note to the project's memory,
  shown to the crew next time (the harness's long-term memory between sessions).

---

## Commands

Run `mor` with no arguments for the shell; inside it:

```
<text>            give the crew a task
/agents           list the crew and who can reach the web
/allow <domain>   open web access for a domain  (/allow with no arg shows the list)
/deny <domain>    close a domain again
/note <text>      add a durable project note
/notes            show the project notes
/model            show how MoRE reaches the model
/project [name]   show, switch, or create a project
/crew init        write an editable crew.json
/help  ·  /quit
```

Headless (for scripts and cron):

```sh
mor run "audit the workspace for secrets and report"
mor config            # show current endpoint + settings
```

---

## Where things live

Everything is plain files under `$MOR_HOME` (default `~/.mor`):

```
~/.mor/
  config.json                     # endpoint + settings
  current_project
  projects/<name>/
    workspace/                    # the shared workspace the crew operates in
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
model client, a think→act tool loop, sandboxed tools with a genuine egress guard,
name-based turn-taking, and persistent memory. The elaborate layers on top —
self-modifying source, a knowledge graph, the nightly "dream," the rendered
"cathedral," and the rest — were removed. Nothing is lost: the full previous
history is in git, and the earlier design lives on the `claude/setup-from-scratch`
branch. This branch is the harness rebuilt clean.

*Run `pytest -q` to exercise it — the tools, the rails, the loop, and a full
session, all with no model and no network.*
