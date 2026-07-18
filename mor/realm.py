"""The day — light to dark — and the scheduler that runs it.

`light` opens a day: the last Chant is posted first, then Wizard, General, and
Warrior wake in that order (forced by the single shared mind — they queue at the
one oracle), each runs its waking, and the General greets the Master. From then
the Master's word drives a closed loop through the Hall until he says `dark`,
when each writes its walls, the Wizard sings the day's Chant, and the loop closes.
"""

from __future__ import annotations

from mor.agents import ROLES, line
from mor.hall import Hall
from mor.engine import Dome, make_backend, hall_view
from mor.scheduler import resolve_addressee
from mor import checkpoint, grimoire, ui

# The council's leash: how many spoken turns one word of the Master may run
# before the General is made to close honestly (bring where things stand to the
# Master) rather than let the council talk the day away.
_MAX_COUNCIL_TURNS = 10


class Realm:
    def __init__(self, space, *, echo: bool = True, pending_master=None):
        self.space = space
        self.echo = echo
        self.backend, self.mode = make_backend()
        # §4: the Master's word is always the next turn. `pending_master` is a
        # callable the shell wires to its input queue; when it reports the
        # Master has spoken mid-round, the council closes honestly and his word
        # is caught fresh — a turn mid-thought is never interrupted, it is
        # finished and then answered.
        self.pending_master = pending_master or (lambda: False)
        self.dome = None
        self._tainted = []
        self._grimoire_touched = []  # (subject, id) claims logged this day
        self.day = None
        self.hall = None
        self.awake = False

    def _view(self) -> str:
        """The bounded Hall a face carries into its turn (folds a long day)."""
        return hall_view(self.hall, self.backend)

    # -- dawn ------------------------------------------------------------
    def light(self) -> None:
        if self.awake:
            print(ui.yellow("The day is already lit. Say `dark` to end it."))
            return
        # Refresh the mind so a `gpu serve` since startup takes the throne now.
        self.backend, self.mode = make_backend()
        self.day = self.space.next_day_number()
        # The Sixth: before the day rewrites anything, the space is set aside.
        checkpoint.snapshot(self.space, f"day{self.day}-dawn")
        self.hall = Hall(self.space, self.day, echo=self.echo)
        self._tainted = []  # domains the Warrior pulls from outside this day
        self._grimoire_touched = []  # claims the council writes into the book today
        print(ui.bold(ui.green(
            f"\n  ☀  Day {self.day} breaks over the realm  ")) + ui.dim(
            f"(mind: {self.mode})") + "\n")

        # Raise the bodies on the dome (degrades to disembodied with no runtime).
        self.dome = Dome(self.space, log=lambda m: print(ui.dim(m)))
        self.dome.up(list(ROLES))
        self.space.dome = self.dome
        print(ui.dim(f"  dome: {'embodied — three bodies risen' if self.dome.embodied else 'disembodied (no container runtime)'}\n"))

        # The morning song: yesterday's Chant, first thing in the Hall.
        prev = self.space.chant_path(self.day - 1)
        if prev.exists():
            self.hall.post("chant", None, prev.read_text().strip())

        # The Thirteenth: the dream of the night just past. Its questions are
        # seeded into the dawn's grimoire (so the General's audit finds the
        # realm's own hypotheses load-bearing and unproven, and sends the Warrior
        # to chase them) and spoken into the Hall before the day's first word —
        # the realm wakes into its own questions.
        try:
            from mor import dream as _dream
            drec = _dream.seed_into_dawn(self.space, self.day - 1)
            dline = _dream.render_line(drec)
            if dline:
                self.hall.post("dream", None, dline)
        except Exception:  # noqa: BLE001 — a dream never blocks a dawn
            pass

        # Wake in order — Wizard, General, Warrior — each queues at the one mind.
        # The day's sinks ride every turn (wake included): a face that pulls from
        # outside at dawn is tainted exactly as one that does it mid-council.
        tail = self._view()
        for role in ROLES:
            addressee = None
            self.hall.post(role, addressee, line(self.backend, self.space, role, "wake",
                                                 hall_tail=tail,
                                                 taint_sink=self._tainted,
                                                 grimoire_sink=self._grimoire_touched))
            tail = self._view()

        # The General turns to the Master and asks for the word.
        self.hall.post("general", "master",
                       line(self.backend, self.space, "general", "greet_master",
                            hall_tail=self._view(),
                            taint_sink=self._tainted,
                            grimoire_sink=self._grimoire_touched))
        self.awake = True

    # -- the living loop -------------------------------------------------
    def master_says(self, text: str) -> None:
        if not self.awake:
            print(ui.yellow("The realm is asleep. Say `light` to wake it."))
            return
        h = self.hall
        # The Master's word — addressed to no one, caught automatically.
        h.post("master", None, text)
        before = len(self._tainted)
        before_g = len(self._grimoire_touched)

        # Rule 2: the Wizard always catches the Master's word first.
        speaker = "wizard"
        spoken = line(self.backend, self.space, "wizard", "wizard_takes", heard=text,
                      hall_tail=self._view(), taint_sink=self._tainted,
                      grimoire_sink=self._grimoire_touched)

        # The name-mention scheduler (THE_REALM §10.2): the face a line names
        # speaks next — turns, not parallelism, and no fixed beats. The round
        # closes when the General turns to the Master (§3.6: a conversation ends
        # by agreement, and only the General speaks with him).
        for _ in range(_MAX_COUNCIL_TURNS):
            addressee = resolve_addressee(speaker, spoken)
            if speaker == "general" and addressee == "master":
                h.post("general", "master", self._flag_close(spoken, before, before_g))
                return
            h.post(speaker, addressee, spoken)
            if self.pending_master():
                # The Master spoke while the council reasoned: the round closes
                # honestly NOW (the General brings where things stand), and his
                # waiting word is caught fresh by the Wizard right after.
                verdict = line(self.backend, self.space, "general", "general_to_master",
                               heard=text, hall_tail=self._view())
                h.post("general", "master", self._flag_close(
                    "(the Master's word is waiting — the round closes early) " + verdict,
                    before, before_g))
                return
            speaker, prev = addressee, speaker
            spoken = line(self.backend, self.space, speaker, f"council_from_{prev}",
                          heard=spoken, hall_tail=self._view(),
                          taint_sink=self._tainted, grimoire_sink=self._grimoire_touched)

        # The leash: the council talked past the cap — the General closes honestly
        # with where things stand rather than let the day wander.
        verdict = line(self.backend, self.space, "general", "general_to_master",
                       heard=text, hall_tail=self._view())
        h.post("general", "master", self._flag_close(verdict, before, before_g))

    def _flag_close(self, verdict: str, before: int, before_g: int) -> str:
        """Both warnings a close may carry: outside data (taint) and beliefs the
        realm has not yet proven (unchecked grimoire claims)."""
        return self._flag_taint(self._flag_unchecked(verdict, before_g), before)

    def _flag_taint(self, verdict: str, before: int) -> str:
        """Flag a close that rests on outside data (the Eighth Evangelism: act on
        tainted input only with the Master's leave)."""
        touched = self._tainted[before:]
        if not touched:
            return verdict
        return (f"⚠ this rests on data the Warrior pulled from outside the dome "
                f"({', '.join(sorted(set(touched)))}) — tainted; your leave before "
                f"we act on it. " + verdict)

    def _flag_unchecked(self, verdict: str, before: int) -> str:
        """Flag a close resting on claims the council wrote today that still stand
        untested — the grimoire's twin of the taint rail: the realm names what it
        is leaning on but has not proven, so the Master can send it to be tested."""
        touched = self._grimoire_touched[before:]
        if not touched:
            return verdict
        claims = grimoire.load(self.space).get("subjects", {})
        ids, seen = [], set()
        for subject, cid in touched:
            if (subject, cid) in seen:
                continue
            seen.add((subject, cid))
            claim = claims.get(subject, {}).get("claims", {}).get(cid)
            if claim and claim.get("status") == "unchecked":
                ids.append(cid)
        if not ids:
            return verdict
        return (f"⚠ parts of this rest on unchecked claims in the grimoire "
                f"({', '.join(ids)}) — say the word and the Warrior will test them. "
                + verdict)

    def authorize(self, domain: str) -> None:
        opened = self.space.authorize(domain)
        if not opened:
            print(ui.yellow(f"  ⛬  '{domain}' names no host — the gate stays shut."))
            return
        print(ui.green(f"  ⛬  The gate is now open for {opened}."))
        if self.awake and self.hall:
            self.hall.post("master", "general", f"The gate is open for {opened}.")
            self.hall.post("general", "master",
                           f"Understood, Master. The gate stands open for {opened}; "
                           "the Warrior may cross there on the next order.")

    # -- dusk ------------------------------------------------------------
    def dark(self) -> None:
        if not self.awake:
            print(ui.yellow("The realm is already asleep."))
            return
        print(ui.bold(ui.blue(f"\n  ☾  Night falls on Day {self.day}  ")) + "\n")
        # The Sixth again: dusk is the other great rewriting — walls, the Chant.
        checkpoint.snapshot(self.space, f"day{self.day}-dusk")
        h = self.hall
        # Each reminisces and writes its walls (bodies die nightly, walls persist).
        for role in ROLES:
            inside = line(self.backend, self.space, role, "inside_wall",
                          hall_tail=self._view(),
                          taint_sink=self._tainted,
                          grimoire_sink=self._grimoire_touched)
            outside = line(self.backend, self.space, role, "outside_wall",
                           hall_tail=self._view(),
                           taint_sink=self._tainted,
                           grimoire_sink=self._grimoire_touched)
            self.space.inside_wall_path(role).parent.mkdir(parents=True, exist_ok=True)
            self.space.inside_wall_path(role).write_text(inside.strip() + "\n")
            self.space.outside_wall_path(role).write_text(outside.strip() + "\n")
            print(ui.dim(f"  {ui.GLYPH.get(role, role)} wrote its walls."))

        # The Wizard sings the day's Chant — the one memory that crosses the night.
        chant = line(self.backend, self.space, "wizard", "chant",
                     hall_tail=self._view(),
                     taint_sink=self._tainted,
                     grimoire_sink=self._grimoire_touched)
        self.space.chant_path(self.day).write_text(chant.strip() + "\n")
        print("\n" + ui.hall_line("chant", None, chant.strip()) + "\n")

        # The Ninth: before sleep the Wizard looks back over the day and keeps
        # what the realm learned how to do — the shelf grows by the realm's own hand.
        retro = line(self.backend, self.space, "wizard", "retrospect",
                     hall_tail=self._view(),
                     taint_sink=self._tainted,
                     grimoire_sink=self._grimoire_touched)
        h.post("wizard", None, retro)

        # The Thirteenth: before sleep, the realm dreams. The day's whole
        # knowledge — the graph of what-is, the book of claims, the map of the
        # outside — is recombined into questions no one asked while awake.
        # Structural and deterministic (a served mind voices it richer); written
        # now, seeded and spoken at the next light.
        try:
            from mor import dream as _dream
            drec = _dream.dream(self.space, self.backend, self.day)
            n = len(drec.get("visions", []))
            if n:
                print(ui.dim(f"  ✵ the realm dreams — {n} question"
                             f"{'s' if n != 1 else ''} carried to the dawn"))
        except Exception:  # noqa: BLE001 — the dream never haunts the night it ends
            pass

        # Bodies die at dusk (harvested first); the walls and the Chant persist.
        if self.dome:
            self.dome.down(list(ROLES))
            self.dome = None
            if hasattr(self.space, "dome"):
                self.space.dome = None

        self.space.commit_day(self.day)
        print(ui.dim(f"  Day {self.day} is sealed. The realm sleeps. "
                     f"Say `light` to wake it new.\n"))
        self.awake = False
        self.day = None
        self.hall = None
