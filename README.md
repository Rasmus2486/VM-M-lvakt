# VM straffevakt → push på mobilen (gratis, via Pushover)

En liten tjeneste som kjører gratis i skyen (GitHub Actions), sjekker live
VM-2026-kamper hvert 5. minutt, og sender deg en **push-varsling på mobilen**
når en utslagskamp nærmer seg straffekonkurranse.

Du trenger ingen egen app i App Store — du bruker den ferdige **Pushover**-appen.

**To varsler (samme som i Cowork-versjonen):**
- **A** – når 1. ekstraomgang er ferdigspilt og det fortsatt står likt → «kan gå mot straffer».
- **B** – når det er ca. 3 min igjen av siste ekstraomgang (eller straffer akkurat har startet) → varsler stillingen.

Dekker alle sluttspillkamper (Runde 32 og utover). Straffer kan først skje fra **28. juni**.

---

## Filer
- `monitor.py` – selve overvåkingen (ren Python, ingen pakker å installere).
- `watch.yml` – GitHub Actions-jobb som kjører `monitor.py` på timeplan. **Skal ligge i `.github/workflows/` i repoet.**
- `state.json` – holder styr på hva som allerede er varslet (unngår dobbeltvarsler). Oppdateres automatisk.

---

## Oppsett (engangsjobb, ca. 10 min)

### 1. Pushover på mobilen
1. Last ned **Pushover** fra App Store / Google Play og lag en konto (gratis 30-dagers prøve, deretter en engangssum ~5 USD per plattform).
2. Logg inn på <https://pushover.net>. Øverst ser du din **User Key** – noter den.
3. Gå til <https://pushover.net/apps/build>, lag en applikasjon (navn f.eks. «VM straffevakt»), og kopier **API Token/Key** du får.

Nå har du to verdier: **User Key** og **API Token**.

### 2. Legg koden i et GitHub-repo
1. Lag et nytt repo på GitHub. Tips: gjør det **public** → da er GitHub Actions helt gratis uten minuttgrense.
2. Last opp `monitor.py` og `state.json` i roten.
3. Lag mappen `.github/workflows/` og legg `watch.yml` der.

Strukturen skal se slik ut:
```
ditt-repo/
├─ monitor.py
├─ state.json
└─ .github/
   └─ workflows/
      └─ watch.yml
```

### 3. Legg inn nøklene som «secrets»
I repoet: **Settings → Secrets and variables → Actions → New repository secret**. Lag to stk:
- `PUSHOVER_TOKEN` = API Token fra steg 1.3
- `PUSHOVER_USER` = User Key fra steg 1.2

(Secrets er trygge også i public repo – de vises aldri i koden eller loggene.)

### 4. Slå på og test
1. Gå til **Actions**-fanen og bekreft at workflows er aktivert.
2. Velg «VM straffevakt» → **Run workflow** for å kjøre manuelt med én gang.
3. Vil du teste at push når frem til mobilen? Kjør lokalt på egen maskin:
   ```bash
   PUSHOVER_TOKEN=xxx PUSHOVER_USER=yyy python3 monitor.py --test
   ```
   Du skal da få et «✅ Testvarsel» på telefonen.

Ferdig. Tjenesten sjekker nå automatisk og varsler deg når det lukter straffer.

---

## Greit å vite
- **Timeplan:** kjører hvert 5. minutt i kampvinduet (ca. 15–04 UTC), kun i juni/juli. Endre `cron` i `watch.yml` om du vil ha et annet vindu. GitHub kan forsinke planlagte kjøringer noen minutter ved høy last – derfor varsler vi i et lite tidsvindu, ikke på ett eksakt minutt.
- **Ingen server å drifte** – alt kjører i GitHub Actions.
- **Etter VM:** du kan bare slette repoet, eller skru av workflowen under Actions. (GitHub deaktiverer uansett planlagte jobber automatisk etter 60 dager uten aktivitet.)
- **Datakilde:** ESPNs offentlige scoreboard-API for VM (`site.api.espn.com/.../soccer/fifa.world/scoreboard`). Krever ingen nøkkel.
