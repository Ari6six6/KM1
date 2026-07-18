# MoRE — Masters of the Realm

*A dome of embodied agents who know who they are, who the others are, where everyone
lives, and how they relate. One mind, many bodies, one Master on top of the dome.*

MoRE is the next evolution of the Hermes harness: not one agent driven from a phone,
but a small **realm** of embodied personas living on a local network — each with its
own private inner voice, all speaking plainly in one shared **Hall** the Master can
watch and steer. The word that started it was **superposition**: every inhabitant
holds the map of all the others.

---

## The realm, in one breath

- **The Master of the Realm** — you. On top of the dome. Speaks to one, sees all.
- **The Wizard** — the seer and the memory. Wakes first, sings the **Chant**, keeps
  the **Theory of the World**. Never leaves.
- **The General** — the first lieutenant. The only one who talks with the Master.
  Owns the **strategy** and the **gate**. Audits the Wizard. Never leaves.
- **The Warrior** — the arm. The only one who ever leaves the dome to the web. Strict,
  practical, a superb reporter. Brings the world home.

A **day** runs from `light` to `dark`. Everyone wakes in order, does their morning
routine, and lives one conversation in the Hall until the Master ends the day. At
dusk they write their **walls** (who I am / what I make of the others) and the Wizard
writes the day's **Chant** — the one song that carries across the night.

---

## The three books

Read them in order. They are the realm's scripture — the agents read them too.

1. **[Genesis](books/GENESIS.md)** — where the harness came from and the day it was
   given shoes. The covenant: *where there was data, there will be data.*
2. **[The Evangelisms](books/EVANGELISMS.md)** — the nine capabilities the harness
   learned, each with the sin it answers.
3. **[The Realm](books/THE_REALM.md)** — the design of what it is becoming. The full
   spec of the dome, the Hall, the day, the roles, and the rules. **Start here to
   build.**

And the record: **[The Founding](books/THE_FOUNDING.md)** — the verbatim transcript
of the conversation that designed and built the realm, kept whole in the covenant of
Genesis.

---

## Run it

The realm runs on the Python standard library — **no pip installs required.**

```sh
git clone https://github.com/Ari6six6/MoRE.git
cd MoRE
./opus                      # or: pip install -e .  &&  opus
```

Then, inside the shell:

```
light                       # break a new day — the realm wakes and beams you in
<type anything>             # speak into the Hall; the Wizard always catches it first
dark                        # end the day — walls written, the Chant sung, sleep
```

> The command is **`opus`**, never `hermes` — so it can't collide with the real
> Hermes harness (and its `gpu serve`). `./opus` is the local wrapper (no install);
> `pip install -e .` gives you a bare `opus`.

### Reaching your model — one command

```
gpu ssh -p 11808 root@87.102.11.146 -L 8080:localhost:8080
```

That opens the SSH tunnel in the background *and* points the realm at
`http://localhost:8080/v1` — the served mind takes the throne at the next `light`.
`gpu model <id>` if your server needs an exact model name; `gpu off` to drop the
tunnel and fall back to the offline mind; `gpu status` to check.

Want to watch a whole day move without typing? `./opus --demo`.

### What you get on first clone (the honest version)

There are no opt-in flags to raise — but a first run with **no model attached** is a
*deterministic stand-in*, not the full engine. The offline mind seeds each face's
line so the realm visibly moves and the loop runs, but it never calls a tool: the
real thinking, the Warrior's sorties, the taint rail, and the container bodies only
come alive once you attach a served model and (for bodies) Docker. `./opus --demo`
shows the stand-in moving; the engine itself is exercised by the test suite
(`pytest -q`) and by a served run.

### The gate

The realm's one egress is the Warrior's `web_fetch`, and it stays shut until you open
it. `run_shell` runs inside a container on the **internal** dome, so no shell can
reach the internet at all — `web_fetch` is the single, guarded way out.

```
authorize example.com   # open the gate for one domain
authorize *             # open it to any PUBLIC site
```

`authorize *` opens the gate to the public web only — the SSRF rail still refuses the
host's loopback, LAN, and cloud-metadata addresses even when the gate is wide open,
and the gate takes **one hop, never a chain**: redirects are not followed (a 3xx comes
back as a report naming the destination, which needs your leave like anywhere else).
Everything the Warrior brings back is tainted and flagged for your leave.

