#!/bin/bash
# CI-only credential preparation. No app, model, account or publication work.
set -euo pipefail
umask 077
temp_root="$(cd "$RUNNER_TEMP" && pwd -P)"
signing_dir="$(mktemp -d "$temp_root/vision-signing.XXXXXXXX")"
touch "$signing_dir/VISION-SIGNING-TEMP"
keychain="$signing_dir/signing.keychain-db"
export VISION_SIGNING_KEYCHAIN="$keychain"
printf 'VISION_SIGNING_KEYCHAIN=%s\n' "$keychain" >> "$GITHUB_ENV"
helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
finish() {
  preparation_status=$?
  if [ "$preparation_status" -ne 0 ]; then
    /bin/bash "$helper_dir/Clean-Signing.sh" || true
  fi
  exit "$preparation_status"
}
trap finish EXIT
password="$(uuidgen)"
security create-keychain -p "$password" "$keychain"
security set-keychain-settings -lut 3600 "$keychain"
security unlock-keychain -p "$password" "$keychain"
printf '%s' "$MAC_DEVELOPER_ID_P12_BASE64" | base64 --decode > "$signing_dir/identity.p12"
security import "$signing_dir/identity.p12" -k "$keychain" -P "$MAC_DEVELOPER_ID_P12_PASSWORD" -T /usr/bin/codesign
rm -f "$signing_dir/identity.p12"
security set-key-partition-list -S apple-tool:,apple: -s -k "$password" "$keychain" > /dev/null
printf '%s' "$APPLE_NOTARY_KEY_P8" > "$signing_dir/notary.p8"
xcrun notarytool store-credentials VISION-notary --key "$signing_dir/notary.p8" \
  --key-id "$APPLE_NOTARY_KEY_ID" --issuer "$APPLE_NOTARY_ISSUER" --keychain "$keychain"
rm -f "$signing_dir/notary.p8"
