# Windows desktop page and recovery, 19 October 2026

The existing Windows WebView2 runtime (155.0.4283.62) successfully initialized
and rendered the shipped local VISION page. The hidden owned test used the actual
`SceneWindow.cs` with a test entry point, the verified cached SDK, and an empty
real local application/library backend. It did not use a substitute HTML page.
A captured screenshot was reviewed: the library title, saved-queue controls,
map section and empty Scene library rendered correctly.

The page authenticated to its local backend; an unauthenticated request was
refused, the token left the visible URL, the personal-map and photo primitives
were available, and layout had nonzero expected dimensions. The production host
cancelled an outside navigation before a request. All nine observed application
requests were loopback GETs, with zero mutations. The test blocks outside web
resources and sets child-only flags to suppress background networking/component
updates. It uses an isolated InPrivate profile under the private evidence folder.
No WebView installation, model setup, inference or imagery request ran.

This is actual Windows initialization/rendering evidence, extending the earlier
[self-check evidence](WINDOWS_LOCAL_PREVIEW_20261019.md). It is a hidden test of the
production host source with a dedicated test entry, not an interactive participant
installation or execution of the published EXE in normal mode. Native file panels,
visible user interaction, first-computer setup and real processing remain unverified.

Two focused startup fixes also passed. The private native host folder must now
contain exactly its manifest and named pinned files. An extra `.exe.config` or
subdirectory is refused before execution and preserved for diagnosis. Those
folders have no legitimate mutable state; WebView profiles live elsewhere.
If writing a failure report itself fails, the existing authenticated browser
fallback still opens. Shutdown continues to suppress fallback. No report is
claimed saved when persistence fails.

Two targeted Python tests first demonstrated the original failures and then
passed after the fixes. They use synthetic host files and mocked native/browser
execution and report refusal; they are separate from the actual Windows rendering
check. Original failing output remains private. No broad suite, model matrix,
Google/Cloudflare/R2 access, Actions, task registration or old-job restart ran.
No mathematical, qualification, assignment or model changes are included.

[Machine-readable evidence](evidence/windows-webview-first-use-20261019.json)
records source and receipt hashes and exact limits. Private logs/screenshot are
under `work/local-scene-webview-20261019`; keep them off public issues. The public
17 October preview and earlier clean local kit are unchanged and do not yet carry
these Python host-boundary fixes. Reuse this evidence until relevant inputs change.