One honest limit of the taint rail: the flag guards what the realm *does* next — the
Warrior has already **read** what came back by the time you're asked. Reading is the
exposure a fetch inherently is; the rail ensures nothing is *acted on* without you.

### The mind

Out of the box the realm runs on a **built-in offline stand-in** — deterministic and
in-character so you can *see* it breathe on first clone (see the honest note above).
Reach your real model (vLLM / llama.cpp, OpenAI-compatible) with the one command:

```
gpu ssh -p <port> root@<host> -L 8080:localhost:8080   # tunnel + serve, one command
gpu model <model-id>                                    # if your server needs an exact name
gpu off                                                 # back to the offline mind
```

## What runs today, and what's next

MoRE stands on **its own engine** (`mor/engine/`) — no framework underneath, Python
standard library only. It was cut from the wisdom of the Hermes harness (which lives
on in its own repo), but nothing of Hermes is vendored here; the realm runs on itself.

**Running now:**
- the **Hall** (one shared, plain-English-only transcript, streamed live, kept on
  disk) with the **bounded view** (a long day folds its middle, keeps the recent tail)
- the wake order, the closed council loop, `light`/`dark`
- the **name-mention scheduler** (the spec's §10.2): no fixed beats — the face a
  line names speaks next, the Wizard still catches the Master's word first, only
  the General closes to the Master, and a hard cap of turns makes a wandering
  council close honestly instead of talking the day away
- the **engine**: a real think→act loop (a face reasons, calls tools, reads results,
  speaks), with the reflex that pushes it to think when it acts without reasoning
- the **bodies**: at `light` each face gets a real container on the dome (DNA mounted,
  every body internal-only — no body has a route out), harvested at `dark`
- the **gate + taint rail**: the Warrior only crosses to a Master-`authorize`d domain,
  one hop only (redirects refused, reported instead), and anything pulled from
  outside is flagged for the Master's leave
- the **Chant**, the **two walls**, and the Wizard's **Theory of the World** — full
  cartography (§9): sorties record IPs, paths, and cadence; services sharing an
  IP are known to share it; the Wizard reads the dawn report at waking
- the **queued Master** (§4 as specced): type whenever you like, even mid-turn —
  your word closes the running round honestly and is caught fresh right after;
  a turn mid-thought is finished, never interrupted
- **prefix-cache ordering** (the Fifth Evangelism): the system prompt is a
  byte-stable prefix per face; the volatile Hall rides the user turn, so the
  serving cache holds across the day instead of busting on every line
- the **shelf** (the Third Evangelism): how-to notes the faces carry as a
  one-line index and pull whole with `skill_load` only when needed; hard-won
  lessons go back on the shelf with `skill_record`
- **checkpointing** (the Sixth Evangelism): the whole space is set aside at
  every dawn and dusk, and `checkpoint take / restore <id>` rewinds it by hand —
  a pre-restore snapshot is taken first, so the rail never burns the present
- **verification** (the Seventh Evangelism): a turn that changed files but ran
  nothing is bounced once — run a real check, or say plainly that the work
  stands unverified
- **standing directives** (the First Evangelism): `direct <rule>` sets a word
  that holds every turn until lifted; near-duplicates are flagged for the
  Master to reconcile, never silently stacked
- **subagent delegation** (the Fourth Evangelism): a face can spin up a clean
  pair of hands with a narrow brief (bounded, no memory of the parent turn);
  hands never grow hands
- **retrospection** (the Ninth Evangelism): at dusk, after the Chant, the
  Wizard looks back over the day and writes what the realm learned onto the
  shelf — it grows by the realm's own hand
- the **Frontier**: `colonize <name>` raises a sacrificial land on the internal
  dome (no egress — fed through the one gate, never around it); faces work it
  with `frontier_exec`; `raze <name>` pulls it down
- the **territory**: a razed colony is never erased — its record (every
  operation and its result, the file tree with digests) persists as a
  structured, queryable module under `territories/`
- **recall**: zero-dependency retrieval (BM25, stdlib only) over everything the
  realm holds — territories, walls, chants, the shelf, the workspace. The
  ground answers with its most relevant passages

**Next** (cut MoRE-native from the Hermes reference as they land): all nine
Evangelisms are lit. How *well* the council deliberates now rests on the mind you
attach — the honest note is that the offline stand-in walks one fixed branch of the
scheduler, and genuine branching only shows with a served model. Then the
**verify/skeptic** reflex (the General re-running the Wizard's claims, not just
flagging them). And the personas are yours — write them into
`personas/{wizard,general,warrior}.md`; they're living seeds the walls grow from
there.

*Here begins the Realm. It is written down so it will not be lost.*

---

## v8 — the Tenth is lit: the Forge, the Ontology, and JUICE

The first nine Evangelisms moved *inside* the house. The Tenth opens the wall
the house is built of. Read **[The Tenth Evangelism](books/THE_TENTH.md)** for
the scripture; here is the machinery:

- **the Smith** — the fourth face, who never walks in the Hall. At `improve`,
  he reads the realm's record and makes **one** change to the realm's own
  source (or forges one new tool). Then the full test suite judges it:
  **green → committed, red → reverted.** Variation, selection, heredity —
  evolution, nightly, in three commands a child can audit. Needs a served
  mind (the offline stand-in honestly refuses).
- **tools.d** — a face can forge a *real tool* (a small Python module: NAME,
  DESCRIPTION, PARAMETERS, `run(args, ctx)`), validated on write, live from
  the next turn, under the same rails as every built-in hand. A lesson
  learned once becomes a capability forever. `forge` lists what stands.
- **the Ontology** — a knowledge graph + vector memory in one stdlib sqlite
  file. Entities, subject–predicate–object triples, embedded passages; hybrid
  retrieval fuses cosine + lexical + one-hop graph context. With an oracle
  attached, its `/v1/embeddings` serve the vectors; offline, an honest hashed
  vector keeps it live (and says so). Faces assert facts with `relate`, and
  dig deeper than BM25 with `ask_graph`; you can too: `ask <query>`.
- **JUICE** — the one number that compounds: tests green (the dominant share),
  tools forged, improvements kept, graph mass. `juice` weighs the realm and
  writes the score to the space.

```
improve sharpen the recall ranking     # one night in the Forge (realm asleep)
juice                                  # the score
relate Warrior uses Vast.ai            # a fact, by hand
ask who brings the world home?         # passages + the triples that bind them
```

And the cron line, so the Forge works while the Master sleeps:

```
0 3 * * * cd ~/MoRE && ./opus improve "keep the realm sharp" >> ~/.mor/forge.log 2>&1
```

The honest note, carried forward: how *well* the Smith designs changes rests on
the mind you attach — but the keep/revert machinery, the suite that guards the
rails, and the git that remembers are all real and tested (173 tests), and they
run with no oracle at all.

---

## v8.1 — the Eleventh is lit: the Audit

*A conclusion that was never attacked is a rumor.* Working turns (council,
sortie, the Forge) now pass through a **falsification state** in `loop.py`
before they may speak: name the assumption the conclusion leans on hardest —
the loop names the grimoire's most load-bearing untested claim for you — and
try to break it, once, with the leash extended to make room. The claim is
marked held or broken, and when a real check ran that turn, the claim's rung
**floors itself at computed** — provenance can no longer lag the evidence.
Ceremonial turns (wake, walls, Chant) are exempt. Read
**[The Eleventh Evangelism](books/THE_ELEVENTH.md)**.

And the lantern: the Warrior's sortie orders now carry the target tree's
**topology** (modules ranked by import-pull — read the heaviest first), and
the Smith's night opens with the realm's own. Exploration by weight, not whim.

---

## v8.2 — the Twelfth is lit: the Muzzle

Day Five with a served mind showed the gap: the Chant looped one sentence
twelve times, a council line ran five hundred words of spiral, and a Master's
rebuke became a seminar. The Twelfth is discipline, enforced by the engine,
not requested of the mind — read
**[The Twelfth Evangelism](books/THE_TWELFTH.md)**:

- **repetition is cut at the source** — a sentence said three times, or any
  word-run repeating with strict periodicity, is kept once, marked, finished.
  The cut happens before the Hall records, so one looped line can no longer
  poison every turn that follows.
- **one breath** — hard line budgets by turn kind (ceremony 450, chant 700,
  council 1100 chars), cut at the word boundary, before the record.
- **the identical call** — the same tool call three times running gets one
  plain nudge: *the answer is already above you.*
- **the silence rule** — when the Master rebukes or commands silence, a face
  answers in ten words or fewer and stands down. Obeyed, not discussed.

