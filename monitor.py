#!/usr/bin/env python3
"""
VM straffevakt — overvaaker Fotball-VM 2026 og sender Pushover-varsel
naar en utslagskamp er paa vei mot straffekonkurranse.
 
Henter live-data fra ESPNs offentlige scoreboard-API (ren JSON, ingen noekkel).
 
VIKTIG OM TIMING:
  Naar skriptet startes og det er en VM-kamp som enten paagaar eller starter
  innen ~25 min, "laaser" det seg fast og sjekker hvert 60. sekund helt til
  kampen(e) er ferdig. Slik blir vi ikke avhengige av at GitHubs cron treffer
  akkurat det rette minuttet — det holder at den starter oss én gang i loepet
  av kampen. Er ingen kamp live/naert forestaaende, avslutter vi med en gang.
 
To triggere:
  A: stillingen er lik rundt slutten av 1. ekstraomgang (~104-112 min)  -> "kan gaa mot straffer"
  B: ~3 min igjen av 2. ekstraomgang (>=116 min) ELLER straffer i gang  -> rapporter stilling
 
Krever miljoevariabler:
  PUSHOVER_TOKEN, PUSHOVER_USER
 
Bruk:
  python3 monitor.py          # smart modus (laas-og-foelg)
  python3 monitor.py --once   # én enkelt sjekk (debug)
  python3 monitor.py --test   # send et testvarsel og avslutt
"""
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.parse
import urllib.error
 
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN")
PUSHOVER_USER = os.environ.get("PUSHOVER_USER")
 
