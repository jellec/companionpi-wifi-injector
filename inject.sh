#!/bin/bash
# inject.sh — apply a companionpi-wifi-injector bundle to a mounted SD card
# Usage: bash inject.sh <bundle.zip> [boot-partition-path]
#        bash inject.sh ~/Downloads/bundle.zip
#        bash inject.sh ~/Downloads/bundle.zip /Volumes/bootfs

set -e

# ── argument parsing ──────────────────────────────────────────────────────────
BUNDLE=""
BOOT=""
for arg in "$@"; do
    if [[ "$arg" == *.zip ]]; then
        BUNDLE="$arg"
    elif [[ -d "$arg" ]]; then
        BOOT="$arg"
    fi
done

[ -f "$BUNDLE" ] || { echo "Usage: bash inject.sh <bundle.zip> [boot-partition-path]"; exit 1; }

# ── SD card auto-detection (macOS) ────────────────────────────────────────────
if [ -z "$BOOT" ]; then
    CANDIDATES=()
    for vol in /Volumes/*/; do
        [ -f "${vol}cmdline.txt" ] && CANDIDATES+=("${vol%/}")
    done

    if [ ${#CANDIDATES[@]} -eq 0 ]; then
        echo "ERROR: No mounted RPi boot partition found."
        echo "       Mount the SD card and try again, or pass the path explicitly:"
        echo "       bash inject.sh bundle.zip /Volumes/bootfs"
        exit 1
    elif [ ${#CANDIDATES[@]} -eq 1 ]; then
        BOOT="${CANDIDATES[0]}"
        echo "Found boot partition: $BOOT"
    else
        echo "Multiple boot partitions found:"
        for i in "${!CANDIDATES[@]}"; do
            echo "  $((i+1))) ${CANDIDATES[$i]}"
        done
        printf "Select [1-%d]: " "${#CANDIDATES[@]}"
        read -r choice
        idx=$((choice - 1))
        [ "$idx" -ge 0 ] && [ "$idx" -lt "${#CANDIDATES[@]}" ] || { echo "Invalid choice"; exit 1; }
        BOOT="${CANDIDATES[$idx]}"
    fi
fi

[ -f "$BOOT/cmdline.txt" ] || { echo "ERROR: $BOOT is not an RPi boot partition (no cmdline.txt)"; exit 1; }

# ── inject ────────────────────────────────────────────────────────────────────
echo "Injecting into: $BOOT"
echo "Bundle:         $BUNDLE"
echo ""

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

unzip -q "$BUNDLE" -d "$TMP"

for f in firstrun.sh userconf.txt ssh companionpi-info.txt; do
    [ -f "$TMP/$f" ] && cp "$TMP/$f" "$BOOT/$f" && echo "  + $f"
done

if [ -d "$TMP/companionpi-wifi" ]; then
    rm -rf "$BOOT/companionpi-wifi"
    cp -r "$TMP/companionpi-wifi" "$BOOT/companionpi-wifi"
    echo "  + companionpi-wifi/"
fi

CMDLINE=$(tr -d '\n' < "$BOOT/cmdline.txt")
CMDLINE=$(echo "$CMDLINE" | sed \
    -e 's| systemd\.run=[^ ]*||g' \
    -e 's| systemd\.run_success_action=[^ ]*||g' \
    -e 's| systemd\.run_failure_action=[^ ]*||g' \
    -e 's| systemd\.unit=[^ ]*||g')
ADD=$(python3 -c "import json; print(json.load(open('$TMP/meta.json'))['cmdline_add'])")
printf '%s %s\n' "$CMDLINE" "$ADD" > "$BOOT/cmdline.txt"
echo "  + cmdline.txt (patched)"

HOSTNAME=$(python3 -c "import json; print(json.load(open('$TMP/meta.json'))['hostname'])")
echo ""
echo "Done! Eject $BOOT safely, insert into RPi and power on."
echo "First boot takes ~1 minute. Open http://${HOSTNAME}.local when ready."
