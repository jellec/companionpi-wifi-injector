"""
companion-imager — Local web app to inject firstrun.sh into a flashed RPi SD card.
Run:  python imager.py
Then open:  http://localhost:7070
"""

import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import threading
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from threading import Timer

from flask import Flask, Response, flash, redirect, render_template, request, stream_with_context, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)

REPO_URL_DEFAULT = "https://codeberg.org/jellec/companionpi-wifi"
IMAGER_VERSION = "0.2.3"

SCRIPT_DIR   = Path(__file__).parent
TEMPLATE_FILE = SCRIPT_DIR / "firstrun-template.sh"
PACKAGES_DIR  = SCRIPT_DIR / "packages"
PACKAGES_DIR.mkdir(exist_ok=True)

COMPANION_RELEASES_URL = "https://api.github.com/repos/bitfocus/companion/releases?per_page=15"


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

# Download state
_dl = {"running": False, "done": False, "error": "", "file": "",
       "size": 0, "downloaded": 0, "version": "", "name": ""}
_dl_lock = threading.Lock()


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


def detect_image_type(boot_path: str) -> str:
    """Detect whether this is a CompanionPi or standard RPi OS boot partition."""
    boot = Path(boot_path)
    # CompanionPi image has specific markers
    for marker in ["companion.txt", "companionpi.txt", "companion/", ".companion"]:
        if (boot / marker).exists():
            return "companionpi"
    # Check cmdline.txt for CompanionPi-specific content
    cmdline = boot / "cmdline.txt"
    if cmdline.exists():
        content = cmdline.read_text()
        if "companion" in content.lower():
            return "companionpi"
    return "rpios"


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
                ("Repo URL", "repo_url"),
                ("Imager version", "prev_version"),
                ("AP SSID", "ap_ssid"),
                ("AP password", "ap_password"),
            ]:
                if line.startswith(f"{key}"):
                    result[field] = line.split(":", 1)[-1].strip()
    except Exception:
        pass
    return result


# --------------------------------------------------------------------------- #
#  Package cache
# --------------------------------------------------------------------------- #

def fetch_companion_releases():
    """Fetch available Companion ARM64 releases from GitHub."""
    try:
        req = urllib.request.Request(
            COMPANION_RELEASES_URL,
            headers={"User-Agent": f"companion-imager/{IMAGER_VERSION}"}
        )
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=10) as r:
            releases = json.loads(r.read())
        result = []
        for rel in releases:
            if rel.get("prerelease") or rel.get("draft"):
                continue
            tag = rel["tag_name"]
            for asset in rel["assets"]:
                name = asset["name"].lower()
                if "arm64.deb" in name and "linux" in name:
                    result.append({
                        "version": tag,
                        "name":    asset["name"],
                        "url":     asset["browser_download_url"],
                        "size_mb": round(asset["size"] / 1024 / 1024, 1),
                        "cached":  (PACKAGES_DIR / asset["name"]).exists(),
                    })
                    break
            if len(result) >= 6:
                break
        return result
    except Exception as e:
        return {"error": str(e)}


def get_cached_packages():
    """Return all .deb files in the packages cache."""
    pkgs = []
    for f in sorted(PACKAGES_DIR.glob("*.deb"), key=lambda x: x.stat().st_mtime, reverse=True):
        size_mb = round(f.stat().st_size / 1024 / 1024, 1)
        pkgs.append({"name": f.name, "size_mb": size_mb, "path": str(f)})
    return pkgs


def boot_free_mb(boot_path: str) -> float:
    try:
        st = shutil.disk_usage(boot_path)
        return round(st.free / 1024 / 1024, 1)
    except Exception:
        return 9999.0


def _do_download(url: str, filename: str, version: str):
    dest = PACKAGES_DIR / filename
    try:
        with _dl_lock:
            _dl.update(running=True, done=False, error="", file=filename,
                       version=version, name=filename, downloaded=0, size=0)
        req = urllib.request.Request(url, headers={"User-Agent": f"companion-imager/{IMAGER_VERSION}"})
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            with _dl_lock:
                _dl["size"] = total
            with open(dest, "wb") as f:
                downloaded = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    with _dl_lock:
                        _dl["downloaded"] = downloaded
        with _dl_lock:
            _dl.update(running=False, done=True, downloaded=total or dest.stat().st_size)
    except Exception as e:
        if dest.exists():
            dest.unlink()
        with _dl_lock:
            _dl.update(running=False, done=False, error=str(e))


# --------------------------------------------------------------------------- #
#  Password hashing
# --------------------------------------------------------------------------- #

def hash_password(password):
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


