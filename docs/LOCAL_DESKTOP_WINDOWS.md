# Local desktop windows

The native-window kit adds **VISION Local Scenes.app** on Apple-silicon Macs
(macOS13+) and a WebView2 window on Windows. The Mac launcher opens without a
Terminal window. The Mac app contains its sealed setup files and can be moved
on its own; keep the Windows extracted kit together. The app verifies the
sealed source inventory before setup. Windows still starts through
**VISION Local Scenes.exe**. Setup keeps Python/models private to VISION.

The desktop view uses the same local backend, check, queue, library and search.
Opening it never starts indexing. Choose Start yourself. Closing the native
window asks to pause and exit; the backend saves/stops at its existing group
boundary. Closing the launcher during setup or a running backend is blocked.
The existing browser interface remains available if WebView2 is missing or the
optional view cannot start. No runtime installation or update is attempted by
the window host.

The view accepts an exact authenticated127.0.0.1 connection, blocks navigation
away from that origin, and opens user-clicked HTTPS links in the system browser.
File inputs and downloads use native file panels. Mac WebKit uses a nonpersistent
data store; Windows WebView2 uses an InPrivate session with autofill/password
saving disabled. Camera/microphone features are not part of this application.
Backend API keys remain governed by the memory-only MMA connection. Private
diagnostic logs are retained; this is not a secure-erasure claim.

Reopen asks the existing view to come forward over the authenticated local API.
There is no second backend or queue worker. The Python process owner supervises
the view. A stopped backend closes its view; shutdown has a bounded fallback
that terminates only its owned wrapper if the view stops responding.

These are unsigned invited builds. Signing/notarization and real Windows use
remain separate from local compilation. Native file-panel and interactive UI
behavior must be reported as unverified until actually used; a non-GUI self-check
or hidden rendering check is not evidence of those interactions.

The clean Mac build passed an actual hidden WebKit rendering/authentication
check of the shipped page. Both complete ZIPs and inventories passed. The first
hidden check stopped before loading: Foundation rewrote a canonical/private/tmp
connection path to linked/tmp. The corrected reader checks the original POSIX
path, retains no-link checks and reads a bounded regular file. The original
failure remains preserved. See [the evidence](evidence/local-native-desktop-20261017.json).

## Build locally

Use the existing local-pilot builder with **--native-windows**. For Windows,
also supply **--webview2-sdk** and the existing **--windows-reference-dir**.
The SDK folder contains the four files pinned in
[the SDK lock](../packaging/webview2-sdk-lock.json). The fixed NuGet package was
checked against its published SHA512; only the required assemblies/loader and
license are redistributed. The builder makes no network calls. Its receipts
record source hashes, platform and actual execution limits.

The compiled view and its dependencies are included in the sealed release
inventory, then reverified and copied into a content-addressed private folder.
Modified files never execute. Model/pipeline pins and Scene qualification remain
unchanged.

The Windows distribution follows [Microsoft's WebView2 distribution guidance](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution).
Mac HTTP permission is limited to local networking using
[Apple's local-networking setting](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking);
no global transport-security exception is enabled.
