"""
CompanionPi WiFi Injector — NAS webapp that generates SD card bundle ZIPs.
Run:  python imager.py  →  http://localhost:7070
"""

import io
import json
import os
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for

app = Flask(__name__)
app.secret_key = os.urandom(24)

REPO_URL_DEFAULT = "https://codeberg.org/jellec/companionpi-wifi"
IMAGER_VERSION   = "0.3.4"
AGENT_PORT       = 7072

SCRIPT_DIR      = Path(__file__).parent
TEMPLATE_FILE   = SCRIPT_DIR / "firstrun-template.sh"
WIFI_REPO_CACHE = SCRIPT_DIR / "wifi-repo-cache"

CMDLINE_ADD = (
    " systemd.run=/boot/firmware/firstrun.sh"
    " systemd.run_success_action=reboot"
    " systemd.run_failure_action=reboot"
    " systemd.unit=kernel-command-line.target"
)

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
            # Clone to a sibling temp dir, then move contents into the cache dir.
            # Cannot rmtree the cache dir itself — it may be a bind-mount point.
            tmp = WIFI_REPO_CACHE.parent / ".wifi-repo-cache.tmp"
            if tmp.exists():
                shutil.rmtree(tmp)
            with _repo_lock:
                _repo["step"] = "Cloning repo..."
            subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(tmp)],
                check=True, capture_output=True, timeout=120,
            )
            WIFI_REPO_CACHE.mkdir(parents=True, exist_ok=True)
            for item in WIFI_REPO_CACHE.iterdir():
                shutil.rmtree(item) if item.is_dir() else item.unlink()
            for item in tmp.iterdir():
                shutil.move(str(item), str(WIFI_REPO_CACHE / item.name))
            shutil.rmtree(tmp)

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
#  SD card detection & direct inject
# --------------------------------------------------------------------------- #

def find_boot_partitions() -> list:
    """Return mounted RPi boot partitions (have cmdline.txt)."""
    candidates = []
    for root in [Path("/Volumes"), Path("/media"), Path("/mnt")]:
        if not root.exists():
            continue
        try:
            for vol in root.iterdir():
                if (vol / "cmdline.txt").exists():
                    candidates.append({"path": str(vol), "name": vol.name})
        except PermissionError:
            pass
    return candidates


def inject_to_partition(boot_path: str, hostname: str, wifi_country: str,
                        username: str, pw_hash: str, ap_ssid: str,
                        ap_password: str, install_cups: bool):
    """Write bundle files directly to a mounted boot partition."""
    boot = Path(boot_path)
    if not (boot / "cmdline.txt").exists():
        raise ValueError(f"Not a valid RPi boot partition: {boot_path}")
    if not WIFI_REPO_CACHE.exists():
        raise ValueError("Wifi repo not cached — fetch it first.")

    firstrun = _render_firstrun(hostname, wifi_country, username, pw_hash,
                                ap_ssid, ap_password, install_cups)
    (boot / "firstrun.sh").write_text(firstrun)
    (boot / "userconf.txt").write_text(f"{username}:{pw_hash}\n")
    (boot / "ssh").touch()

    wifi_dst = boot / "companionpi-wifi"
    if wifi_dst.exists():
        shutil.rmtree(wifi_dst)
    shutil.copytree(str(WIFI_REPO_CACHE), str(wifi_dst),
                    ignore=shutil.ignore_patterns(".git", ".fetch_time", "*.tmp"))

    cmdline = (boot / "cmdline.txt").read_text().strip()
    for pat in [r"\s+systemd\.run=\S+", r"\s+systemd\.run_success_action=\S+",
                r"\s+systemd\.run_failure_action=\S+", r"\s+systemd\.unit=\S+"]:
        cmdline = re.sub(pat, "", cmdline)
    (boot / "cmdline.txt").write_text(cmdline.strip() + CMDLINE_ADD + "\n")

    info = (
        f"CompanionPi Injector\n====================\n"
        f"Injector version : {IMAGER_VERSION}\n"
        f"Injected         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\nConfiguration\n-------------\n"
        f"Hostname     : {hostname}\n"
        f"Username     : {username}\n"
        f"WiFi country : {wifi_country}\n"
        f"AP SSID      : {ap_ssid}\n"
        f"AP password  : {ap_password}\n"
    )
    (boot / "companionpi-info.txt").write_text(info)


# --------------------------------------------------------------------------- #
#  Bundle builder
# --------------------------------------------------------------------------- #

def _render_firstrun(hostname: str, wifi_country: str, username: str, password: str,
                     ap_ssid: str, ap_password: str, install_cups: bool,
                     image_type: str = "companionpi") -> str:
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
    return template


