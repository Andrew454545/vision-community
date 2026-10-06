#!/bin/bash
# Remove only the private temporary directory created by Prepare-Signing.sh.
set -euo pipefail
if [ -z "${VISION_SIGNING_KEYCHAIN:-}" ]; then exit 0; fi
signing_dir="$(dirname "$VISION_SIGNING_KEYCHAIN")"
if [ ! -e "$signing_dir" ] && [ ! -L "$signing_dir" ]; then exit 0; fi
temp_root="$(cd "$RUNNER_TEMP" && pwd -P)"
if [ "$(dirname "$signing_dir")" != "$temp_root" ] ||
   [[ ! "$(basename "$signing_dir")" =~ ^vision-signing\.[A-Za-z0-9]{8}$ ]] ||
   [ "$(basename "$VISION_SIGNING_KEYCHAIN")" != 'signing.keychain-db' ] ||
   [ -L "$signing_dir" ] || [ -L "$VISION_SIGNING_KEYCHAIN" ] ||
   [ ! -f "$signing_dir/VISION-SIGNING-TEMP" ] || [ -L "$signing_dir/VISION-SIGNING-TEMP" ]; then
  echo 'Refusing unfamiliar signing cleanup scope.' >&2
  exit 1
fi
cleanup_status=0
if [ -e "$VISION_SIGNING_KEYCHAIN" ]; then
  security delete-keychain "$VISION_SIGNING_KEYCHAIN" || cleanup_status=1
fi
# Raw credential files are removed even if the keychain deletion fails.
rm -f "$signing_dir/identity.p12" "$signing_dir/notary.p8"
if [ "$cleanup_status" -eq 0 ]; then
  rm -f "$signing_dir/VISION-SIGNING-TEMP"
  rmdir "$signing_dir" || cleanup_status=1
fi
exit "$cleanup_status"
