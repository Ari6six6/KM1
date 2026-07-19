"""The tunnel supervisor: it restores a dropped tunnel by itself, with backoff."""

from __future__ import annotations

from mor.tunnel import TunnelSupervisor


def test_up_tunnel_needs_no_action():
    sup = TunnelSupervisor(is_alive=lambda: True, redial=lambda: True)
    assert sup.tick() == "up"
    assert sup.redials == 0


def test_a_tunnel_killed_by_hand_is_restored_with_no_human_input():
    alive = {"v": True}
    redials = {"n": 0}

    def redial():
        redials["n"] += 1
        alive["v"] = True        # the dial succeeds
        return True

    sup = TunnelSupervisor(is_alive=lambda: alive["v"], redial=redial)
    assert sup.tick() == "up"

    alive["v"] = False           # someone kills the tunnel
    assert sup.tick() == "redialed"
    assert alive["v"] is True and redials["n"] == 1 and sup.redials == 1
    assert sup.tick() == "up"    # stays healed


def test_backoff_grows_and_caps_while_the_dial_keeps_failing():
    sup = TunnelSupervisor(is_alive=lambda: False, redial=lambda: False,
                           backoff=(2, 5, 10))
    sup.tick(); assert sup.next_backoff() == 2      # 1st failure
    sup.tick(); assert sup.next_backoff() == 5      # 2nd
    sup.tick(); assert sup.next_backoff() == 10     # 3rd
    sup.tick(); assert sup.next_backoff() == 10     # capped
    assert sup.redials == 0                          # never came back up


def test_failure_streak_resets_after_a_successful_redial():
    state = {"alive": False, "fail": True}

    def redial():
        if state["fail"]:
            return False
        state["alive"] = True
        return True

    sup = TunnelSupervisor(is_alive=lambda: state["alive"], redial=redial,
                           backoff=(1, 2, 3))
    sup.tick(); sup.tick()
    assert sup.consecutive_failures == 2
    state["fail"] = False        # the box comes back; next dial works
    assert sup.tick() == "redialed"
    assert sup.consecutive_failures == 0


def test_start_and_stop_are_clean():
    sup = TunnelSupervisor(is_alive=lambda: True, redial=lambda: True,
                           check_interval=0.01)
    sup.start()
    sup.stop()                   # joins without hanging; no assertion beyond no-crash
