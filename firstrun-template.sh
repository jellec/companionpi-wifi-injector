#!/bin/bash
# CompanionPi firstrun.sh — runs on first RPi boot, injected by companion-imager
# Triggered via cmdline.txt: systemd.run=/boot/firmware/firstrun.sh

LOG=/boot/firmware/firstrun.log
exec 1>"$LOG" 2>&1

HOSTNAME="{{HOSTNAME}}"
WIFI_COUNTRY="{{WIFI_COUNTRY}}"
REPO_URL="{{REPO_URL}}"
USERNAME="{{USERNAME}}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

log "=== CompanionPi first boot ==="

# Hostname
log "Setting hostname: $HOSTNAME"
hostnamectl set-hostname "$HOSTNAME"
grep -qF "127.0.1.1" /etc/hosts \
    && sed -i "s/^127.0.1.1.*/127.0.1.1\t$HOSTNAME/" /etc/hosts \
    || echo "127.0.1.1	$HOSTNAME" >> /etc/hosts

# Enable SSH
log "Enabling SSH..."
systemctl enable ssh
systemctl start ssh

# Start status web server on port 80
# Serves firstrun.log with auto-refresh so you can watch progress from a browser
log "Starting install status page on port 80..."
python3 - <<'PYEOF' &
STATUS_PID=$!
import http.server, os, time, html

LOG_FILE = "/boot/firmware/firstrun.log"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        try:
            with open(LOG_FILE) as f:
                content = html.escape(f.read())
        except Exception:
            content = "Log not available yet..."
        body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="3">
  <title>CompanionPi Install</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%232563eb'/><path d='M8 17.5a11.4 11.4 0 0116 0M11.5 21a6.4 6.4 0 019 0M16 24.5h.1' stroke='white' stroke-width='2.2' stroke-linecap='round' fill='none'/></svg>">
  <style>
    body {{ background:#0f172a; color:#e2e8f0; font-family:system-ui,sans-serif; margin:0; padding:0; }}
    .header {{ background:#1e293b; border-bottom:1px solid #334155; padding:16px 24px; display:flex; align-items:center; gap:12px; }}
    .logo {{ width:36px; height:36px; background:#2563eb; border-radius:8px; display:flex; align-items:center; justify-content:center; }}
    h1 {{ margin:0; font-size:16px; font-weight:600; }}
    .sub {{ font-size:12px; color:#64748b; margin:0; }}
    .badge {{ margin-left:auto; background:#f59e0b22; color:#fbbf24; border:1px solid #f59e0b44; border-radius:99px; padding:3px 10px; font-size:11px; font-weight:600; }}
    .log {{ margin:24px; background:#020617; border:1px solid #1e293b; border-radius:12px; padding:20px; }}
    pre {{ margin:0; font-size:12px; line-height:1.7; color:#94a3b8; white-space:pre-wrap; word-break:break-all; }}
    .done {{ color:#34d399; }}
  </style>
  <script>window.onload=()=>window.scrollTo(0,document.body.scrollHeight);</script>
</head>
<body>
  <div class="header">
    <div class="logo">
      <svg width="20" height="20" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" viewBox="0 0 24 24">
        <path d="M8 17.5a5.5 5.5 0 018 0M11.5 21a2.5 2.5 0 013 0M12 24h.01M4.9 12.9a10 10 0 0114.2 0M1.4 9.4a15 15 0 0121.2 0"/>
      </svg>
    </div>
    <div><h1>CompanionPi — Installing</h1><p class="sub">First boot setup in progress</p></div>
    <div class="badge">Auto-refresh 3s</div>
  </div>
  <div class="log"><pre>{content}</pre></div>
</body>
</html>"""
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

with http.server.HTTPServer(("", 80), Handler) as srv:
    srv.serve_forever()
PYEOF
STATUS_PID=$!
log "Status page running (PID $STATUS_PID) — open http://$HOSTNAME.local in your browser"

# Clean firstrun trigger from cmdline.txt
log "Cleaning cmdline.txt..."
sed -i 's| systemd\.run=[^ ]*||g' /boot/firmware/cmdline.txt
sed -i 's| systemd\.run_success_action=[^ ]*||g' /boot/firmware/cmdline.txt
sed -i 's| systemd\.unit=[^ ]*||g' /boot/firmware/cmdline.txt

# Update apt
log "Updating package lists..."
apt-get update -qq

# Install dependencies
log "Installing packages (this may take a few minutes)..."
apt-get install -y -qq \
    git \
    python3 \
    python3-pip \
    python3-flask \
    network-manager \
    dnsmasq \
    curl

# rpi-clone
log "Installing rpi-clone..."
curl -sL https://raw.githubusercontent.com/billw2/rpi-clone/master/rpi-clone \
    -o /usr/local/bin/rpi-clone
chmod +x /usr/local/bin/rpi-clone

# NetworkManager — disable built-in DNS stub
NM_CONF="/etc/NetworkManager/conf.d/companionpi.conf"
cat > "$NM_CONF" << 'EOF'
[main]
dns=none
EOF
systemctl reload NetworkManager 2>/dev/null || true

# Clone companionpi-wifi
log "Cloning companionpi-wifi from $REPO_URL ..."
rm -rf /opt/companionpi-wifi
git clone --depth 1 "$REPO_URL" /opt/companionpi-wifi

# Install
log "Running install.sh..."
bash /opt/companionpi-wifi/install.sh

# Set wifi country
log "Setting Wi-Fi country: $WIFI_COUNTRY"
sed -i "s/^WIFI_COUNTRY=.*/WIFI_COUNTRY=$WIFI_COUNTRY/" \
    /etc/companionpi-wifi/settings.env

# Stop status server
kill $STATUS_PID 2>/dev/null || true

log "=== First boot complete — rebooting ==="
rm -f /boot/firmware/firstrun.sh

reboot
