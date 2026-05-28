"""macOS menu-bar app. Owns the timer; the engine (sync.run) does the work.

Three states drive the icon + status line: OK / Syncing / Cannot-connect.
A failed sync never auto-retries immediately — it shows a Retry action. The
scheduled tick still fires on its interval (owner approved)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import rumps

from . import config, paths, ssh, sync
from .store import Store

log = logging.getLogger("cc-remote-sync")

INTERVALS = {"daily": 86400, "6h": 21600, "1h": 3600, "manual": 0}


def _asset(name: str) -> str | None:
    for base in (
        Path(__file__).resolve().parents[2] / "assets",   # dev checkout
        Path(__file__).resolve().parent / "assets",        # bundled alongside
    ):
        p = base / name
        if p.exists():
            return str(p)
    return None


class CCRemoteSync(rumps.App):
    def __init__(self):
        super().__init__("cc-remote-sync", icon=_asset("menubar_idle.png"), template=True,
                         quit_button="Quit")
        self.cfg = config.load()
        self._busy = False
        self._result = None  # set by worker thread, drained on main thread

        self.status_item = rumps.MenuItem("Idle")
        self.action_item = rumps.MenuItem("Sync now", callback=self.sync_now)
        self.auto_item = rumps.MenuItem("Auto-sync", callback=self.toggle_auto)
        self.auto_item.state = self.cfg.auto_sync
        self.interval_menu = rumps.MenuItem("Interval")
        for key in ("daily", "6h", "1h", "manual"):
            mi = rumps.MenuItem(key.capitalize(), callback=self.set_interval)
            mi.state = (self.cfg.interval == key)
            self.interval_menu.add(mi)

        self.menu = [
            self.status_item, None,
            self.action_item, None,
            self.auto_item, self.interval_menu, None,
            rumps.MenuItem("Open log…", callback=self.open_log),
            rumps.MenuItem("Reveal mapping store…", callback=self.reveal_store),
        ]

        # completion poller (main-thread UI updates from worker results)
        self._poller = rumps.Timer(self._drain, 0.4)
        self._poller.start()
        # scheduled auto-sync timer
        self._timer = rumps.Timer(self._tick, max(60, INTERVALS.get(self.cfg.interval, 0) or 86400))
        if self.cfg.auto_sync and INTERVALS.get(self.cfg.interval):
            self._timer.start()

    # ---- state rendering -------------------------------------------------
    def _set_state(self, state: str, text: str) -> None:
        icon = {"ok": "menubar_idle.png", "syncing": "menubar_syncing.png",
                "error": "menubar_error.png"}[state]
        self.icon = _asset(icon)
        self.status_item.title = text
        self.action_item.title = "Retry" if state == "error" else "Sync now"
        self.action_item.set_callback(None if state == "syncing" else self.sync_now)

    # ---- actions ---------------------------------------------------------
    def sync_now(self, _=None):
        if self._busy:
            return
        self._busy = True
        self._set_state("syncing", "Syncing…")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            store = Store(paths.STORE_PATH).load()
            summ = sync.run(self.cfg, store)
            self._result = ("ok", summ)
        except ssh.Unreachable as e:
            self._result = ("error", e)
        except Exception as e:  # surface, never silently swallow
            log.exception("sync crashed")
            self._result = ("crash", e)

    def _drain(self, _):
        if self._result is None:
            return
        kind, payload = self._result
        self._result = None
        self._busy = False
        if kind == "ok":
            self._set_state("ok", "✓ " + payload.line())
            if payload.skipped:
                # a session was live and got skipped -> nudge manual sync
                self.action_item.title = f"Sync now · {payload.skipped} live skipped"
                rumps.notification(
                    "cc-remote-sync", "Sync complete",
                    f"{payload.line()}\n{payload.skipped} live session(s) skipped — "
                    "Sync now once they're idle.")
            else:
                rumps.notification("cc-remote-sync", "Sync complete", payload.line())
        elif kind == "error":
            self._set_state("error", f"⚠ Can't reach {self.cfg.ssh_config.get('name')}")
            rumps.notification("cc-remote-sync", "Cannot connect", str(payload))
        else:
            self._set_state("error", f"⚠ Error: {payload}")
            rumps.notification("cc-remote-sync", "Sync error", str(payload))

    def _tick(self, _):
        if self.cfg.auto_sync:
            self.sync_now()

    def toggle_auto(self, sender):
        sender.state = not sender.state
        self.cfg.auto_sync = bool(sender.state)
        self.cfg.save()
        self._reschedule()

    def set_interval(self, sender):
        for mi in self.interval_menu.values():
            mi.state = False
        sender.state = True
        self.cfg.interval = sender.title.lower()
        self.cfg.save()
        self._reschedule()

    def _reschedule(self):
        self._timer.stop()
        secs = INTERVALS.get(self.cfg.interval, 0)
        if self.cfg.auto_sync and secs:
            self._timer.interval = secs
            self._timer.start()

    def open_log(self, _):
        rumps.notification("cc-remote-sync", "Log", str(paths.LOG_PATH))
        import subprocess
        subprocess.run(["open", str(paths.LOG_PATH)])

    def reveal_store(self, _):
        import subprocess
        subprocess.run(["open", "-R", str(paths.STORE_PATH)])


def main():
    paths.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(paths.LOG_PATH)],
    )
    CCRemoteSync().run()


if __name__ == "__main__":
    main()
