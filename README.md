# companion-imager

**Version:** 0.2.x (pre-release)

Local web app (Mac/Windows/Linux) that injects a CompanionPi network setup into a freshly flashed SD card. Runs on port 7070 and opens automatically in your browser.

---

## What it does

Writes a `firstrun.sh` script onto the SD card boot partition. On first RPi boot, this script automatically installs and configures everything — no keyboard or monitor needed.

**Two modes:**

| Mode | Use when |
|---|---|
| **RPi OS Lite** | Fresh Raspberry Pi OS Lite image — installs Companion + network manager |
| **CompanionPi (Bitfocus)** | Official CompanionPi image — Companion already installed, only injects network config |

---

## Quick start

```bash
pip install -r requirements.txt
python3 imager.py
```

Browser opens at `http://localhost:7070`.

---

## Steps

1. Flash **RPi OS Lite (64-bit)** or **CompanionPi** image using [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Run `python3 imager.py`
3. Select the mounted boot partition
4. Configure hostname, Wi-Fi, user credentials, AP settings
5. **(RPi OS only)** Optionally bundle a Companion `.deb` / `.tar.gz` for offline install
6. Click **Inject CompanionPi**
7. Eject SD card safely, insert into RPi, power on
8. Open `http://<hostname>.local` in your browser — watch the install progress live

First boot takes **~5–10 minutes** depending on internet speed and packages.

---

## Offline Companion install

Companion v4 is distributed via [user.bitfocus.io/download](https://user.bitfocus.io/download) (free account required).

1. Download the **Linux ARM64 `.deb`** or **`.tar.gz`**
2. In the imager — Step 3 — click **Choose .deb file** and import it
3. The file is bundled onto the SD card; the RPi installs it without internet

---

## What gets injected

| File | Purpose |
|---|---|
| `firstrun.sh` | Runs on first boot — installs packages, clones repo, configures network |
| `cmdline.txt` | Modified to trigger `firstrun.sh` via systemd |
| `userconf.txt` | Creates the user account (Bookworm requirement) |
| `ssh` | Enables SSH server on first boot |
| `companionpi-info.txt` | Records version, settings — read back on next inject |
| `packages/*.deb` | Bundled packages for offline install (optional) |

---

## Companion status page

While the RPi is installing, open `http://<hostname>.local` (port 80) in your browser. The page refreshes every 3 seconds and shows the full install log. A green **"Open Companion →"** button appears when installation is complete.

---

## Requirements

- Python 3.8+
- `flask>=3.0`
- `passlib>=1.7`
- `certifi>=2024.0`

---

## Related

- [companionpi-wifi](https://codeberg.org/jellec/companionpi-wifi) — the network manager that runs on the RPi
- [Bitfocus Companion](https://bitfocus.io/companion) — the software this is all built around
