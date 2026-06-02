#!/bin/bash
# CompanionPi firstrun.sh — runs on first RPi boot, injected by companion-imager

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

# Write status web server to a temp file and run it
log "Starting install status page on port 80..."
cat > /tmp/cpw_status.py << 'PYEOF'
import http.server, html, os

LOG_FILE = "/boot/firmware/firstrun.log"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        try:
            with open(LOG_FILE) as f:
                content = html.escape(f.read())
        except Exception:
            content = "Waiting for log..."
        body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="3">
  <title>CompanionPi Installing...</title>
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='%230d1117'/><rect width='64' height='64' rx='14' fill='%232563eb' fill-opacity='.18'/><path d='M9 28a32 32 0 0146 0M17 36a21 21 0 0130 0M25 44a12 12 0 0114 0' stroke='%233b82f6' stroke-width='4.5' stroke-linecap='round' fill='none'/><circle cx='28.5' cy='51.5' r='4' fill='%23dc2626'/><circle cx='35.5' cy='51.5' r='4' fill='%23dc2626'/><circle cx='32' cy='49.5' r='4' fill='%23dc2626'/><ellipse cx='32' cy='54' rx='5.5' ry='4' fill='%23dc2626'/></svg>">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0d1117; color: #e2e8f0; font-family: system-ui, sans-serif; }}
    .topbar {{ background: #0f1923; border-bottom: 1px solid #1e293b; padding: 14px 24px; display: flex; align-items: center; gap: 14px; }}
    .logo {{ width: 40px; height: 40px; }}
    .title {{ font-size: 15px; font-weight: 600; color: #f1f5f9; }}
    .sub {{ font-size: 11px; color: #64748b; margin-top: 2px; }}
    .badge {{ margin-left: auto; background: #f59e0b1a; color: #fbbf24; border: 1px solid #f59e0b33; border-radius: 99px; padding: 3px 12px; font-size: 11px; font-weight: 600; display: flex; align-items: center; gap: 6px; }}
    .dot {{ width: 7px; height: 7px; border-radius: 50%; background: #fbbf24; animation: pulse 1.5s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}
    .logbox {{ margin: 24px; background: #020617; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; }}
    pre {{ font-size: 12px; line-height: 1.75; color: #94a3b8; white-space: pre-wrap; word-break: break-all; }}
    .done {{ color: #34d399 !important; }}
  </style>
  <script>window.onload = () => window.scrollTo(0, document.body.scrollHeight);</script>
</head>
<body>
  <div class="topbar">
    <svg class="logo" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
      <rect width="64" height="64" rx="14" fill="#0d1117"/>
      <rect width="64" height="64" rx="14" fill="#2563eb" fill-opacity=".18"/>
      <path d="M9 28a32 32 0 0146 0M17 36a21 21 0 0130 0M25 44a12 12 0 0114 0" stroke="#3b82f6" stroke-width="4.5" stroke-linecap="round" fill="none"/>
      <circle cx="28.5" cy="51.5" r="4" fill="#dc2626"/>
      <circle cx="35.5" cy="51.5" r="4" fill="#dc2626"/>
      <circle cx="32"   cy="49.5" r="4" fill="#dc2626"/>
      <ellipse cx="32" cy="54" rx="5.5" ry="4" fill="#dc2626"/>
      <line x1="29.5" y1="48" x2="28" y2="45.5" stroke="#16a34a" stroke-width="2" stroke-linecap="round"/>
      <line x1="32" y1="47" x2="32" y2="44.5" stroke="#16a34a" stroke-width="2" stroke-linecap="round"/>
      <line x1="34.5" y1="48" x2="36" y2="45.5" stroke="#16a34a" stroke-width="2" stroke-linecap="round"/>
    </svg>
    <div>
      <div class="title">CompanionPi — Installing</div>
      <div class="sub">First boot setup in progress &nbsp;·&nbsp; refreshes every 3s</div>
    </div>
    <div class="badge"><span class="dot"></span>Running</div>
  </div>
  <div class="logbox">
    <pre class="{'done' if 'First boot complete' in content else ''}">{content}</pre>
  </div>
</body>
</html>"""
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

with http.server.HTTPServer(("", 80), Handler) as srv:
    srv.serve_forever()
PYEOF

python3 /tmp/cpw_status.py &
STATUS_PID=$!
log "Status page PID $STATUS_PID — open http://{{HOSTNAME}}.local in your browser"

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
cat > /etc/NetworkManager/conf.d/companionpi.conf << 'EOF'
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

# Done
log "=== First boot complete — rebooting in 5s ==="
sleep 5
kill $STATUS_PID 2>/dev/null || true
rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py

reboot
