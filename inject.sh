#!/bin/bash
# inject.sh — apply a companionpi-wifi-injector bundle to a mounted SD card
# Usage: bash inject.sh /Volumes/bootfs ~/Downloads/companionpi-companion-20260606-1200.zip

set -e

BOOT="${1}"
BUNDLE="${2}"

usage() { echo "Usage: bash inject.sh <boot-partition-path> <bundle.zip>"; exit 1; }
[ -z "$BOOT" ] || [ -z "$BUNDLE" ] && usage
[ -f "$BOOT/cmdline.txt" ] || { echo "ERROR: $BOOT is not an RPi boot partition (no cmdline.txt)"; exit 1; }
[ -f "$BUNDLE" ] || { echo "ERROR: Bundle not found: $BUNDLE"; exit 1; }

echo "Injecting into: $BOOT"
echo "Bundle:         $BUNDLE"
echo ""

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

# Extract bundle
unzip -q "$BUNDLE" -d "$TMP"

# Copy flat files
for f in firstrun.sh userconf.txt ssh companionpi-info.txt; do
    [ -f "$TMP/$f" ] && cp "$TMP/$f" "$BOOT/$f" && echo "  + $f"
done

# Copy wifi repo
if [ -d "$TMP/companionpi-wifi" ]; then
    rm -rf "$BOOT/companionpi-wifi"
    cp -r "$TMP/companionpi-wifi" "$BOOT/companionpi-wifi"
    echo "  + companionpi-wifi/"
fi

# Patch cmdline.txt
CMDLINE=$(tr -d '\n' < "$BOOT/cmdline.txt")
CMDLINE=$(echo "$CMDLINE" | sed \
    -e 's| systemd\.run=[^ ]*||g' \
    -e 's| systemd\.run_success_action=[^ ]*||g' \
    -e 's| systemd\.run_failure_action=[^ ]*||g' \
    -e 's| systemd\.unit=[^ ]*||g')
ADD=$(python3 -c "import json; print(open('$TMP/meta.json').read())" | python3 -c "import json,sys; print(json.load(sys.stdin)['cmdline_add'])")
printf '%s %s\n' "$CMDLINE" "$ADD" > "$BOOT/cmdline.txt"
echo "  + cmdline.txt (patched)"

echo ""
echo "Done! Eject $BOOT safely, insert into RPi and power on."
echo "First boot takes ~1 minute. Open http://$(python3 -c "import json; print(json.load(open('$TMP/meta.json'))['hostname'])").local when ready."
