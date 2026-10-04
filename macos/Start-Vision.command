#!/bin/bash
# Maintainer Mac preview: no global install, sudo, pip or security changes.
set -euo pipefail
umask 077
unset BASH_ENV ENV PERL5OPT PERL5LIB PYTHONPATH PYTHONHOME DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export LC_ALL=C
source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
root="${HOME}/Library/Application Support/VISION Community"
mode=app
accepted=0
phase=platform
while [[ $# -gt 0 ]]; do
    case "$1" in
        --root) [[ $# -ge 2 ]] || exit 2; root="$2"; shift 2 ;;
        --accept-downloads) accepted=1; shift ;;
        --python-only) mode=python; shift ;;
        --snapshot-only) mode=snapshot; shift ;;
        --prepare-only) mode=prepare; shift ;;
        *) printf 'That startup option is not supported.\n'; exit 2 ;;
    esac
done
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    printf 'This Mac preview requires an Apple silicon Mac. Other builds are not ready yet.\n'
    exit 2
fi
if [[ "$root" != /* || "$root" == / || "$root" == *'/../'* || "$root" == */.. ]]; then
    printf 'Choose a regular private application folder.\n'; exit 2
fi
regular_path() {
    local path="$1"
    while [[ "$path" != / && -n "$path" ]]; do
        [[ ! -L "$path" ]] || return 1
        path="$(dirname -- "$path")"
    done
}
regular_path "$root" || { printf 'Choose a regular private application folder.\n'; exit 2; }
mkdir -p "$root"
root="$(cd -- "$root" && pwd -P)"
failure() {
    local result=$?
    trap - EXIT
    if [[ $result -ne 0 ]]; then
        if regular_path "$root/setup-failures"; then
            mkdir -p "$root/setup-failures"
            (set -C; printf '{"status":"INCOMPLETE","phase":"%s","code":"mac_setup_failed"}\n' "$phase" \
                > "$root/setup-failures/$(date -u +%Y%m%dT%H%M%SZ)-$$.json") || true
        fi
        printf 'VISION could not start. Your files and a private failure report were kept.\n'
    fi
    exit "$result"
}
trap failure EXIT
phase=consent
regular_path "$root/consent.json"
if [[ $accepted -eq 0 && -f "$root/consent.json" && ! -L "$root/consent.json" ]]; then
    if /usr/bin/env -i PATH="$PATH" /usr/bin/perl -MJSON::PP -e \
        'open my $f,"<",$ARGV[0] or exit 1; local $/; my $r=decode_json(<$f>); exit(($r->{version}==1 && $r->{accepted})?0:1)' "$root/consent.json" 2>/dev/null; then accepted=1; fi
fi
if [[ $accepted -eq 0 ]]; then
    printf 'VISION downloads private processing files. Imagery is retrieved only when you request a check or contribution.\n'
    printf 'Continue? Type Y and press Return: '
    read -r answer
    case "$answer" in y|Y|yes|YES) accepted=1 ;; *) printf 'Cancelled. Nothing was downloaded.\n'; exit 0 ;; esac
fi
printf '{"version":1,"accepted":true}\n' > "$root/consent.json"
phase=storage
[[ $(df -Pk "$root" | awk 'NR==2 {print $4}') -ge 3145728 ]] || { printf 'Free at least 3 GB, then try again.\n'; exit 1; }
phase=private_python
archive_sha=d15291f940cfecd2e54010d5e37d2e03aa192f076a65d26ab741372fff2dabfe
inventory_sha=878935ae4a1cb2a33cf7fee17e0ea020b754a4c9a25d8422961c2aeb44e4824b
downloads="$root/downloads"
private="$root/python-3.14.8-20261003-arm64"
regular_path "$downloads" && regular_path "$private"
mkdir -p "$downloads"
archive="$downloads/cpython-3.14.8-20261003-macos-arm64.tar.gz"
regular_path "$archive" && regular_path "$archive.partial"
if [[ ! -f "$archive" ]]; then
    printf 'Downloading the private setup files. Please wait.\n'
    curl --fail --location --proto '=https' --proto-redir '=https' --retry 2 --max-time 300 --max-filesize 30000000 \
        --output "$archive.partial" \
        'https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.14.8%2B20261003-aarch64-apple-darwin-install_only.tar.gz'
    [[ $(wc -c < "$archive.partial" | tr -d ' ') -eq 26798928 ]]
    [[ $(shasum -a 256 "$archive.partial" | awk '{print $1}') == "$archive_sha" ]]
    mv -- "$archive.partial" "$archive"
fi
[[ $(wc -c < "$archive" | tr -d ' ') -eq 26798928 ]]
[[ $(shasum -a 256 "$archive" | awk '{print $1}') == "$archive_sha" ]]
if [[ ! -d "$private" ]]; then
    mkdir "$private"
    # Only the independently pinned archive reaches extraction. Never overwrite
    # an existing or partial interpreter; preserve it if any check fails.
    tar -xzf "$archive" -C "$private" --no-same-owner
fi
/usr/bin/env -i PATH="$PATH" /usr/bin/perl "$source_root/macos/verify-python.pl" \
    "$source_root/macos/python-arm64-inventory.json" "$inventory_sha" "$private"
python="$private/python/bin/python3.14"
# HTTPS verification uses the CA bundle inside the fully verified distribution.
export SSL_CERT_FILE="$private/python/lib/python3.14/site-packages/pip/_vendor/certifi/cacert.pem"
phase=application
if [[ "$mode" == python ]]; then
    /usr/bin/env -i HOME="$HOME" PATH="$PATH" SSL_CERT_FILE="$SSL_CERT_FILE" "$python" -I -B -c \
        'import platform,ssl,sqlite3,urllib.request; assert platform.system()=="Darwin" and platform.machine()=="arm64"; urllib.request.urlopen("https://api.github.com/",timeout=20).close(); print("Private Mac Python and verified HTTPS work. No account or imagery used.")'
else
    arguments=(--root "$root")
    [[ "$mode" != snapshot ]] || arguments+=(--snapshot-only)
    [[ "$mode" != prepare ]] || arguments+=(--prepare-only)
    /usr/bin/env -i HOME="$HOME" PATH="$PATH" SSL_CERT_FILE="$SSL_CERT_FILE" "$python" -I -B \
        "$source_root/community/mac_starter.py" "${arguments[@]}"
fi
