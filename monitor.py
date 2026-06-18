#!/usr/bin/env python3
"""
VM straffevakt — overvaaker Fotball-VM 2026 og sender Pushover-varsel
naar en utslagskamp er paa vei mot straffekonkurranse.

Henter live-data fra ESPNs offentlige scoreboard-API (ren JSON, ingen noekkel).
To triggere:
  A: 1. ekstraomgang ferdigspilt og fortsatt likt  -> "kan gaa mot straffer"
  B: ~3 min igjen av 2. ekstraomgang (eller straffer i gang) -> rapporter stilling

Krever to miljoevariabler:
  PUSHOVER_TOKEN  (API-token for din Pushover-applikasjon)
  PUSHOVER_USER   (din Pushover user key)

Bruk:
  python3 monitor.py          # en sjekk
  python3 monitor.py --test   # send et test-varsel og avslutt
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER")


def fetch():
    req = urllib.request.Request(ESPN_URL, headers={"User-Agent": "vm-straffevakt/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def display_min(dc):
    try:
        return int(str(dc).replace("'", "").split("+")[0].strip())
    except Exception:
        return None


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)


def send_push(title, message, priority=0):
    if not (PUSHOVER_TOKEN and PUSHOVER_USER):
        print("Mangler PUSHOVER_TOKEN/PUSHOVER_USER", file=sys.stderr)
        return False
    data = urllib.parse.urlencode({
        "token": PUSHOVER_TOKEN,
        "user": PUSHOVER_USER,
        "title": title,
        "message": message,
        "priority": str(priority),
    }).encode()
    try:
        with urllib.request.urlopen("https://api.pushover.net/1/messages.json", data=data, timeout=25) as r:
            r.read()
        return True
    except urllib.error.HTTPError as e:
        print("Pushover-feil:", e.read().decode(errors="replace"), file=sys.stderr)
        return False
    except Exception as e:
        print("Pushover-feil:", e, file=sys.stderr)
        return False


def decide(comp):
    """Returnerer (trigger, tittel, melding) eller (None, None, None)."""
    status = comp.get("status", {}) or {}
    st = status.get("type", {}) or {}
    if st.get("state") != "in":
        return None, None, None

    name = (st.get("name") or "").upper()
    desc = ((st.get("description") or "") + " " + (st.get("detail") or "")).lower()
    mins = display_min(status.get("displayClock"))

    comps = comp.get("competitors", [])
    if len(comps) < 2:
        return None, None, None

    def score(c):
        try:
            return int(c.get("score"))
        except Exception:
            return None

    h = next((c for c in comps if c.get("homeAway") == "home"), comps[0])
    a = next((c for c in comps if c.get("homeAway") == "away"), comps[1])
    hs, as_ = score(h), score(a)
    if hs is None or as_ is None:
        return None, None, None

    hn = (h.get("team", {}) or {}).get("displayName") or (h.get("team", {}) or {}).get("abbreviation") or "Hjemme"
    an = (a.get("team", {}) or {}).get("displayName") or (a.get("team", {}) or {}).get("abbreviation") or "Borte"
    level = hs == as_
    label = f"{hn} {hs}-{as_} {an}"

    is_pens = ("PENALT" in name) or ("SHOOTOUT" in name) or ("penalt" in desc) or ("shootout" in desc)
    is_ht_et = ("HALFTIME_ET" in name) or ("halftime et" in desc) or ("et halftime" in desc) or ("end of first extra" in desc)
    is_2nd_et = ("SECOND_EXTRA" in name) or ("second extra time" in desc)

    # Straffer allerede i gang (sikkerhetsnett, deler noekkel med B)
    if is_pens:
        return "B", "VM straffevakt", f"⚽ {label} — straffekonkurranse i gang!"

    # Trigger B: ~3 min igjen av 2. ekstraomgang
    if is_2nd_et and mins is not None and mins >= 115:
        if level:
            return "B", "VM straffevakt", f"⚽ {label} — ~3 min igjen av ekstraomgangene, fortsatt likt. Straffer svært nær!"
        return "B", "VM straffevakt", f"⚽ {label} — ~3 min igjen av ekstraomgangene."

    # Trigger A: 1. ekstraomgang ferdig og fortsatt likt
    if level and (is_ht_et or (is_2nd_et and (mins is None or mins <= 110))):
        return "A", "VM straffevakt", f"⚽ {label} — 1. ekstraomgang ferdig og fortsatt likt. Kan gå mot straffer!"

    return None, None, None


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        ok = send_push("VM straffevakt", "✅ Testvarsel — oppsettet fungerer. Du vil nå få push når en VM-utslagskamp nærmer seg straffer.")
        print("Test sendt" if ok else "Test feilet")
        return

    try:
        data = fetch()
    except Exception as e:
        print("Henting feilet:", e, file=sys.stderr)
        return

    state = load_state()
    live_ids = set()
    changed = False

    for ev in data.get("events", []):
        eid = str(ev.get("id"))
        comp = (ev.get("competitions") or [{}])[0]
        ev_state = (((comp.get("status") or {}).get("type") or {}).get("state"))
        if ev_state == "in":
            live_ids.add(eid)

        trig, title, msg = decide(comp)
        if not trig:
            continue
        key = f"{eid}:{trig}"
        if state.get(key):
            continue
        priority = 1 if trig == "B" else 0
        if send_push(title, msg, priority):
            state[key] = True
            changed = True
            print("Sendt:", msg)

    # Rydd bort noekler for kamper som ikke lenger paagaar
    for k in list(state.keys()):
        if k.split(":")[0] not in live_ids:
            del state[k]
            changed = True

    if changed:
        save_state(state)
        print("State oppdatert")
    else:
        print("Ingen trigger denne kjoeringen")


if __name__ == "__main__":
    main()
