# Owner key setup

**Operator source only. Do not run during the [cost hold](COST_STOP_20261012.md).**
No real saved credential was read or written to build this component. Contributors
do not need this tool or an owner key.

After separate activation/budget approval, an operator can put the already
authorized coordinator key in their own OS vault using
[`owner-credential.py`](../owner-credential.py). This neither creates a server
key nor changes the server. Keep the key out of GitHub, chat, configuration,
arguments and environment variables.

1. Select the private [owner configuration](OWNER_SEARCH_SERVICE.md) and verify
   its independently supplied SHA-256 and destination.
2. In an intentional interactive terminal, run the private Python with `-I -B`,
   the absolute `owner-credential.py` path, `--config ABSOLUTE_PRIVATE_CONFIG_PATH`
   and `--config-sha256 INDEPENDENT_CONFIG_SHA256`.
3. Check the displayed HTTPS destination. Enter the existing key twice at the
   hidden prompts. A `stored` reply confirms local vault readback. `unchanged`
   means that exact key was already present.

Redirected input and password-echo fallback are refused. There is no secret
argument, plaintext-file option or environment fallback. Successful setup never
creates an activation marker, clears PAUSE/STOP, registers a task, loads a model,
contacts the coordinator or changes balances/paid replies.

Windows stores one local, non-roaming generic credential for the current user.
The target is `VISIONCommunity.OwnerSearch.` followed by the SHA-256 of the
canonical HTTPS origin; the account is `owner-search-agent`. The existing runner
reads that exact item. Missing and denied credentials are different outcomes:
denial, an unrelated account or malformed data never authorizes an overwrite.

Mac uses the Security framework and the existing current user's
`Library/Keychains/login.keychain-db`. The key travels in private process memory,
not a child command line. Setup neither creates/unlocks a Keychain nor changes
item access controls. A real Mac can require normal OS consent, including when
the runner subsequently reads the item; grant no automatic bypass. The Windows
and Mac API checks here use fixtures, not real vaults or a real Mac.

An existing different key is preserved. Deliberate rotation additionally requires
`--replace-sha256 INDEPENDENT_OLD_KEY_SHA256`; a stale old-key pin refuses the
change. Setup and the owner runner share a process lock. This serializes this
application's operations, but the OS APIs do not provide compare-and-swap against
unrelated simultaneous OS edits. Stop other credential editors during rotation.

An ambiguous/denied readback keeps the possibly successful write for operator
recovery. Do not delete it or repeatedly rotate it to make the message disappear.
No automatic rollback or item deletion occurs. Outputs contain fixed status/error
codes; native errors, account paths and key bytes are not reported. Mutable native
password buffers are cleared after writing; Python/OS memory is not claimed to be
fully erased.

The [Windows synthetic receipt](evidence/owner-credentials-20261012.json) records
the checks and their limits. Trusted signed Windows/Mac installation, actual vault
consent/readback and approved reboot/endurance acceptance remain release gates.
