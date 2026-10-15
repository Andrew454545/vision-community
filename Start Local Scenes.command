#!/bin/bash
set -euo pipefail
unset BASH_ENV ENV PERL5OPT PERL5LIB PYTHONPATH PYTHONHOME DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
source_root="$(cd -- "$(dirname -- "$0")" && pwd -P)"
packet="${1:-}"
if [[ -z "$packet" ]]; then
    packet=$(/usr/bin/osascript -e 'POSIX path of (choose file with prompt "Choose Check this computer.json first, or your approved campaign.json")') || exit 0
fi
exec /bin/bash --noprofile --norc "$source_root/macos/Start-Vision.command" \
    --root "${HOME}/Library/Application Support/VISION Local Scenes" --local-scene-packet "$packet"