def inject(boot_path: str, hostname: str, wifi_country: str, repo_url: str,
           username: str, password: str, ap_ssid: str = "CompanionPi",
           ap_password: str = "companion123", install_cups: bool = False,
           package_files: list = None, image_type: str = "rpios") -> None:
    boot = Path(boot_path)

    if not (boot / "cmdline.txt").exists():
        raise ValueError(f"No cmdline.txt in {boot_path} — is this an RPi boot partition?")

    # 1. Copy bundled packages to SD
    pkg_names = []
    if package_files:
        pkg_dir = boot / "packages"
        pkg_dir.mkdir(exist_ok=True)
        for pkg in package_files:
            src = PACKAGES_DIR / pkg
            if src.exists():
                free = boot_free_mb(boot_path)
                need = src.stat().st_size / 1024 / 1024
                if need > free - 20:
                    raise ValueError(
                        f"Not enough space on boot partition: need {need:.0f} MB, "
                        f"only {free:.0f} MB free. Use a larger SD card or skip offline packages."
                    )
                shutil.copy2(src, pkg_dir / pkg)
                pkg_names.append(pkg)

    # 2. Render firstrun.sh
    template = TEMPLATE_FILE.read_text()
    rendered = template
    for key, val in [
        ("{{HOSTNAME}}", hostname),
        ("{{WIFI_COUNTRY}}", wifi_country),
        ("{{REPO_URL}}", repo_url),
        ("{{USERNAME}}", username),
        ("{{AP_SSID}}", ap_ssid),
        ("{{AP_PASSWORD}}", ap_password),
        ("{{INSTALL_CUPS}}", "true" if install_cups else "false"),
        ("{{IMAGE_TYPE}}", image_type),
    ]:
        rendered = rendered.replace(key, val)

    _write_unix(boot / "firstrun.sh", rendered)

    # 3. cmdline.txt
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

    # 4. userconf.txt
    pw_hash = hash_password(password)
    _write_unix(boot / "userconf.txt", f"{username}:{pw_hash}\n")

    # 5. ssh
    (boot / "ssh").write_text("")

    # 6. companionpi-info.txt
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
        f"AP SSID        : {ap_ssid}\n"
        f"AP password    : {ap_password}\n"
        f"\n"
        f"Bundled packages\n"
        f"----------------\n"
    )
    if pkg_names:
        for p in pkg_names:
            info += f"  {p}\n"
    else:
        info += "  (none — will install from internet)\n"
    info += f"\nInstall CUPS   : {'yes' if install_cups else 'no'}\n"
    _write_unix(boot / "companionpi-info.txt", info)


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    partitions = find_boot_partitions()
    prev = {}
    detected_type = "rpios"
    if partitions:
        prev = read_previous_config(partitions[0]["path"])
        detected_type = detect_image_type(partitions[0]["path"])
    cached = get_cached_packages()
    return render_template("index.html", partitions=partitions,
                           repo_url_default=REPO_URL_DEFAULT,
                           imager_version=IMAGER_VERSION,
                           prev=prev, cached_packages=cached,
                           detected_image_type=detected_type)


@app.route("/api/releases")
def api_releases():
    releases = fetch_companion_releases()
    return json.dumps(releases), 200, {"Content-Type": "application/json"}


@app.route("/api/import-deb", methods=["POST"])
def api_import_deb():
    """Import a locally downloaded .deb or .tar.gz Companion package."""
    if "file" not in request.files:
        return json.dumps({"error": "No file"}), 400
    f = request.files["file"]
    fname = f.filename.lower()
    if not (fname.endswith(".deb") or fname.endswith(".tar.gz") or fname.endswith(".tgz")):
        return json.dumps({"error": "Only .deb or .tar.gz/.tgz files accepted"}), 400

    safe_name = re.sub(r"[^\w\-\.]", "_", f.filename)
    dest = PACKAGES_DIR / safe_name
    f.save(dest)
    size_mb = round(dest.stat().st_size / 1024 / 1024, 1)
    return json.dumps({"ok": True, "name": safe_name, "size_mb": size_mb})


@app.route("/api/download", methods=["POST"])
def api_download():
    with _dl_lock:
        if _dl["running"]:
            return json.dumps({"error": "Download already running"}), 409
    data   = request.get_json(force=True)
    url    = data.get("url", "")
    name   = data.get("name", "")
    version = data.get("version", "")
    if not url or not name:
        return json.dumps({"error": "Missing url or name"}), 400
    if (PACKAGES_DIR / name).exists():
        return json.dumps({"status": "already_cached", "name": name}), 200
    threading.Thread(target=_do_download, args=(url, name, version), daemon=True).start()
    return json.dumps({"status": "started"}), 200


@app.route("/api/download/status")
def api_download_status():
    with _dl_lock:
        state = dict(_dl)
    pct = 0
    if state["size"] > 0:
        pct = round(state["downloaded"] / state["size"] * 100)
    state["pct"] = pct
    state["downloaded_mb"] = round(state["downloaded"] / 1024 / 1024, 1)
    state["size_mb"] = round(state["size"] / 1024 / 1024, 1)
    return json.dumps(state), 200, {"Content-Type": "application/json"}


@app.route("/api/package/delete", methods=["POST"])
def api_package_delete():
    name = request.get_json(force=True).get("name", "")
    if name and re.match(r"^[\w\-\.]+\.deb$", name):
        f = PACKAGES_DIR / name
        if f.exists():
            f.unlink()
    return json.dumps({"ok": True})


@app.route("/inject", methods=["POST"])
def do_inject():
    boot_path    = request.form.get("boot_path", "").strip()
    hostname     = re.sub(r"[^a-zA-Z0-9\-]", "", request.form.get("hostname", "companion"))[:63]
    wifi_country = re.sub(r"[^A-Z]", "", request.form.get("wifi_country", "BE").upper())[:2]
    repo_url     = request.form.get("repo_url", REPO_URL_DEFAULT).strip()
    username     = re.sub(r"[^a-z0-9_]", "", request.form.get("username", "companion"))
    password     = request.form.get("password", "companion123")
    ap_ssid      = request.form.get("ap_ssid", "CompanionPi").strip() or "CompanionPi"
    ap_password  = request.form.get("ap_password", "companion123").strip() or "companion123"
    install_cups = request.form.get("install_cups") == "on"
    image_type   = request.form.get("image_type", "rpios")
    package_files = request.form.getlist("bundle_pkg")

    if not boot_path:
        flash("Select a boot partition first.", "error")
        return redirect(url_for("index"))

    try:
        inject(boot_path, hostname, wifi_country, repo_url, username, password,
               ap_ssid, ap_password, install_cups, package_files, image_type)
        pkg_note = f" — {len(package_files)} package(s) bundled offline" if package_files else " — internet install"
        flash(
            f"Injected successfully into {boot_path}{pkg_note}. "
            "Eject the SD card safely and insert into your Raspberry Pi.",
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
