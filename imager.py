"""
CompanionPi Imager — inject firstrun.sh + wifi repo into a flashed CompanionPi SD card.
Run:  python imager.py  →  http://localhost:7070
"""

import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from threading import Timer

from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)

REPO_URL_DEFAULT = "https://codeberg.org/jellec/companionpi-wifi"
IMAGER_VERSION   = "0.3.0"

SCRIPT_DIR      = Path(__file__).parent
TEMPLATE_FILE   = SCRIPT_DIR / "firstrun-template.sh"
WIFI_REPO_CACHE = SCRIPT_DIR / "wifi-repo-cache"

STATIC_ASSETS = {
    "tailwind.js":   "https://cdn.tailwindcss.com",
    "alpine.min.js": "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js",
}


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


# --------------------------------------------------------------------------- #
#  Boot partition detection
# --------------------------------------------------------------------------- #

def find_boot_partitions():
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
        for letter in string.ascii_uppercase[2:]:
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


def read_previous_config(boot_path: str) -> dict:
    info_file = Path(boot_path) / "companionpi-info.txt"
    result = {}
    if not info_file.exists():
        return result
    try:
        for line in info_file.read_text().splitlines():
            for key, field in [
                ("Hostname", "hostname"),
                ("Username", "username"),
                ("WiFi country", "wifi_country"),
                ("Imager version", "prev_version"),
                ("AP SSID", "ap_ssid"),
                ("AP password", "ap_password"),
            ]:
                if line.startswith(key):
                    result[field] = line.split(":", 1)[-1].strip()
    except Exception:
        pass
    return result


# --------------------------------------------------------------------------- #
#  Wifi repo cache
# --------------------------------------------------------------------------- #

_repo = {"running": False, "done": False, "error": "", "step": ""}
_repo_lock = threading.Lock()


def wifi_repo_status() -> dict:
    if not WIFI_REPO_CACHE.exists():
        return {"cached": False, "age_s": None, "size_mb": None, "static_ok": False}
    marker = WIFI_REPO_CACHE / ".fetch_time"
    age_s = int(time.time() - marker.stat().st_mtime) if marker.exists() else None
    size = sum(f.stat().st_size for f in WIFI_REPO_CACHE.rglob("*") if f.is_file())
    static_ok = (
        (WIFI_REPO_CACHE / "webapp" / "static" / "tailwind.js").exists() and
        (WIFI_REPO_CACHE / "webapp" / "static" / "alpine.min.js").exists()
    )
    return {
        "cached": True,
        "age_s": age_s,
        "size_mb": round(size / 1024 / 1024, 1),
        "static_ok": static_ok,
    }


def _do_fetch_repo(repo_url: str):
    with _repo_lock:
        _repo.update(running=True, done=False, error="", step="Starting...")
    try:
        git_dir = WIFI_REPO_CACHE / ".git"
        if git_dir.exists():
            with _repo_lock:
                _repo["step"] = "Updating repo..."
            subprocess.run(
                ["git", "-C", str(WIFI_REPO_CACHE), "fetch", "--depth=1", "origin"],
                check=True, capture_output=True, timeout=60,
            )
            subprocess.run(
                ["git", "-C", str(WIFI_REPO_CACHE), "reset", "--hard", "FETCH_HEAD"],
                check=True, capture_output=True, timeout=30,
            )
        else:
            if WIFI_REPO_CACHE.exists():
                shutil.rmtree(WIFI_REPO_CACHE)
            with _repo_lock:
                _repo["step"] = "Cloning repo..."
            subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(WIFI_REPO_CACHE)],
                check=True, capture_output=True, timeout=120,
            )

        static_dir = WIFI_REPO_CACHE / "webapp" / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        for name, url in STATIC_ASSETS.items():
            with _repo_lock:
                _repo["step"] = f"Downloading {name}..."
            req = urllib.request.Request(
                url, headers={"User-Agent": f"companion-imager/{IMAGER_VERSION}"}
            )
            with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as r:
                (static_dir / name).write_bytes(r.read())

        (WIFI_REPO_CACHE / ".fetch_time").touch()
        with _repo_lock:
            _repo.update(running=False, done=True, step="Done")
    except Exception as e:
        with _repo_lock:
            _repo.update(running=False, done=False, error=str(e), step="Failed")


# --------------------------------------------------------------------------- #
#  Password hashing
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    try:
        from passlib.hash import sha512_crypt
        return sha512_crypt.hash(password)
    except ImportError:
        pass
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
    with open(path, "w", newline="\n") as f:
        f.write(text)


