"""
CompanionPi Injector — standalone desktop app.
Dubbelklik .app (Mac) of .exe (Windows) — browser opent automatisch.
"""

import io
import json
import os
import re
import shutil
import socket
import ssl
import string
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_file, url_for

APP_VERSION      = "0.4.5"
APP_BUILD_DATE   = "unknown"   # replaced by CI: sed -i "s/APP_BUILD_DATE.*=.*/APP_BUILD_DATE = \"DATE\"/"
PORT             = 7070
REPO_URL_DEFAULT = "https://codeberg.org/jellec/companionpi-wifi"
GITHUB_RELEASE   = "https://api.github.com/repos/jellec/companionpi-wifi-injector/releases/tags/latest"
GITHUB_ACTIONS   = "https://api.github.com/repos/jellec/companionpi-wifi-injector/actions/runs"

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

# Works in dev (plain Python) and in PyInstaller bundle
BASE_DIR = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent

app = Flask(__name__,
            template_folder=str(BASE_DIR / "templates"),
            static_folder=str(BASE_DIR / "static"))
app.secret_key = os.urandom(24)


# ── Data directory (platform-specific, persists across runs) ─────────────────

def _data_dir() -> Path:
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "CompanionPi"
    elif sys.platform == "win32":
        d = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CompanionPi"
    else:
        d = Path.home() / ".local" / "share" / "companionpi"
    d.mkdir(parents=True, exist_ok=True)
    return d


WIFI_REPO_CACHE = _data_dir() / "wifi-repo-cache"
TEMPLATE_FILE   = BASE_DIR / "firstrun-template.sh"


# ── SSL context ───────────────────────────────────────────────────────────────

def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


# ── Auto-update ───────────────────────────────────────────────────────────────

_update = {
    "available": False, "latest": "", "status": "idle",
    "progress": 0, "error": "", "download_path": "",
    "download_url": "", "asset_name": "",
}
_update_lock = threading.Lock()


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in re.sub(r"[^0-9.]", "", v).split("."))
    except ValueError:
        return (0,)


def _find_app_bundle() -> "Path | None":
    """Return the running .app bundle path on macOS (PyInstaller only)."""
    if not hasattr(sys, "_MEIPASS") or sys.platform != "darwin":
        return None
    for p in Path(sys.executable).parents:
        if p.suffix == ".app":
            return p
    return None


