#!/bin/bash
# CompanionPi firstrun.sh — injected by companionpi-wifi-injector, runs on first RPi boot

# Remove systemd.run= entries from cmdline.txt FIRST — before anything else can fail.
# If this doesn't run, systemd.run_success_action=reboot causes an infinite reboot loop.
sed -i 's| systemd\.run=[^ ]*||g'                /boot/firmware/cmdline.txt 2>/dev/null || true
sed -i 's| systemd\.run_success_action=[^ ]*||g' /boot/firmware/cmdline.txt 2>/dev/null || true
sed -i 's| systemd\.unit=[^ ]*||g'               /boot/firmware/cmdline.txt 2>/dev/null || true
sync

LOG=/boot/firmware/firstrun.log
exec 1>"$LOG" 2>&1

HOSTNAME='{{HOSTNAME}}'
WIFI_COUNTRY='{{WIFI_COUNTRY}}'
USERNAME='{{USERNAME}}'
PASSWORD='{{PASSWORD}}'
AP_SSID='{{AP_SSID}}'
AP_PASSWORD='{{AP_PASSWORD}}'
INSTALL_CUPS='{{INSTALL_CUPS}}'
IMAGE_TYPE='{{IMAGE_TYPE}}'

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

# Set password for companion user (PASSWORD is a sha512_crypt hash)
if [ -n "$PASSWORD" ]; then
    log "Setting password for user: $USERNAME"
    echo "$USERNAME:$PASSWORD" | chpasswd -e 2>/dev/null || true
fi

# Start install status web server on port 80
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
            status_html = f'''<div style="margin:24px;background:#052e16;border:1px solid #166534;border-radius:12px;padding:16px 20px">
              <div style="color:#4ade80;font-weight:600;margin-bottom:10px">&#10003; Install complete! Rebooting in 60 seconds...</div>
              <div style="display:flex;gap:10px;flex-wrap:wrap">
                <a href="http://{HOSTNAME}.local" target="_blank"
                   style="background:#1d4ed8;color:white;padding:8px 18px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">
                  &#9881; WiFi settings &#8594;
                </a>
                <a href="http://{HOSTNAME}.local:8000" target="_blank"
                   style="background:#166534;color:white;padding:8px 18px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">
                  Open Companion &#8594;
                </a>
              </div>
              <div style="color:#6b7280;font-size:11px;margin-top:8px">After reboot: connect to WiFi &ldquo;{HOSTNAME}&rdquo; or check your network for the RPi IP.</div>
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

log "cmdline.txt already cleaned at script start."

# Copy companionpi-wifi from SD card — bundled by imager, no internet needed
WIFI_SRC="/boot/firmware/companionpi-wifi"
if [ -d "$WIFI_SRC" ]; then
    log "Copying companionpi-wifi from SD card..."
    rm -rf /opt/companionpi-wifi
    cp -r "$WIFI_SRC" /opt/companionpi-wifi
    rm -rf "$WIFI_SRC"
else
    log "ERROR: companionpi-wifi not on SD card — re-inject with companionpi-wifi-injector."
    touch /tmp/cpw_install_failed
    sleep 300
    kill $STATUS_PID 2>/dev/null || true
    rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py /tmp/cpw_install_failed
    exit 0
fi

# Install packages best-effort (most already present in CompanionPi image)
log "Installing packages..."
apt-get install -y -qq --fix-missing \
    network-manager dnsmasq rfkill wireless-tools curl \
    python3 python3-pip python3-flask 2>&1 || \
    log "WARNING: apt-get failed — continuing with pre-installed packages"

# rpi-clone (best-effort — needs internet)
log "Installing rpi-clone (best-effort)..."
curl -sL --max-time 20 https://raw.githubusercontent.com/billw2/rpi-clone/master/rpi-clone \
    -o /usr/local/bin/rpi-clone 2>/dev/null \
    && chmod +x /usr/local/bin/rpi-clone \
    || log "WARNING: rpi-clone not installed (no internet)"

# NetworkManager — disable built-in DNS stub
cat > /etc/NetworkManager/conf.d/companionpi.conf << 'EOF'
[main]
dns=none
EOF
systemctl reload NetworkManager 2>/dev/null || true

# Run install.sh from the bundled repo
log "Running install.sh..."
cd /opt/companionpi-wifi
bash install.sh --force

# Companion already installed on CompanionPi image — ensure it's enabled
if [ "$IMAGE_TYPE" = "companionpi" ]; then
    log "CompanionPi image — ensuring Companion service is enabled..."
    systemctl enable --now companion 2>/dev/null || true
fi

# CUPS print server (optional)
if [ "$INSTALL_CUPS" = "true" ]; then
    log "Installing CUPS print server..."
    apt-get install -y -qq cups cups-bsd printer-driver-gutenprint 2>&1 | tail -3
    systemctl enable cups 2>/dev/null || true
    cupsctl --remote-admin --remote-any --share-printers 2>/dev/null || true
    log "CUPS installed."
fi

# Apply WiFi settings
log "Applying Wi-Fi settings (country=$WIFI_COUNTRY AP=$AP_SSID)"
sed -i "s/^WIFI_COUNTRY=.*/WIFI_COUNTRY=$WIFI_COUNTRY/" \
    /etc/companionpi-wifi/settings.env
sed -i "s/^WLAN0_AP_SSID=.*/WLAN0_AP_SSID=$AP_SSID/" \
    /etc/companionpi-wifi/settings.env
sed -i "s/^WLAN0_AP_PASSWORD=.*/WLAN0_AP_PASSWORD=$AP_PASSWORD/" \
    /etc/companionpi-wifi/settings.env
# Clear placeholder client profiles so the RPi goes straight to AP mode on first boot
sed -i "s/^WLAN0_CLIENT_PROFILES=.*/WLAN0_CLIENT_PROFILES=/" \
    /etc/companionpi-wifi/settings.env
raspi-config nonint do_wifi_country "$WIFI_COUNTRY" 2>/dev/null || \
    iw reg set "$WIFI_COUNTRY" 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true

# Done
log "=== First boot complete ==="
touch /tmp/cpw_install_done
log "Companion:     http://{{HOSTNAME}}.local:8000"
log "Network config: http://{{HOSTNAME}}.local"
log "Rebooting in 60 seconds..."
sleep 60

kill $STATUS_PID 2>/dev/null || true
rm -f /boot/firmware/firstrun.sh /tmp/cpw_status.py /tmp/cpw_install_done
sync
# systemd triggers reboot via systemd.run_success_action=reboot in cmdline.txt
exit 0