def inject(boot_path: str, hostname: str, wifi_country: str,
           username: str, password: str, ap_ssid: str = "CompanionPi",
           ap_password: str = "companion123", install_cups: bool = False,
           image_type: str = "companionpi") -> None:
    boot = Path(boot_path)

    if not (boot / "cmdline.txt").exists():
        raise ValueError(f"No cmdline.txt in {boot_path} — is this an RPi boot partition?")
    if not WIFI_REPO_CACHE.exists():
        raise ValueError("Wifi repo not cached — click 'Fetch repo' first.")

    # 1. Copy bundled wifi repo to SD card
    wifi_dest = boot / "companionpi-wifi"
    if wifi_dest.exists():
        shutil.rmtree(wifi_dest)
    shutil.copytree(
        str(WIFI_REPO_CACHE), str(wifi_dest),
        ignore=shutil.ignore_patterns(".git", ".fetch_time"),
    )

    # 2. Render firstrun.sh
    template = TEMPLATE_FILE.read_text()
    for key, val in [
        ("{{HOSTNAME}}", hostname),
        ("{{WIFI_COUNTRY}}", wifi_country),
        ("{{USERNAME}}", username),
        ("{{PASSWORD}}", password),
        ("{{AP_SSID}}", ap_ssid),
        ("{{AP_PASSWORD}}", ap_password),
        ("{{INSTALL_CUPS}}", "true" if install_cups else "false"),
        ("{{IMAGE_TYPE}}", image_type),
    ]:
        template = template.replace(key, val)
    _write_unix(boot / "firstrun.sh", template)

    # 3. cmdline.txt — add systemd.run trigger
    cmdline = (boot / "cmdline.txt").read_text().strip()
    for pattern in [r"\s+systemd\.run=\S+", r"\s+systemd\.run_success_action=\S+",
                    r"\s+systemd\.run_failure_action=\S+", r"\s+systemd\.unit=\S+"]:
        cmdline = re.sub(pattern, "", cmdline)
    cmdline += (
        " systemd.run=/boot/firmware/firstrun.sh"
        " systemd.run_success_action=reboot"
        " systemd.run_failure_action=reboot"
        " systemd.unit=kernel-command-line.target"
    )
    _write_unix(boot / "cmdline.txt", cmdline.strip() + "\n")

    # 4. userconf.txt — set password for companion user
    pw_hash = hash_password(password)
    _write_unix(boot / "userconf.txt", f"{username}:{pw_hash}\n")

    # 5. SSH enable marker
    (boot / "ssh").write_text("")

    # 6. companionpi-info.txt
    repo_st = wifi_repo_status()
    info = (
        f"CompanionPi Imager\n"
        f"==================\n"
        f"Imager version : {IMAGER_VERSION}\n"
        f"Injected at    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\n"
        f"Configuration\n"
        f"-------------\n"
        f"Hostname       : {hostname}\n"
        f"Username       : {username}\n"
        f"WiFi country   : {wifi_country}\n"
        f"AP SSID        : {ap_ssid}\n"
        f"AP password    : {ap_password}\n"
        f"\n"
        f"Bundled\n"
        f"-------\n"
        f"  companionpi-wifi repo ({repo_st.get('size_mb', '?')} MB)\n"
        f"Install CUPS   : {'yes' if install_cups else 'no'}\n"
    )
    _write_unix(boot / "companionpi-info.txt", info)


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    partitions = find_boot_partitions()
    prev = {}
    if partitions:
        prev = read_previous_config(partitions[0]["path"])
    repo = wifi_repo_status()
    with _repo_lock:
        repo_fetch = dict(_repo)
    return render_template("index.html", partitions=partitions,
                           repo_url_default=REPO_URL_DEFAULT,
                           imager_version=IMAGER_VERSION,
                           prev=prev, repo=repo, repo_fetch=repo_fetch)


@app.route("/api/repo/fetch", methods=["POST"])
def api_repo_fetch():
    with _repo_lock:
        if _repo["running"]:
            return json.dumps({"error": "Already running"}), 409
    data = request.get_json(force=True) or {}
    repo_url = data.get("repo_url", REPO_URL_DEFAULT)
    threading.Thread(target=_do_fetch_repo, args=(repo_url,), daemon=True).start()
    return json.dumps({"status": "started"}), 200


@app.route("/api/repo/status")
def api_repo_status():
    with _repo_lock:
        state = dict(_repo)
    state.update(wifi_repo_status())
    return json.dumps(state), 200, {"Content-Type": "application/json"}


@app.route("/inject", methods=["POST"])
def do_inject():
    boot_path    = request.form.get("boot_path", "").strip()
    hostname     = re.sub(r"[^a-zA-Z0-9\-]", "", request.form.get("hostname", "companion"))[:63]
    wifi_country = re.sub(r"[^A-Z]", "", request.form.get("wifi_country", "BE").upper())[:2]
    password     = request.form.get("password", "companion123")
    ap_ssid      = request.form.get("ap_ssid", "CompanionPi").strip() or "CompanionPi"
    ap_password  = request.form.get("ap_password", "companion123").strip() or "companion123"
    install_cups = request.form.get("install_cups") == "on"

    if not boot_path:
        flash("Select a boot partition first.", "error")
        return redirect(url_for("index"))

    try:
        inject(boot_path, hostname, wifi_country, "companion", password,
               ap_ssid, ap_password, install_cups)
        flash(
            f"Injected into {boot_path}. Eject the SD card safely and insert into your Raspberry Pi.",
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
    url  = f"http://localhost:{port}"
    print(f"\n  CompanionPi Imager  →  {url}\n")
    Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
