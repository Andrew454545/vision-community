#!/bin/bash
unset BASH_ENV ENV PERL5OPT PERL5LIB PYTHONPATH PYTHONHOME DYLD_INSERT_LIBRARIES DYLD_LIBRARY_PATH
exec /bin/bash --noprofile --norc "$(cd -- "$(dirname -- "$0")" && pwd -P)/macos/Start-Vision.command" "$@"
