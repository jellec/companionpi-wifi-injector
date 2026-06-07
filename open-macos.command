#!/bin/bash
# Verwijder macOS-quarantaine en open CompanionPi Injector
cd "$(dirname "$0")"
xattr -cr companion-app.app
open companion-app.app
