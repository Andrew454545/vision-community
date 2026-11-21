#!/bin/bash
# Existing verified interpreter only; removal never downloads processing files.
set -euo pipefail
umask 077
unset BASH_ENV ENV PERL5OPT PERL5LIB PYTHONPATH PYTHONHOME DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export LC_ALL=C
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]]
source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
root="${HOME}/Library/Application Support/VISION Community"
arguments=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --root) [[ $# -ge 2 ]] || exit 2; root="$2"; shift 2 ;;
        --check-label|--check-home) [[ $# -ge 2 ]] || exit 2; arguments+=("$1" "$2"); shift 2 ;;
        *) exit 2 ;;
    esac
done
[[ "$root" == /* && "$root" != / && "$root" != *'/../'* && "$root" != */.. ]]
private="$root/python-3.14.8-20261003-arm64"
failure() {
    local result=$?
    trap - EXIT
    if [[ $result -ne 0 ]]; then
        /usr/bin/env -i PATH="$PATH" /usr/bin/perl -MFile::Basename=dirname -MFcntl=:mode,:DEFAULT -e '
            my $root=$ARGV[0]; my $folder="$root/setup-failures";
            sub plain { my($p,$missing)=@_; while($p ne "/") {
                my @s=lstat($p); return 0 if @s && (!S_ISDIR($s[2]) || S_ISLNK($s[2]));
                return 0 if !@s && !$missing; $p=dirname($p);
            } return 1; }
            plain($root,0) && plain($folder,1) or exit 1;
            mkdir($folder,0700) unless -d $folder; plain($folder,0) or exit 1;
            sysopen(my $f,"$folder/mac-removal-".time()."-$$.json",O_WRONLY|O_CREAT|O_EXCL,0600) or exit 1;
            print $f q({"status":"INCOMPLETE","phase":"mac-application-removal","code":"mac_removal_not_safe"}); close $f;
        ' "$root" || true
    fi
    exit "$result"
}
trap failure EXIT
path="$private"
while [[ "$path" != / ]]; do
    [[ -d "$path" && ! -L "$path" ]] || exit 1
    path="$(dirname -- "$path")"
done
# The verifier checks parents, files, exact hashes and the pinned internal links
# before any private Python code executes. No setup/free-space/consent flow runs.
/usr/bin/env -i PATH="$PATH" /usr/bin/perl "$source_root/macos/verify-python.pl" \
    "$source_root/macos/python-arm64-inventory.json" \
    a0f5d70672a69e5f34433bc7f2de43a2c85443af610007711d20f00334fc0c0d "$private" > /dev/null
/usr/bin/env -i HOME="$HOME" PATH="$PATH" LC_ALL=C \
    "$private/python/bin/python3.14" -I -B "$source_root/community/mac_remove.py" --root "$root" "${arguments[@]}"
