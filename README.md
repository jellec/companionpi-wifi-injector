# companionpi-wifi-injector

**Version:** 0.3.x | NAS webapp — runs as Docker container, accessible in the local network.

Generates a downloadable ZIP bundle that injects CompanionPi network setup onto a freshly flashed SD card. No internet needed on the Raspberry Pi during first boot.

---

## Architecture

```
NAS (Docker)                     Mac                         SD card / RPi
┌─────────────────────┐          ┌──────────────┐            ┌───────────────┐
│ companionpi-wifi-   │  bundle  │  inject.sh   │  copies    │  firstrun.sh  │
│ injector (Flask)    │─────────▶│  (bash)      │───────────▶│  cmdline.txt  │
│ :7070               │  ZIP     │              │            │  companionpi- │
│                     │          └──────────────┘            │  wifi/        │
│ caches companionpi- │                                      └───────────────┘
│ wifi repo locally   │
└─────────────────────┘
```

The injector caches the [companionpi-wifi](https://codeberg.org/jellec/companionpi-wifi) repo locally and bundles it into a ZIP together with `firstrun.sh`. The Mac only needs `inject.sh` — no Python, no dependencies.

---

## Quick start (NAS)

```bash
docker compose up -d
```

Open `http://<NAS-IP>:7070` in your browser.

---

## Usage

1. Flash **CompanionPi** image using [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Open `http://<NAS-IP>:7070`
3. Click **Fetch/update repo** (caches companionpi-wifi on the NAS)
4. Configure hostname, Wi-Fi, credentials, AP settings
5. Click **Download bundle** → saves `companionpi-bundle.zip`
6. Run `inject.sh` on your Mac:
   ```bash
   bash inject.sh /Volumes/bootfs companionpi-bundle.zip
   ```
7. Eject SD card, insert into RPi, power on
8. First boot runs `firstrun.sh` — configures everything automatically (~2–5 min), then reboots

---

## inject.sh

Mac-side helper script. Unpacks the bundle onto the mounted SD card boot partition and patches `cmdline.txt`.

```bash
# Auto-detect SD card (finds any mounted RPi boot partition)
bash inject.sh ~/Downloads/companionpi-bundle.zip

# Explicit path (if auto-detect picks the wrong one)
bash inject.sh ~/Downloads/companionpi-bundle.zip /Volumes/bootfs
```

Auto-detect werkt op macOS via `/Volumes/*/cmdline.txt`. Als meerdere partities gevonden worden, toont het script een keuzemenu.

Requirements: `bash`, `python3` (pre-installed on macOS), `unzip`.

---

## Bundle contents

| File | Purpose |
|---|---|
| `firstrun.sh` | Runs on first boot — configures hostname, Wi-Fi, Companion |
| `cmdline.txt.patch` | `systemd.run` entry to trigger firstrun |
| `userconf.txt` | Creates the `companion` user account |
| `ssh` | Enables SSH on first boot |
| `companionpi-wifi/` | Full wifi manager repo — installed offline from SD card |
| `meta.json` | Bundle metadata (version, timestamp, cmdline_add) |
| `companionpi-info.txt` | Human-readable summary of injected settings |

---

## Development

```bash
pip install -r requirements.txt
python imager.py
# → http://localhost:7070
```

---

## Requirements

- Python 3.8+
- `flask>=3.0`
- `passlib>=1.7`
- `certifi>=2024.0`
- `git` (for cloning companionpi-wifi repo)

---

## Related

- [companionpi-wifi](https://codeberg.org/jellec/companionpi-wifi) — the network manager installed on the RPi
- [infra-stacks/stack_companionpi](https://git.fjhome.eu/jellec/infra-stacks) — NAS deploy stack
- [Bitfocus Companion](https://bitfocus.io/companion) — the software this is all built around
