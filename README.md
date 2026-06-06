# companionpi-wifi-injector

**Version:** 0.4.x | Standalone desktop app voor Mac en Windows

Configureert en schrijft de CompanionPi netwerkinstellingen direct op een SD kaart. Geen Docker, geen server, geen CLI nodig.

---

## Downloaden

[**GitHub Releases →**](https://github.com/jellec/companionpi-wifi-injector/releases/tag/latest)

| Platform | Bestand |
|---|---|
| macOS | `companion-app-macos.zip` — pak uit, rechtermuisknop → **Open** (eenmalig) |
| Windows | `companion-app.exe` — dubbelklik |
| Linux | `companion-app-linux` — `chmod +x` en starten |

De app opent automatisch de browser op `http://localhost:7070`.

---

## Gebruik

1. Flash de **CompanionPi** ARM64 image via [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Start `companion-app`
3. Klik **Fetch repo** (eenmalig — haalt companionpi-wifi op en cachet lokaal)
4. Stel hostname, Wi-Fi, wachtwoord en AP-instellingen in
5. Sluit de SD kaart aan — hij verschijnt automatisch in de lijst
6. Klik **Injecteer op SD kaart**
7. Werp de SD kaart uit, stop hem in de RPi, zet hem aan
8. Eerste boot (~2–5 min) configureert alles automatisch, dan herstart de RPi

---

## Cache

De wifi-repo wordt lokaal gecached:

| Platform | Pad |
|---|---|
| macOS | `~/Library/Application Support/CompanionPi/wifi-repo-cache/` |
| Windows | `%LOCALAPPDATA%\CompanionPi\wifi-repo-cache\` |
| Linux | `~/.local/share/companionpi/wifi-repo-cache/` |

---

## inject.sh (alternatief)

Als je liever handmatig injecteert via de terminal:

```bash
# Genereer een bundle via de app (knop "Download bundle")
# Daarna:
bash inject.sh ~/Downloads/companionpi-bundle.zip
# of met expliciet pad:
bash inject.sh ~/Downloads/companionpi-bundle.zip /Volumes/bootfs
```

---

## Development

```bash
pip install -r requirements.txt
python companion-app.py
# → http://localhost:7070
```

---

## CI/CD

GitHub Actions bouwt automatisch `.app`, `.exe` en Linux binary bij elke push naar `main` die `companion-app.py`, templates of static files aanraakt.

Workflow: `.github/workflows/build-agent.yml` → Release `latest` op GitHub.

---

## Requirements

- Python 3.8+
- `flask>=3.0`
- `passlib[bcrypt]>=1.7`
- `certifi>=2024.0`
- `git` (voor het ophalen van de wifi-repo)

---

## Gerelateerd

- [companionpi-wifi](https://codeberg.org/jellec/companionpi-wifi) — de network manager die op de RPi wordt geïnstalleerd
- [Bitfocus Companion](https://bitfocus.io/companion) — de software waar dit allemaal omheen draait
