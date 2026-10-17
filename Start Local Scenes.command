#!/bin/bash
set -euo pipefail
unset BASH_ENV ENV PERL5OPT PERL5LIB PYTHONPATH PYTHONHOME DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
source_root="$(cd -- "$(dirname -- "$0")" && pwd -P)"
packet=''
storage=''
accepted=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --accept-downloads) accepted=1; shift ;;
        --packet) [[ $# -ge 2 ]] || exit 2; packet="$2"; shift 2 ;;
        --storage) [[ $# -ge 2 ]] || exit 2; storage="$2"; shift 2 ;;
        *) [[ -z "$packet" ]] || exit 2; packet="$1"; shift ;;
    esac
done
if [[ -z "$packet" ]]; then
    choice=$(/usr/bin/osascript -e 'set chosen to choose from list {"Check this computer", "Open my queue", "My library", "Choose storage folder"} with prompt "What would you like to do?" default items {"Check this computer"}' -e 'if chosen is false then error number -128' -e 'item 1 of chosen') || exit 0
    if [[ "$choice" == "Check this computer" && -f "$source_root/Readiness/Check this computer.json" ]]; then
        packet="$source_root/Readiness/Check this computer.json"
    elif [[ "$choice" == "My library" ]]; then
        packet="$source_root/community/local_scene_library.json"
    elif [[ "$choice" == "Choose storage folder" ]]; then
        storage=$(/usr/bin/osascript -e 'POSIX path of (choose folder with prompt "Choose a folder or disk for new Scene work. Existing files stay in place.")') || exit 0
        packet="$source_root/community/local_scene_library.json"
    else
        packet=$(/usr/bin/osascript -e 'POSIX path of (choose file with prompt "Choose campaign.json from your personal queue")') || exit 0
    fi
fi
arguments=(--root "${HOME}/Library/Application Support/VISION Local Scenes" --local-scene-packet "$packet")
[[ $accepted -eq 0 ]] || arguments+=(--accept-downloads)
[[ -z "$storage" ]] || arguments+=(--select-scene-storage "$storage")
exec /bin/bash --noprofile --norc "$source_root/macos/Start-Vision.command" "${arguments[@]}"