def _check_update_async():
    try:
        req = urllib.request.Request(
            GITHUB_RELEASE,
            headers={"User-Agent": f"companionpi-app/{APP_VERSION}",
                     "Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=8) as r:
            data = json.loads(r.read())

        m = re.search(r"v?(\d+\.\d+\.\d+)", data.get("name", ""))
        if not m:
            return
        latest = m.group(1)
        if _version_tuple(latest) <= _version_tuple(APP_VERSION):
            return

        asset_name = {
            "darwin": "companion-app-macos.zip",
            "win32":  "companion-app.exe",
            "linux":  "companion-app-linux",
        }.get(sys.platform, "")
        asset_url = next(
            (a["browser_download_url"] for a in data.get("assets", [])
             if a["name"] == asset_name), "")

        with _update_lock:
            _update.update(available=True, latest=latest, status="available",
                           download_url=asset_url, asset_name=asset_name)
    except Exception:
        pass


def _do_install_update():
    import tempfile
    with _update_lock:
        url       = _update["download_url"]
        asset     = _update["asset_name"]

    if not url:
        with _update_lock:
            _update.update(status="error", error="Geen download-URL gevonden")
        return

    try:
        with _update_lock:
            _update.update(status="downloading", progress=0)

        tmp = Path(tempfile.mkdtemp(prefix="cpw-update-"))
        dl  = tmp / asset

        req = urllib.request.Request(url, headers={"User-Agent": f"companionpi-app/{APP_VERSION}"})
        with urllib.request.urlopen(req, context=_ssl_context()) as r:
            total, received = int(r.headers.get("Content-Length", 0) or 0), 0
            with open(dl, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    if total:
                        with _update_lock:
                            _update["progress"] = int(received * 100 / total)

        with _update_lock:
            _update.update(status="installing", progress=100)

        if sys.platform == "darwin":
            _install_macos(tmp, dl)
        elif sys.platform == "win32":
            _install_windows(dl)
        else:
            with _update_lock:
                _update.update(status="ready", download_path=str(dl))

    except Exception as e:
        with _update_lock:
            _update.update(status="error", error=str(e))


def _install_macos(tmp: Path, zip_path: Path):
    """Extract new .app, write a replace-and-relaunch script, then exit."""
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp / "extracted")

    new_app = tmp / "extracted" / "companion-app.app"
    if not new_app.exists():
        raise RuntimeError("companion-app.app niet gevonden in het zip-archief")

    old_app = _find_app_bundle()
    if not old_app:
        # Running from source or unknown location — just show the download
        with _update_lock:
            _update.update(status="ready", download_path=str(zip_path))
        return

    script = tmp / "cpw_update.sh"
    script.write_text(
        "#!/bin/bash\n"
        "sleep 1.5\n"
        f'rsync -a --delete "{new_app}/" "{old_app}/"\n'
        f'xattr -cr "{old_app}" 2>/dev/null\n'
        f'open "{old_app}"\n'
    )
    os.chmod(script, 0o755)
    subprocess.Popen(["/bin/bash", str(script)],
                     start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with _update_lock:
        _update.update(status="relaunching")
    time.sleep(0.3)
    sys.exit(0)


def _install_windows(exe_path: Path):
    """Rename running exe, write batch script to swap in new one, relaunch."""
    current = Path(sys.executable)
    old_bak = current.with_suffix(".bak.exe")

    import tempfile
    bat = Path(tempfile.gettempdir()) / "cpw_update.bat"
    bat.write_text(
        "@echo off\n"
        "timeout /t 2 /nobreak >nul\n"
        f'del /f "{old_bak}" 2>nul\n'
        f'move /y "{exe_path}" "{current}"\n'
        f'start "" "{current}"\n'
    )
    shutil.move(str(current), str(old_bak))

    with _update_lock:
        _update.update(status="relaunching")
    subprocess.Popen(["cmd", "/c", str(bat)],
                     start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    sys.exit(0)


# ── Wifi repo cache ───────────────────────────────────────────────────────────

_repo      = {"running": False, "done": False, "error": "", "step": ""}
_repo_lock = threading.Lock()


def wifi_repo_status() -> dict:
    if not WIFI_REPO_CACHE.exists():
        return {"cached": False, "age_s": None, "size_mb": None, "static_ok": False}
    marker = WIFI_REPO_CACHE / ".fetch_time"
    age_s  = int(time.time() - marker.stat().st_mtime) if marker.exists() else None
    size   = sum(f.stat().st_size for f in WIFI_REPO_CACHE.rglob("*") if f.is_file())
    static_ok = (
        (WIFI_REPO_CACHE / "webapp" / "static" / "tailwind.js").exists() and
        (WIFI_REPO_CACHE / "webapp" / "static" / "alpine.min.js").exists()
    )
    return {"cached": True, "age_s": age_s,
            "size_mb": round(size / 1024 / 1024, 1), "static_ok": static_ok}


def _download_flask_wheels(dest: Path):
    """Download Flask + deps as ARM64/pure-Python wheels via PyPI JSON API."""
    deps = {
        "flask": "3.0.3",
        "werkzeug": "3.0.3",
        "jinja2": "3.1.4",
        "click": "8.1.7",
        "itsdangerous": "2.2.0",
        "blinker": "1.8.2",
        "markupsafe": "2.1.5",
    }
    ctx = _ssl_context()
    for pkg, ver in deps.items():
        try:
            req = urllib.request.Request(
                f"https://pypi.org/pypi/{pkg}/{ver}/json",
                headers={"User-Agent": f"companionpi-app/{APP_VERSION}"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                data = json.loads(r.read())

            wheels = [u for u in data["urls"] if u["packagetype"] == "bdist_wheel"]

            def _rank(u):
                fn = u["filename"]
                if "linux_aarch64" in fn or "manylinux" in fn and "aarch64" in fn:
                    return 0
                if "none-any" in fn:
                    return 1
                return 99

            wheels.sort(key=_rank)
            if not wheels or _rank(wheels[0]) == 99:
                continue

            filename = wheels[0]["filename"]
            whl_path = dest / filename
            if whl_path.exists():
                continue
            whl_req = urllib.request.Request(
                wheels[0]["url"],
                headers={"User-Agent": f"companionpi-app/{APP_VERSION}"})
            with urllib.request.urlopen(whl_req, context=ctx, timeout=30) as r:
                whl_path.write_bytes(r.read())
        except Exception:
            pass  # best-effort per package


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
                check=True, capture_output=True, timeout=60)
            subprocess.run(
                ["git", "-C", str(WIFI_REPO_CACHE), "reset", "--hard", "FETCH_HEAD"],
                check=True, capture_output=True, timeout=30)
        else:
            with _repo_lock:
                _repo["step"] = "Cloning repo..."
            if WIFI_REPO_CACHE.exists():
                shutil.rmtree(WIFI_REPO_CACHE)
            subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(WIFI_REPO_CACHE)],
                check=True, capture_output=True, timeout=120)

        static_dir = WIFI_REPO_CACHE / "webapp" / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        for name, url in STATIC_ASSETS.items():
            with _repo_lock:
                _repo["step"] = f"Downloading {name}..."
            req = urllib.request.Request(
                url, headers={"User-Agent": f"companionpi-app/{APP_VERSION}"})
            with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as r:
                (static_dir / name).write_bytes(r.read())

        # Download Flask wheels for offline RPi install (ARM64 + pure-Python)
        # Uses PyPI JSON API directly — no pip required, no platform issues
        with _repo_lock:
            _repo["step"] = "Downloading Python wheels..."
        wheels_dir = WIFI_REPO_CACHE / "wheels"
        wheels_dir.mkdir(exist_ok=True)
        if not list(wheels_dir.glob("Flask*.whl")):
            _download_flask_wheels(wheels_dir)

        (WIFI_REPO_CACHE / ".fetch_time").touch()
        with _repo_lock:
            _repo.update(running=False, done=True, step="Done")
    except Exception as e:
        with _repo_lock:
            _repo.update(running=False, done=False, error=str(e), step="Failed")


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    try:
        from passlib.hash import sha512_crypt
        return sha512_crypt.hash(password)
    except ImportError:
        pass
    try:
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"],
            input=password, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    raise RuntimeError("Cannot hash password — install passlib: pip install passlib[bcrypt]")


# ── SD card detection ─────────────────────────────────────────────────────────

def find_boot_partitions() -> list:
    candidates = []
    if sys.platform == "win32":
        for drive in string.ascii_uppercase:
            p = Path(f"{drive}:/")
            try:
                if p.exists() and (p / "cmdline.txt").exists():
                    candidates.append({"path": str(p), "name": f"{drive}:"})
            except PermissionError:
                pass
    else:
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


# ── Inject ────────────────────────────────────────────────────────────────────

def _render_firstrun(hostname: str, wifi_country: str, username: str, password: str,
                     ap_ssid: str, ap_password: str, install_cups: bool) -> str:
    template = TEMPLATE_FILE.read_text()
    for key, val in [
        ("{{HOSTNAME}}", hostname),
        ("{{WIFI_COUNTRY}}", wifi_country),
        ("{{USERNAME}}", username),
        ("{{PASSWORD}}", password),
        ("{{AP_SSID}}", ap_ssid),
        ("{{AP_PASSWORD}}", ap_password),
        ("{{INSTALL_CUPS}}", "true" if install_cups else "false"),
        ("{{IMAGE_TYPE}}", "companionpi"),
    ]:
        template = template.replace(key, val)
    return template


_FAT32_IGNORE = {".git", ".fetch_time"}


def _fat32_copytree(src: Path, dst: Path) -> None:
    """Recursively copy src→dst using only shutil.copyfile — safe on FAT32.

    shutil.copytree calls os.utime/os.chmod on directories after creating them.
    FAT32 volumes on macOS raise OSError for those metadata calls, so we skip
    them entirely and only copy raw file bytes.
    """
    dst.mkdir(exist_ok=True)
    for item in src.iterdir():
        if item.name in _FAT32_IGNORE or item.name.endswith(".tmp"):
            continue
        target = dst / item.name
        if item.is_dir():
            _fat32_copytree(item, target)
        elif item.is_file():
            shutil.copyfile(str(item), str(target))


def inject_to_partition(boot_path: str, hostname: str, wifi_country: str,
                        username: str, pw_hash: str, ap_ssid: str,
                        ap_password: str, install_cups: bool):
    boot = Path(boot_path)
    if not (boot / "cmdline.txt").exists():
        raise ValueError(f"Geen geldige RPi boot-partitie: {boot_path}")

    if not (WIFI_REPO_CACHE / "install.sh").exists():
        raise ValueError(
            "Wifi repo niet gevonden of leeg — klik eerst 'Fetch repo' in stap 1.")

    firstrun = _render_firstrun(hostname, wifi_country, username, pw_hash,
                                ap_ssid, ap_password, install_cups)
    (boot / "firstrun.sh").write_text(firstrun)
    (boot / "userconf.txt").write_text(f"{username}:{pw_hash}\n")
    (boot / "ssh").touch()

    wifi_dst = boot / "companionpi-wifi"
    if wifi_dst.exists():
        shutil.rmtree(str(wifi_dst))
    _fat32_copytree(WIFI_REPO_CACHE, wifi_dst)

    if not (wifi_dst / "install.sh").exists():
        raise RuntimeError(
            "companionpi-wifi kopie mislukt — probeer opnieuw of herstart de app.")

    cmdline = (boot / "cmdline.txt").read_text().strip()
    for pat in [r"\s+systemd\.run=\S+", r"\s+systemd\.run_success_action=\S+",
                r"\s+systemd\.run_failure_action=\S+", r"\s+systemd\.unit=\S+"]:
        cmdline = re.sub(pat, "", cmdline)
    (boot / "cmdline.txt").write_text(cmdline.strip() + CMDLINE_ADD + "\n")

    (boot / "companionpi-info.txt").write_text(
        f"CompanionPi Injector\n"
        f"====================\n"
        f"App version  : {APP_VERSION}\n"
        f"Injected     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\nConfiguration\n-------------\n"
        f"Hostname     : {hostname}\n"
        f"Username     : {username}\n"
        f"WiFi country : {wifi_country}\n"
        f"AP SSID      : {ap_ssid}\n"
        f"AP password  : {ap_password}\n"
    )


# ── Bundle builder (download fallback) ────────────────────────────────────────

def build_bundle(hostname: str, wifi_country: str, username: str, password: str,
                 ap_ssid: str, ap_password: str, install_cups: bool) -> io.BytesIO:
    if not (WIFI_REPO_CACHE / "install.sh").exists():
        raise ValueError("Wifi repo ontbreekt of is corrupt — klik Re-fetch in stap 1.")

    repo_st = wifi_repo_status()
    pw_hash = hash_password(password)

    meta = {
        "hostname": hostname,
        "cmdline_strip": [
            r" systemd\.run=\S+", r" systemd\.run_success_action=\S+",
            r" systemd\.run_failure_action=\S+", r" systemd\.unit=\S+",
        ],
        "cmdline_add": CMDLINE_ADD.strip(),
        "app_version": APP_VERSION,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("firstrun.sh",
                    _render_firstrun(hostname, wifi_country, username, pw_hash,
                                     ap_ssid, ap_password, install_cups))
        zf.writestr("userconf.txt", f"{username}:{pw_hash}\n")
        zf.writestr("ssh", "")
        zf.writestr("meta.json", json.dumps(meta, indent=2))
        zf.writestr("companionpi-info.txt",
            f"CompanionPi Injector\n====================\n"
            f"App version    : {APP_VERSION}\n"
            f"Bundle created : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
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
        skip = {".git", ".fetch_time"}
        for f in sorted(WIFI_REPO_CACHE.rglob("*")):
            if not f.is_file() or any(p in skip for p in f.parts):
                continue
            zf.write(str(f), "companionpi-wifi/" + str(f.relative_to(WIFI_REPO_CACHE)))

    buf.seek(0)
    return buf


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    repo = wifi_repo_status()
    with _repo_lock:
        repo_fetch = dict(_repo)
    with _update_lock:
        update_info = dict(_update)
    return render_template("index.html",
                           repo_url_default=REPO_URL_DEFAULT,
                           app_version=APP_VERSION,
                           app_build_date=APP_BUILD_DATE,
                           repo=repo, repo_fetch=repo_fetch,
                           update_info=update_info)


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
        return json.dumps({"error": "Geen SD kaart geselecteerd"}), 400, {"Content-Type": "application/json"}
    try:
        pw_hash = hash_password(password)
        inject_to_partition(boot_path, hostname, wifi_country, "companion",
                            pw_hash, ap_ssid, ap_password, install_cups)
        return json.dumps({"ok": True, "hostname": hostname}), 200, {"Content-Type": "application/json"}
    except Exception as e:
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}


@app.route("/api/ci/status")
def api_ci_status():
    try:
        req = urllib.request.Request(
            f"{GITHUB_ACTIONS}?per_page=1&branch=main",
            headers={"User-Agent": f"companionpi-app/{APP_VERSION}",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        runs = data.get("workflow_runs", [])
        if not runs:
            return json.dumps({"status": "unknown"}), 200, {"Content-Type": "application/json"}
        run = runs[0]
        return json.dumps({
            "status":     run.get("status"),      # queued | in_progress | completed
            "conclusion": run.get("conclusion"),  # success | failure | cancelled | …
            "title":      run.get("display_title", ""),
            "url":        run.get("html_url", ""),
        }), 200, {"Content-Type": "application/json"}
    except Exception:
        return json.dumps({"status": "unknown"}), 200, {"Content-Type": "application/json"}


@app.route("/api/version")
def api_version():
    return json.dumps({"version": APP_VERSION}), 200, {"Content-Type": "application/json"}


@app.route("/api/quit", methods=["POST"])
def api_quit():
    def _do_quit():
        time.sleep(0.3)
        os._exit(0)
    threading.Thread(target=_do_quit, daemon=True).start()
    return json.dumps({"ok": True}), 200, {"Content-Type": "application/json"}


@app.route("/api/update/check")
def api_update_check():
    with _update_lock:
        return json.dumps(dict(_update)), 200, {"Content-Type": "application/json"}


@app.route("/api/update/install", methods=["POST"])
def api_update_install():
    with _update_lock:
        if _update["status"] not in ("available", "error"):
            return json.dumps({"error": "Geen update beschikbaar"}), 409, \
                   {"Content-Type": "application/json"}
        _update["status"] = "starting"
    threading.Thread(target=_do_install_update, daemon=True).start()
    return json.dumps({"status": "started"}), 200, {"Content-Type": "application/json"}


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
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}


# ── Main ──────────────────────────────────────────────────────────────────────

def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _get_running_version(port: int) -> str:
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/api/version",
            headers={"User-Agent": f"companionpi-app/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode()).get("version", "")
    except Exception:
        return ""


def _kill_port(port: int) -> None:
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(["netstat", "-ano"], text=True,
                                          stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    pid = line.split()[-1]
                    subprocess.call(["taskkill", "/F", "/PID", pid],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        else:
            subprocess.call(
                f"lsof -ti tcp:{port} | xargs kill -9 2>/dev/null",
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


if __name__ == "__main__":
    url = f"http://localhost:{PORT}"

    if _port_in_use(PORT):
        running_version = _get_running_version(PORT)
        if running_version == APP_VERSION:
            # Zelfde versie al actief — open gewoon de browser
            webbrowser.open(url)
            sys.exit(0)
        # Andere (oudere) versie actief — vervang die
        print(f"  Oude versie '{running_version or '?'}' op port {PORT} gevonden — vervangen door v{APP_VERSION}...")
        _kill_port(PORT)
        time.sleep(1.5)
        if _port_in_use(PORT):
            # Nog steeds bezet — open toch de browser
            webbrowser.open(url)
            sys.exit(0)

    threading.Thread(
        target=lambda: (time.sleep(1.2), webbrowser.open(url)),
        daemon=True
    ).start()
    threading.Thread(
        target=lambda: (time.sleep(4), _check_update_async()),
        daemon=True
    ).start()

    print(f"\n  CompanionPi Injector v{APP_VERSION}  →  {url}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
