#!/bin/bash
set -euo pipefail
unset BASH_ENV ENV PERL5OPT PERL5LIB PYTHONPATH PYTHONHOME DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
source_root="$(cd -- "$(dirname -- "$0")" && pwd -P)"
packet="${1:-}"
if [[ -z "$packet" ]]; then
    choice=$(/usr/bin/osascript -e 'button returned of (display dialog "Check this computer first. After approval, process your queue or search your saved Scenes." buttons {"My library", "Open my queue", "Check this computer"} default button "Check this computer")') || exit 0
    if [[ "$choice" == "Check this computer" && -f "$source_root/Readiness/Check this computer.json" ]]; then
        packet="$source_root/Readiness/Check this computer.json"
    elif [[ "$choice" == "My library" ]]; then
        packet="$source_root/community/local_scene_library.json"
    else
        packet=$(/usr/bin/osascript -e 'POSIX path of (choose file with prompt "Choose campaign.json from your personal queue")') || exit 0
    fi
fi
exec /bin/bash --noprofile --norc "$source_root/macos/Start-Vision.command" \
    --root "${HOME}/Library/Application Support/VISION Local Scenes" --local-scene-packet "$packet"
