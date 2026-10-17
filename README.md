# VISION Community

Process Street View locations on your own computer and keep the results locally.
The **invited Local Scenes preview** is available for Windows PCs and
Apple-silicon Macs. No account, subscription, global Python installation or
administrator password is needed.

## Start here

1. [Download the Local Scenes preview](https://github.com/Andrew454545/vision-community/releases/tag/local-scenes-desktop-app-preview-20261017).
   Choose the ZIP for Windows x64 or Apple-silicon Mac and extract all its files.
2. Windows: open **VISION Local Scenes.exe**. Mac: open **VISION Local Scenes.app**.
3. Choose **Check this computer**, accept setup downloads, then choose **Start / Resume**.
4. When the checks finish, choose **Save results**. Send that ZIP privately to the
   maintainer, who reviews it and sends your personal queue.
5. Open your personal queue and choose your day and night speeds. A tiny live
   trial comes first; after it succeeds, the maintainer can issue up to five
   million separate locations for this computer.

[Full simple instructions](https://github.com/Andrew454545/vision-community/releases/download/local-scenes-desktop-app-preview-20261017/START-HERE.md)
· [Prompt for a friend's Windows Codex](https://github.com/Andrew454545/vision-community/releases/download/local-scenes-desktop-app-preview-20261017/PC-CODEX-PROMPT.md)

Work saves locally and resumes after interruptions. You can opt into automatic
resume when you sign in. Choose **Pause** to keep it paused. Each person's queue
is separate; do not share it or post private check reports on GitHub.

This is an unsigned invited preview. Its first Windows run supplies actual
Windows feedback. Google must permit live imagery access on your connection;
the app stops if access is refused. See the release notes for checksums and
current limits. Do not disable computer security to run it. Your own electricity,
internet and storage are used; five million locations need about 15.4 GB for
vectors alone, plus setup, metadata and backups. Searching prepares another
copy of those vectors, so allow additional space.

The app now opens a native local window. Windows falls back to your browser if
WebView2 is unavailable; it does not install that runtime automatically. The Mac
app handles setup without Terminal and can be moved on its own. Keep the Windows
extracted folder together.

## Use your own MMA maps

After **Check this computer**, choose **My library → Add my own MMA map**.
Choose your exported JSON, then **Prepare my private queue → Open my queue here**.
Set your day/night speeds and choose **Start**. Use **My saved queues** to return
to earlier personal queues; opening always stays paused until you choose Start.
The app skips panoramas already reserved by your other personal maps. Your map results
stay local. This personal workflow is separate from maintainer-approved Community
assignments.

## Search your Scenes

Choose **My library** in the launcher or processing window. Pause processing,
describe what you want, optionally choose country/generation/view filters and
choose **Search my Scenes**. Use **Save results as a map** for an MMA-compatible
JSON map. Text searches run locally without live imagery requests. Street View
examples retrieve reference imagery from Google. Choose **Use a photo from this
computer** to search with your own photo instead, without a Google request. You
can blend the photo with a description and search your own MMA maps separately.

Choose **Choose storage folder** in the launcher for a local or external disk.
Existing queues keep their original location and progress. Small MMA JSON maps
can supply reference views; online MMA export is optional and uses a key held
only in memory. Owner import and catalog preparation tools are available.

First-user Windows/live feedback, actual contributor ingestion and Objects are
next in [the next-phase outline](https://github.com/Andrew454545/vision-community/releases/download/local-scenes-desktop-app-preview-20261017/NEXT-PHASE.md).

**The older hosted contribution service, uploads, credits and online search
remain closed.** Keep old VISION folders, saved work and private account codes.
Leave older automatic-processing jobs paused. The local preview does not upload
results or earn credits.

[Developer guide](https://github.com/Andrew454545/vision-community/blob/codex/windows-production-readiness/docs/DEVELOPER_GUIDE.md)
· [Contributing](CONTRIBUTING.md)
