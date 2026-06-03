#!/bin/bash
# CompanionPi firstrun.sh — runs on first RPi boot, injected by companion-imager

LOG=/boot/firmware/firstrun.log
exec 1>"$LOG" 2>&1

HOSTNAME="{{HOSTNAME}}"
WIFI_COUNTRY="{{WIFI_COUNTRY}}"
REPO_URL="{{REPO_URL}}"
USERNAME="{{USERNAME}}"
AP_SSID="{{AP_SSID}}"
AP_PASSWORD="{{AP_PASSWORD}}"
INSTALL_CUPS="{{INSTALL_CUPS}}"
IMAGE_TYPE="{{IMAGE_TYPE}}"    # companionpi | rpios
PACKAGES_DIR="/boot/firmware/packages"

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

LOG_FILE  = "/boot/firmware/firstrun.log"
HOSTNAME  = open("/etc/hostname").read().strip()
DONE_FLAG = "/tmp/cpw_install_done"
FAIL_FLAG = "/tmp/cpw_install_failed"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        try:
            with open(LOG_FILE) as f:
                content = html.escape(f.read())
        except Exception:
            content = "Waiting for log..."
        done   = os.path.exists(DONE_FLAG)
        failed = os.path.exists(FAIL_FLAG)
        refresh = "" if (done or failed) else '<meta http-equiv="refresh" content="3">'
        if done:
            status_html = f'''<div style="margin:24px;background:#052e16;border:1px solid #166534;border-radius:12px;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px">
              <div style="color:#4ade80;font-weight:600">&#10003; Install complete!</div>
              <a href="http://{HOSTNAME}.local:8001" target="_blank"
                 style="background:#2563eb;color:white;padding:8px 18px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">
                Open Companion &#8594;
              </a>
            </div>'''
            badge = '<div class="badge" style="background:#4ade801a;color:#4ade80;border:1px solid #4ade8033"><span class="dot" style="background:#4ade80"></span>Done</div>'
        elif failed:
            status_html = '<div style="margin:24px;background:#450a0a;border:1px solid #7f1d1d;border-radius:12px;padding:16px 20px;color:#fca5a5;font-weight:600">&#10007; Install failed — check log above</div>'
            badge = '<div class="badge" style="background:#dc26261a;color:#fca5a5;border:1px solid #dc262633"><span class="dot" style="background:#fca5a5"></span>Failed</div>'
        else:
            status_html = ""
            badge = '<div class="badge"><span class="dot"></span>Running</div>'

        body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  {refresh}
  <title>CompanionPi Installing...</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:#0d1117;color:#e2e8f0;font-family:system-ui,sans-serif}}
    .topbar{{background:#0f1923;border-bottom:1px solid #1e293b;padding:14px 24px;display:flex;align-items:center;gap:14px}}
    .logo{{width:40px;height:40px}}
    .title{{font-size:15px;font-weight:600;color:#f1f5f9}}
    .sub{{font-size:11px;color:#64748b;margin-top:2px}}
    .badge{{margin-left:auto;background:#f59e0b1a;color:#fbbf24;border:1px solid #f59e0b33;border-radius:99px;padding:3px 12px;font-size:11px;font-weight:600;display:flex;align-items:center;gap:6px}}
    .dot{{width:7px;height:7px;border-radius:50%;background:#fbbf24;animation:pulse 1.5s infinite}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
    .logbox{{margin:24px;background:#020617;border:1px solid #1e293b;border-radius:12px;padding:20px}}
    pre{{font-size:12px;line-height:1.75;color:#94a3b8;white-space:pre-wrap;word-break:break-all}}
  </style>
  <script>window.onload=()=>window.scrollTo(0,document.body.scrollHeight)</script>
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
      <div class="sub">First boot setup &nbsp;·&nbsp; {HOSTNAME}.local</div>
    </div>
    {badge}
  </div>
  {status_html}
  <div class="logbox">
    <pre>{content}</pre>
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

# Ensure DNS works during early boot (resolv.conf may be empty before systemd-resolved starts)
if ! grep -q "^nameserver" /etc/resolv.conf 2>/dev/null; then
    log "No nameserver in resolv.conf — adding 8.8.8.8"
    echo "nameserver 8.8.8.8" >> /etc/resolv.conf
fi

# Wait for network / IP connectivity before proceeding
log "Waiting for network..."
NETWORK_OK=0
for i in $(seq 1 60); do
    if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then
        log "Network ready (try $i)"
        NETWORK_OK=1
        break
    fi
    log "  No network yet, waiting... ($i/60)"
    sleep 2
done

if [ $NETWORK_OK -eq 0 ]; then
    log "ERROR: Network/DNS not available after 120s — cannot install packages."
    touch /tmp/cpw_install_failed
    sleep 300
    kill $STATUS_PID 2>/dev/null || true
    rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py /tmp/cpw_install_failed
    reboot
fi

# Update apt (retry up to 3 times)
for attempt in 1 2 3; do
    log "Updating package lists (attempt $attempt/3)..."
    apt-get update -qq && break
    [ $attempt -lt 3 ] && { log "  Retrying in 15s..."; sleep 15; }
done

# Install dependencies — CompanionPi image already has most packages
if [ "$IMAGE_TYPE" = "companionpi" ]; then
    log "CompanionPi image — installing only network management packages..."
    PKGS="network-manager dnsmasq rfkill wireless-tools git curl"
else
    PKGS="git python3 python3-pip python3-flask network-manager dnsmasq curl rfkill wireless-tools"
fi

for attempt in 1 2 3; do
    log "Installing packages — attempt $attempt/3..."
    apt-get install -y -qq --fix-missing $PKGS && break
    [ $attempt -lt 3 ] && { log "  apt failed, retrying in 30s..."; sleep 30; }
done

# Verify git is available
if ! command -v git >/dev/null 2>&1; then
    log "ERROR: git not installed after apt — aborting."
    touch /tmp/cpw_install_failed
    sleep 300
    kill $STATUS_PID 2>/dev/null || true
    rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py /tmp/cpw_install_failed
    reboot
fi

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

if [ ! -f /opt/companionpi-wifi/install.sh ]; then
    log "ERROR: git clone failed — /opt/companionpi-wifi/install.sh not found."
    touch /tmp/cpw_install_failed
    sleep 300
    kill $STATUS_PID 2>/dev/null || true
    rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py /tmp/cpw_install_failed
    reboot
fi

# Install
log "Running install.sh..."
bash /opt/companionpi-wifi/install.sh

# Install Bitfocus Companion — skip if already present (CompanionPi image)
if [ "$IMAGE_TYPE" = "companionpi" ]; then
    log "CompanionPi image — Companion already installed, skipping."
    systemctl enable --now companion 2>/dev/null || true
else
    COMPANION_DEB=$(ls "$PACKAGES_DIR"/companion*.deb 2>/dev/null | head -1)
    if [ -n "$COMPANION_DEB" ]; then
        log "Installing Companion from SD card: $(basename $COMPANION_DEB)"
        apt-get install -y -qq "$COMPANION_DEB" 2>&1 || log "WARNING: Companion install failed"
        systemctl enable --now companion 2>/dev/null || true
        log "Companion installed (offline)."
    else
        log "WARNING: No Companion package found. Install via web UI after boot."
        log "  Download from: https://user.bitfocus.io/download (Linux ARM64 .deb)"
    fi
fi

# Install print server (CUPS) if requested
if [ "$INSTALL_CUPS" = "true" ]; then
    log "Installing CUPS print server..."
    apt-get install -y -qq cups cups-bsd printer-driver-gutenprint 2>&1 | tail -3
    systemctl enable cups 2>/dev/null || true
    cupsctl --remote-admin --remote-any --share-printers 2>/dev/null || true
    log "CUPS installed."
fi

# Write WiFi and AP settings to settings.env
log "Applying Wi-Fi settings (country=$WIFI_COUNTRY AP=$AP_SSID)"
sed -i "s/^WIFI_COUNTRY=.*/WIFI_COUNTRY=$WIFI_COUNTRY/" \
    /etc/companionpi-wifi/settings.env
sed -i "s/^WLAN0_AP_SSID=.*/WLAN0_AP_SSID=$AP_SSID/" \
    /etc/companionpi-wifi/settings.env
sed -i "s/^WLAN0_AP_PASSWORD=.*/WLAN0_AP_PASSWORD=$AP_PASSWORD/" \
    /etc/companionpi-wifi/settings.env
# Apply country code and unblock WiFi at OS level
raspi-config nonint do_wifi_country "$WIFI_COUNTRY" 2>/dev/null || \
    iw reg set "$WIFI_COUNTRY" 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true

# Done
log "=== First boot complete ==="
touch /tmp/cpw_install_done
log "Open http://{{HOSTNAME}}.local:8001 in your browser"
log "Status page stays up for 5 minutes, then rebooting..."
sleep 300

kill $STATUS_PID 2>/dev/null || true
rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py /tmp/cpw_install_done

reboot