def build_bundle(hostname: str, wifi_country: str, username: str, password: str,
                 ap_ssid: str, ap_password: str, install_cups: bool) -> io.BytesIO:
    if not WIFI_REPO_CACHE.exists():
        raise ValueError("Wifi repo not cached — fetch it first.")

    repo_st = wifi_repo_status()
    pw_hash = hash_password(password)

    info = (
        f"CompanionPi Injector\n"
        f"====================\n"
        f"Injector version : {IMAGER_VERSION}\n"
        f"Bundle created   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\nConfiguration\n-------------\n"
        f"Hostname       : {hostname}\n"
        f"Username       : {username}\n"
        f"WiFi country   : {wifi_country}\n"
        f"AP SSID        : {ap_ssid}\n"
        f"AP password    : {ap_password}\n"
        f"\nBundled\n-------\n"
        f"  companionpi-wifi repo ({repo_st.get('size_mb', '?')} MB)\n"
        f"Install CUPS   : {'yes' if install_cups else 'no'}\n"
    )

    meta = {
        "hostname": hostname,
        "cmdline_strip": [
            r" systemd\.run=\S+",
            r" systemd\.run_success_action=\S+",
            r" systemd\.run_failure_action=\S+",
            r" systemd\.unit=\S+",
        ],
        "cmdline_add": CMDLINE_ADD.strip(),
        "injector_version": IMAGER_VERSION,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("firstrun.sh",
                    _render_firstrun(hostname, wifi_country, username, password,
                                     ap_ssid, ap_password, install_cups))
        zf.writestr("userconf.txt", f"{username}:{pw_hash}\n")
        zf.writestr("ssh", "")
        zf.writestr("companionpi-info.txt", info)
        zf.writestr("meta.json", json.dumps(meta, indent=2))

        skip = {".git", ".fetch_time"}
        for f in sorted(WIFI_REPO_CACHE.rglob("*")):
            if not f.is_file():
                continue
            if any(part in skip for part in f.parts):
                continue
            arcname = "companionpi-wifi/" + str(f.relative_to(WIFI_REPO_CACHE))
            zf.write(str(f), arcname)

    buf.seek(0)
    return buf


# --------------------------------------------------------------------------- #
#  Routes
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    repo = wifi_repo_status()
    with _repo_lock:
        repo_fetch = dict(_repo)
    return render_template("index.html",
                           repo_url_default=REPO_URL_DEFAULT,
                           imager_version=IMAGER_VERSION,
                           agent_port=AGENT_PORT,
                           repo=repo, repo_fetch=repo_fetch)


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


@app.route("/api/bundle", methods=["POST"])
def api_bundle():
    hostname     = re.sub(r"[^a-zA-Z0-9\-]", "", request.form.get("hostname", "companion"))[:63]
    wifi_country = re.sub(r"[^A-Z]", "", request.form.get("wifi_country", "BE").upper())[:2]
    password     = request.form.get("password", "companion123")
    ap_ssid      = request.form.get("ap_ssid", "CompanionPi").strip() or "CompanionPi"
    ap_password  = request.form.get("ap_password", "companion123").strip() or "companion123"
    install_cups = request.form.get("install_cups") == "on"
    try:
        buf = build_bundle(hostname, wifi_country, "companion", password,
                           ap_ssid, ap_password, install_cups)
        filename = f"companionpi-{hostname}-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
        return send_file(buf, mimetype="application/zip",
                         download_name=filename, as_attachment=True)
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("index"))


@app.route("/api/bundle-b64", methods=["POST"])
def api_bundle_b64():
    """Returns bundle as base64 JSON — used by companion-agent for local SD inject."""
    hostname     = re.sub(r"[^a-zA-Z0-9\-]", "", request.form.get("hostname", "companion"))[:63]
    wifi_country = re.sub(r"[^A-Z]", "", request.form.get("wifi_country", "BE").upper())[:2]
    password     = request.form.get("password", "companion123")
    ap_ssid      = request.form.get("ap_ssid", "CompanionPi").strip() or "CompanionPi"
    ap_password  = request.form.get("ap_password", "companion123").strip() or "companion123"
    install_cups = request.form.get("install_cups") == "on"
    try:
        import base64 as _b64
        buf = build_bundle(hostname, wifi_country, "companion", password,
                           ap_ssid, ap_password, install_cups)
        b64 = _b64.b64encode(buf.read()).decode()
        return json.dumps({"bundle_base64": b64, "hostname": hostname}), 200, {"Content-Type": "application/json"}
    except Exception as e:
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}


@app.route("/api/partitions")
def api_partitions():
    return json.dumps(find_boot_partitions()), 200, {"Content-Type": "application/json"}


@app.route("/api/inject", methods=["POST"])
def api_inject():
    hostname     = re.sub(r"[^a-zA-Z0-9\-]", "", request.form.get("hostname", "companion"))[:63]
    wifi_country = re.sub(r"[^A-Z]", "", request.form.get("wifi_country", "BE").upper())[:2]
    password     = request.form.get("password", "companion123")
    ap_ssid      = request.form.get("ap_ssid", "CompanionPi").strip() or "CompanionPi"
    ap_password  = request.form.get("ap_password", "companion123").strip() or "companion123"
    install_cups = request.form.get("install_cups") == "on"
    boot_path    = request.form.get("boot_path", "").strip()
    if not boot_path:
        return json.dumps({"error": "No SD card selected"}), 400, {"Content-Type": "application/json"}
    try:
        pw_hash = hash_password(password)
        inject_to_partition(boot_path, hostname, wifi_country, "companion",
                            pw_hash, ap_ssid, ap_password, install_cups)
        return json.dumps({"ok": True, "boot_path": boot_path}), 200, {"Content-Type": "application/json"}
    except Exception as e:
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7070))
    print(f"\n  CompanionPi Injector  →  http://0.0.0.0:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
