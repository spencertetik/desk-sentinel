# Always-on supervision (launchd)

On macOS, Desk Sentinel can run as a **LaunchAgent** so it stays up no matter what:

- **KeepAlive** — restarts the process on any exit (crash, or the in-app
  capture watchdog's exit-on-wedge).
- **RunAtLoad** — starts at login / after a reboot.
- The app is the **single owner of port 8088** — don't also launch it by hand
  with `python -m sentinel.app` while the agent is loaded, or you'll get two
  competing instances (a stale one can freeze the feed while still serving — the
  exact bug this setup fixes).

## Reliability layers

1. **In-thread self-heal** (`sentinel/capture.py`): RTSP read has a 15s socket
   timeout so it can't block forever; reconnects with backoff; `is_healthy()`
   reflects real frame freshness.
2. **Watchdog** (`sentinel/app.py`): if the feed stays stale >45s (unrecoverable
   wedge), the process exits so launchd restarts a clean one.
3. **launchd supervisor** (`com.desk-sentinel.plist.template`): restarts on exit
   + at login.

## Install / manage

The plist is a **template** — fill in your own paths first. `__INSTALL_DIR__`
is the absolute path to this repo on your machine; `__HOME__` is your home
directory. The `sed` command below substitutes both automatically.

```bash
# from the repo root, generate a real plist from the template:
sed -e "s#__INSTALL_DIR__#$(pwd)#g" -e "s#__HOME__#$HOME#g" \
  deploy/com.desk-sentinel.plist.template > ~/Library/LaunchAgents/com.desk-sentinel.plist

# load it (starts now + at every login)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.desk-sentinel.plist

# status (PID + last exit code)
launchctl list | grep desk-sentinel

# restart now
launchctl kickstart -k gui/$(id -u)/com.desk-sentinel

# stop / uninstall
launchctl bootout gui/$(id -u)/com.desk-sentinel

# logs
tail -f ~/.desk-sentinel/desk-sentinel.log ~/.desk-sentinel/desk-sentinel.err.log
```

Dashboard: http://localhost:8088