POLL_SECONDS = 60          # hvor ofte vi sjekker mens en kamp foelges
IDLE_POLL_SECONDS = 120    # hvor ofte vi sjekker naar ingenting skjer (--forever)
IMMINENT_MIN = 25          # start aa foelge en kamp saa mange min foer avspark
MAX_RUNTIME_MIN = int(os.environ.get("MAX_RUNTIME_MIN", "315"))  # stopp foer GitHubs 6t-grense
 
 
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)
 
 
def fetch():
    req = urllib.request.Request(ESPN_URL, headers={"User-Agent": "vm-straffevakt/2.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)
 
 
def parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None
 
 
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
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("Kunne ikke lagre state:", e, file=sys.stderr)
 
 
def send_push(title, message, priority=0):
    if not (PUSHOVER_TOKEN and PUSHOVER_USER):
        print("FEIL: Mangler PUSHOVER_TOKEN/PUSHOVER_USER", file=sys.stderr)
        return False
    data = urllib.parse.urlencode({
        "token": PUSHOVER_TOKEN, "user": PUSHOVER_USER,
        "title": title, "message": message, "priority": str(priority),
    }).encode()
    try:
        with urllib.request.urlopen("https://api.pushover.net/1/messages.json", data=data, timeout=25) as r:
            r.read()
        return True
    except Exception as e:
        try:
            detalj = e.read().decode(errors="replace")
        except Exception:
            detalj = str(e)
        print("Pushover-feil:", detalj, file=sys.stderr)
        return False
 
 
def teams(comp):
    cs = comp.get("competitors", [])
    h = next((c for c in cs if c.get("homeAway") == "home"), cs[0] if cs else {})
    a = next((c for c in cs if c.get("homeAway") == "away"), cs[1] if len(cs) > 1 else {})
 
    def score(c):
        try:
            return int(c.get("score"))
        except Exception:
            return None
 
    def name(c):
        t = c.get("team", {}) or {}
        return t.get("displayName") or t.get("shortDisplayName") or t.get("abbreviation") or "?"
 
    def shootout(c):
        v = c.get("shootoutScore")
        try:
            return int(v)
        except Exception:
            return None
 
    return (name(h), score(h), shootout(h)), (name(a), score(a), shootout(a))
 
 
def decide(comp):
    """Returnerer (trigger, tittel, melding) eller (None, None, None)."""
    status = comp.get("status", {}) or {}
    st = status.get("type", {}) or {}
    if st.get("state") != "in":
        return None, None, None
 
    name = (st.get("name") or "").upper()
    desc = ((st.get("description") or "") + " " + (st.get("detail") or "")).lower()
    mins = display_min(status.get("displayClock"))
    (hn, hs, hso), (an, as_, aso) = teams(comp)
    if hs is None or as_ is None:
        return None, None, None
    level = hs == as_
    label = f"{hn} {hs}-{as_} {an}"
 
    # --- Straffekonkurranse i gang (flere signaler) ---
    is_pens = ("PENALT" in name or "SHOOTOUT" in name or "penalt" in desc or "shootout" in desc
               or hso is not None or aso is not None)
    if is_pens:
        ekstra = ""
        if hso is not None and aso is not None:
            ekstra = f" (straffer {hso}-{aso})"
        return "B", "VM straffevakt", f"⚽ {label} — straffekonkurranse i gang!{ekstra}"
 
    # Ekstraomganger? Bruk baade klokke (mest paalitelig) og statustekst.
    in_et = (mins is not None and mins >= 91) or ("EXTRA" in name) or ("extra time" in desc) or (" aet" in desc) or ("et " in desc)
    is_2nd_et = ("SECOND_EXTRA" in name) or ("second extra" in desc) or (mins is not None and mins >= 106)
    is_ht_et = ("HALFTIME_ET" in name) or ("halftime et" in desc) or ("et halftime" in desc) or ("end of first extra" in desc)
 
    # --- Trigger B: ~3 min igjen av siste ekstraomgang ---
    if mins is not None and mins >= 116 and in_et:
        if level:
            return "B", "VM straffevakt", f"⚽ {label} — ~3 min igjen av ekstraomgangene, fortsatt likt. Straffer svært nær!"
        return "B", "VM straffevakt", f"⚽ {label} — ~3 min igjen av ekstraomgangene."
 
    # --- Trigger A: lik stilling rundt slutten av 1. ekstraomgang ---
    if level and (is_ht_et or (mins is not None and 104 <= mins <= 112) or (is_2nd_et and (mins is None or mins <= 112))):
        return "A", "VM straffevakt", f"⚽ {label} — 1. ekstraomgang ferdig og fortsatt likt. Kan gå mot straffer!"
 
    return None, None, None
 
 
def scan_and_notify(data, state):
    """Vurderer alle kamper, sender varsler, returnerer (changed, n_live, n_imminent)."""
    changed = False
    n_live = 0
    n_imminent = 0
    now = now_utc()
 
    for ev in data.get("events", []):
        eid = str(ev.get("id"))
        comp = (ev.get("competitions") or [{}])[0]
        st = ((comp.get("status") or {}).get("type") or {})
        state_str = st.get("state")
 
        if state_str == "in":
            n_live += 1
            # Diagnostikk i loggen (hjelper oss kalibrere mot ekte data)
            (hn, hs, _), (an, as_, _) = teams(comp)
            print(f"  LIVE: {hn} {hs}-{as_} {an} | {st.get('name')} | klokke={ (comp.get('status') or {}).get('displayClock') } | {st.get('detail')}")
        elif state_str == "pre":
            ko = parse_iso(ev.get("date"))
            if ko is not None and now <= ko <= now + datetime.timedelta(minutes=IMMINENT_MIN):
                n_imminent += 1
 
        trig, title, msg = decide(comp)
        if not trig:
            continue
        key = f"{eid}:{trig}"
        if state.get(key):
            continue
        if send_push(title, msg, priority=(1 if trig == "B" else 0)):
            state[key] = True
            changed = True
            print("  >>> SENDT:", msg)
 
    # Rydd noekler for kamper som ikke lenger er live
    live_ids = {str(ev.get("id")) for ev in data.get("events", [])
                if (((ev.get("competitions") or [{}])[0].get("status") or {}).get("type") or {}).get("state") == "in"}
    for k in list(state.keys()):
        if k.split(":")[0] not in live_ids:
            del state[k]
            changed = True
 
    return changed, n_live, n_imminent
 
 
def main():
    if "--test" in sys.argv:
        ok = send_push("VM straffevakt", "✅ Testvarsel — oppsettet fungerer. Du vil nå få push når en VM-utslagskamp nærmer seg straffer.")
        print("Test sendt" if ok else "Test feilet")
        return
 
    once = "--once" in sys.argv
    forever = "--forever" in sys.argv
    started = now_utc()
    state = load_state()
 
    while True:
        n_live = n_imminent = 0
        try:
            data = fetch()
        except Exception as e:
            print("Henting feilet:", e, file=sys.stderr)
            data = None
 
        if data is not None:
            changed, n_live, n_imminent = scan_and_notify(data, state)
            if changed:
                save_state(state)
            ts = now_utc().strftime("%H:%M:%S")
            print(f"[{ts}UTC] live={n_live} imminent={n_imminent}")
 
            if once:
                return
            # I --forever-modus kjoerer vi videre uansett (alltid-paa).
            # Ellers avslutter vi naar ingen kamp er live eller naert forestaaende.
            if not forever and n_live == 0 and n_imminent == 0:
                print("Ingen kamp live eller naert forestaaende — avslutter.")
                return
        elif once:
            return
 
        # Sikkerhetsgrense paa total kjoeretid (neste kjoering i koeen tar over)
        if (now_utc() - started).total_seconds() > MAX_RUNTIME_MIN * 60:
            print("Naadde maks kjoeretid — avslutter rent saa neste jobb kan ta over.")
            return
 
        # Sjekk ofte naar noe skjer, sjeldnere naar det er stille
        time.sleep(POLL_SECONDS if (n_live > 0 or n_imminent > 0) else IDLE_POLL_SECONDS)
 
 
if __name__ == "__main__":
    main()
 
