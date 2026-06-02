#!/bin/bash
# CompanionPi firstrun.sh — runs on first RPi boot, injected by companion-imager
# Triggered via cmdline.txt: systemd.run=/boot/firmware/firstrun.sh

exec 1>/boot/firmware/firstrun.log 2>&1

HOSTNAME="{{HOSTNAME}}"
WIFI_COUNTRY="{{WIFI_COUNTRY}}"
REPO_URL="{{REPO_URL}}"
USERNAME="{{USERNAME}}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [firstrun] $1"; }

log "CompanionPi first boot starting..."

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

# Remove the 'firstrun' trigger from cmdline.txt so we don't loop
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
log "Cloning CompanionPi WiFi3..."
rm -rf /opt/companionpi-wifi
git clone --depth 1 "$REPO_URL" /opt/companionpi-wifi

# Install
log "Running install.sh..."
bash /opt/companionpi-wifi/install.sh

# Set wifi country
log "Setting Wi-Fi country: $WIFI_COUNTRY"
sed -i "s/^WIFI_COUNTRY=.*/WIFI_COUNTRY=$WIFI_COUNTRY/" \
    /etc/companionpi-wifi/settings.env

# Clean up
rm -f /boot/firmware/firstrun.sh

log "First boot complete — rebooting."
reboot
