"""
companion-imager — Local web app to inject firstrun.sh into a flashed RPi SD card.
Run:  python imager.py
Then open:  http://localhost:7070
"""

import os
import platform
import re
import subprocess
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)

REPO_URL_DEFAULT = "https://codeberg.org/jellec/companionpi-wifi"
IMAGER_VERSION = "1.0.1"

SCRIPT_DIR = Path(__file__).parent
TEMPLATE_FILE = SCRIPT_DIR / "firstrun-template.sh"


# --------------------------------------------------------------------------- #
#  Boot partition detection
# --------------------------------------------------------------------------- #

def find_boot_partitions():
    """Find mounted RPi OS boot partitions (contain cmdline.txt)."""
    system = platform.system()
    candidates = []

    if system == "Darwin":
        volumes = Path("/Volumes")
        if volumes.exists():
            for vol in volumes.iterdir():
                if (vol / "cmdline.txt").exists():
                    candidates.append({"path": str(vol), "name": vol.name})

    elif system == "Windows":
        import string
        for letter in string.ascii_uppercase[2:]:  # skip A, B
            drive = Path(f"{letter}:\\")
            if (drive / "cmdline.txt").exists():
                candidates.append({"path": str(drive), "name": f"{letter}:"})

    elif system == "Linux":
        for base in [Path("/media"), Path("/mnt")]:
            if base.exists():
                for vol in base.rglob("cmdline.txt"):
                    p = vol.parent
                    candidates.append({"path": str(p), "name": p.name})

    return candidates


# --------------------------------------------------------------------------- #
#  Password hashing (for userconf.txt)
# --------------------------------------------------------------------------- #

def hash_password(password):
    try:
        from passlib.hash import sha512_crypt
        return sha512_crypt.hash(password)
    except ImportError:
        pass
    # Fallback: openssl (available on Mac + Linux)
    try:
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"],
            input=password, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    raise RuntimeError("Cannot hash password — install passlib: pip install passlib")


# --------------------------------------------------------------------------- #
#  Inject
# --------------------------------------------------------------------------- #

def _write_unix(path: Path, text: str) -> None:
    """Write text file with Unix line endings (compatible with Python 3.8+)."""
    with open(path, "w", newline="\n") as f:
        f.write(text)


def inject(boot_path: str, hostname: str, wifi_country: str, repo_url: str,
           username: str, password: str) -> None:
    boot = Path(boot_path)

    if not (boot / "cmdline.txt").exists():
        raise ValueError(f"No cmdline.txt found in {boot_path} — is this an RPi boot partition?")

    # 1. Render firstrun.sh
    template = TEMPLATE_FILE.read_text()
    rendered = template
    for key, val in [
        ("{{HOSTNAME}}", hostname),
        ("{{WIFI_COUNTRY}}", wifi_country),
        ("{{REPO_URL}}", repo_url),
        ("{{USERNAME}}", username),
    ]:
        rendered = rendered.replace(key, val)

    firstrun = boot / "firstrun.sh"
    _write_unix(firstrun, rendered)

    # 2. Modify cmdline.txt — remove old firstrun entries, add new one
    cmdline = (boot / "cmdline.txt").read_text().strip()
    cmdline = re.sub(r"\s+systemd\.run=\S+", "", cmdline)
    cmdline = re.sub(r"\s+systemd\.run_success_action=\S+", "", cmdline)
    cmdline = re.sub(r"\s+systemd\.unit=\S+", "", cmdline)
    cmdline += (
        " systemd.run=/boot/firmware/firstrun.sh"
        " systemd.run_success_action=reboot"
        " systemd.unit=kernel-command-line.target"
    )
    _write_unix(boot / "cmdline.txt", cmdline.strip() + "\n")

    # 3. userconf.txt — required on Bookworm (no default pi user)
    pw_hash = hash_password(password)
    _write_unix(boot / "userconf.txt", f"{username}:{pw_hash}\n")

    # 4. ssh — enables SSH server on first boot
    (boot / "ssh").write_text("")

    # 5. companionpi-info.txt — version record on the boot partition

    from datetime import datetime
    info = (
        f"CompanionPi Imager\n"
        f"==================\n"
        f"Imager version : {IMAGER_VERSION}\n"
        f"Injected at    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Repo URL       : {repo_url}\n"
        f"\n"
        f"Configuration\n"
        f"-------------\n"
        f"Hostname       : {hostname}\n"
        f"Username       : {username}\n"
        f"WiFi country   : {wifi_country}\n"
        f"\n"
        f"First boot will install companionpi-wifi from the repo above.\n"
        f"Check /boot/firmware/firstrun.log on the RPi for install progress.\n"
    )
    _write_unix(boot / "companionpi-info.txt", info)


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    partitions = find_boot_partitions()
    return render_template("index.html", partitions=partitions,
                           repo_url_default=REPO_URL_DEFAULT)


@app.route("/inject", methods=["POST"])
def do_inject():
    boot_path    = request.form.get("boot_path", "").strip()
    hostname     = re.sub(r"[^a-zA-Z0-9\-]", "", request.form.get("hostname", "companion"))[:63]
    wifi_country = re.sub(r"[^A-Z]", "", request.form.get("wifi_country", "BE").upper())[:2]
    repo_url     = request.form.get("repo_url", REPO_URL_DEFAULT).strip()
    username     = re.sub(r"[^a-z0-9_]", "", request.form.get("username", "companion"))
    password     = request.form.get("password", "companion123")

    if not boot_path:
        flash("Select a boot partition first.", "error")
        return redirect(url_for("index"))

    try:
        inject(boot_path, hostname, wifi_country, repo_url, username, password)
        flash(
            f"Injected successfully into {boot_path}. "
            "Eject the SD card safely and insert it into your Raspberry Pi.",
            "success",
        )
    except Exception as e:
        flash(f"Injection failed: {e}", "error")

    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    port = 7070
    url = f"http://localhost:{port}"
    print(f"\n  CompanionPi Imager  →  {url}\n")
    # Open browser after a short delay
    Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
