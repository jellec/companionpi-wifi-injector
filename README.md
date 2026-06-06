# companionpi-wifi-injector

**Version:** 0.3.x | NAS webapp + local companion-agent

Generates and writes the CompanionPi network setup onto a freshly flashed SD card. Everything via the browser — no CLI needed.

---

## Architecture

```
NAS (Docker :7070)               Mac/Windows (localhost:7072)     SD card
┌──────────────────────┐         ┌──────────────────────┐         ┌─────────────┐
│ companionpi-wifi-    │ bundle  │ companion-agent       │ write   │ firstrun.sh │
│ injector (Flask)     │────────▶│ (.app / .exe)         │────────▶│ cmdline.txt │
│                      │ base64  │                        │         │ wifi/       │
│ - caches wifi repo   │         │ - detecteert SD kaart  │         └─────────────┘
│ - bouwt ZIP bundle   │         │ - schrijft bundle weg  │
│ - geeft bundle via   │         │ - luistert op :7072    │
│   API terug          │         └──────────────────────┘
└──────────────────────┘
```

De **NAS-webapp** draait in Docker en is bereikbaar op het lokale netwerk. De **companion-agent** draait op je Mac of Windows, detecteert gemounte SD-kaarten en schrijft de bundle weg — zonder terminal.

---

## Snel starten (NAS)

```bash
docker compose up -d
```

Open `http://<NAS-IP>:7070` in je browser.

---

## companion-agent installeren

Download de agent via GitHub Releases (automatisch gebouwd bij elke push):

| Platform | Bestand | Stap |
|---|---|---|
| macOS | `companion-agent-macos.zip` | Pak uit → rechtermuisknop → **Open** (eenmalig voor Gatekeeper) |
| Windows | `companion-agent.exe` | Dubbelklik om te starten |

De agent draait op de achtergrond op **http://localhost:7072**. De NAS-webapp herkent hem automatisch en toont de SD-kaartkeuzelijst.

---

## Gebruik

1. Flash de **CompanionPi** image via [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Start de companion-agent op je Mac/Windows (zie boven)
3. Open `http://<NAS-IP>:7070`
4. Klik **Fetch/update repo** (haalt companionpi-wifi op naar de NAS)
5. Stel hostname, Wi-Fi, wachtwoord en AP-instellingen in
6. Selecteer de SD-kaart in stap 4 van de wizard
7. Klik **Injecteer op SD-kaart** → de agent schrijft alles weg
8. Werp de SD-kaart uit, stop hem in de RPi, zet hem aan
9. Eerste boot (~2–5 min) configureert alles automatisch, dan herstart de RPi

### Zonder agent (handmatig)

Als de agent niet actief is, kun je in stap 5 de **bundle downloaden** als ZIP en hem handmatig schrijven:

```bash
# Auto-detecteert RPi boot-partitie
bash inject.sh ~/Downloads/companionpi-bundle.zip

# Expliciet pad opgeven
bash inject.sh ~/Downloads/companionpi-bundle.zip /Volumes/bootfs
```

---

## inject.sh

Bash-helper voor macOS. Pakt de bundle uit op de gemounte SD-kaart en patcht `cmdline.txt`. Als meerdere partities gevonden worden, verschijnt een keuzemenu.

Vereisten: `bash`, `python3` (standaard op macOS), `unzip`.

---

## Bundle-inhoud

| Bestand | Doel |
|---|---|
| `firstrun.sh` | Draait bij eerste boot — configureert hostname, Wi-Fi, Companion |
| `userconf.txt` | Maakt het `companion`-gebruikersaccount aan |
| `ssh` | Zet SSH aan bij eerste boot |
| `companionpi-wifi/` | Volledige wifi-manager repo — offline geïnstalleerd vanaf SD-kaart |
| `meta.json` | Bundle-metadata (versie, tijdstip, cmdline_add) |
| `companionpi-info.txt` | Leesbare samenvatting van de ingestelde waarden |

---

## Development

```bash
pip install -r requirements.txt
python imager.py          # NAS-webapp op http://localhost:7070

python companion-agent.py # lokale agent op http://localhost:7072
```

---

## CI/CD

| Workflow | Trigger | Wat |
|---|---|---|
| `.gitea/workflows/deploy.yml` | push naar `main` | Deploy injector op NAS |
| `.github/workflows/build-agent.yml` | push → `companion-agent.py` | Bouw `.app`, `.exe`, Linux binary → GitHub Release `latest-agent` |

De GitHub-workflow vereist een GitHub-remote (naast de Gitea/Codeberg remote). Eenmalig instellen:

```bash
git remote add github https://github.com/<user>/companionpi-wifi-injector.git
git push github main
```

---

## Requirements

- Python 3.8+
- `flask>=3.0`
- `passlib>=1.7`
- `certifi>=2024.0`
- `git` (voor het ophalen van de companionpi-wifi repo)

---

## Gerelateerd

- [companionpi-wifi](https://codeberg.org/jellec/companionpi-wifi) — de network manager die op de RPi wordt geïnstalleerd
- [infra-stacks/stack_companionpi](https://git.fjhome.eu/jellec/infra-stacks) — NAS deploy-stack
- [Bitfocus Companion](https://bitfocus.io/companion) — de software waar dit allemaal omheen draait
