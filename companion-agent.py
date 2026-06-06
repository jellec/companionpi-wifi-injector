#!/usr/bin/env python3
"""
CompanionPi Local Agent — draait op je Mac of Windows.
Start eenmalig, laat draaien op de achtergrond.
De NAS-webapp praat ermee via http://localhost:7072

Gebruik:
  python companion-agent.py
  (of: dubbelklik companion-agent.app / companion-agent.exe)
"""

import base64
import io
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, request

AGENT_VERSION = "1.0.0"
PORT = 7072

app = Flask(__name__)


# ── CORS (nodig zodat de NAS-webapp op poort 7070 mag praten met localhost) ──

@app.after_request
def add_cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

@app.route("/api/ping")
def ping():
    return jsonify({"agent": "companion-agent", "version": AGENT_VERSION})

@app.route("/api/ping", methods=["OPTIONS"])
def ping_options():
    return Response(status=200)


# ── SD-kaart detectie ─────────────────────────────────────────────────────────

def find_boot_partitions() -> list:
    candidates = []

    if sys.platform == "win32":
        import string
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


@app.route("/api/partitions")
def partitions():
    return jsonify(find_boot_partitions())

@app.route("/api/partitions", methods=["OPTIONS"])
def partitions_options():
    return Response(status=200)


# ── Inject ────────────────────────────────────────────────────────────────────

@app.route("/api/inject", methods=["OPTIONS"])
def inject_options():
    return Response(status=200)

@app.route("/api/inject", methods=["POST"])
def inject():
    boot_path   = request.form.get("boot_path", "").strip()
    bundle_b64  = request.form.get("bundle_base64", "").strip()

    if not boot_path:
        return jsonify({"error": "Geen SD kaart geselecteerd"}), 400
    if not bundle_b64:
        return jsonify({"error": "Geen bundle ontvangen van de NAS"}), 400

    boot = Path(boot_path)
    if not (boot / "cmdline.txt").exists():
        return jsonify({"error": f"Geen geldige RPi boot-partitie: {boot_path}"}), 400

    try:
        bundle_bytes = base64.b64decode(bundle_b64)
    except Exception:
        return jsonify({"error": "Bundle kon niet worden gedecodeerd"}), 400

    try:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as zf:
                zf.extractall(tmp)

            for name in ["firstrun.sh", "userconf.txt", "ssh", "companionpi-info.txt"]:
                src = tmp / name
                if src.exists():
                    shutil.copy2(str(src), str(boot / name))

            wifi_src = tmp / "companionpi-wifi"
            if wifi_src.exists():
                wifi_dst = boot / "companionpi-wifi"
                if wifi_dst.exists():
                    shutil.rmtree(str(wifi_dst))
                shutil.copytree(str(wifi_src), str(wifi_dst))

            meta = json.loads((tmp / "meta.json").read_text())
            cmdline = (boot / "cmdline.txt").read_text().strip()
            for pat in meta.get("cmdline_strip", []):
                cmdline = re.sub(pat, "", cmdline)
            (boot / "cmdline.txt").write_text(cmdline.strip() + " " + meta["cmdline_add"] + "\n")

        return jsonify({"ok": True, "hostname": meta.get("hostname", "companion")})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n  CompanionPi Agent v{AGENT_VERSION}")
    print(f"  Luistert op http://localhost:{PORT}")
    print(f"  Open de injector-webapp op je NAS in je browser.")
    print(f"  Laat dit venster open — sluit het als je klaar bent.\n")
    app.run(host="127.0.0.1", port=PORT, debug=False)
