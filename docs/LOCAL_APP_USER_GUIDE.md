# VISION Local Scenes

Your computer does the processing. Your results stay on your computer.
No account, subscription or Python installation is needed.

## First time: check this computer

1. Extract the whole **VISION Local Scenes** kit. Keep its files together.
2. Windows: open **VISION Local Scenes.exe**. Apple-silicon Mac: open
   **VISION Local Scenes.app** (macOS13+). The Mac app can be moved on its own;
   keep the Windows extracted folder together.
3. Click **Check this computer**. It is already selected on Windows.
4. Accept setup downloads, then choose **Start / Resume** in the local window.
   Setup downloads private Python and about 1 GB of model files once.
5. When the checks finish, choose **Save results**. Send that ZIP to the maintainer.
   They will send your personal queue after reviewing it.

The same 112 locations are checked at each offered speed. A faster profile that
doesn't pass is not approved. You do not need to understand the test report.

## When you receive your queue

Before opening a large new queue, choose **Choose storage folder** in the launcher
and select a local disk or connected external drive with enough space. New queues
and searchable copies use **VISION Local Scenes Data** there. Existing queues
keep their original location and progress. Keep earlier work folders connected;
**Refresh library** can recover their completed Scenes. A missing selected drive
stops startup instead of silently placing work on another disk.

1. Extract your whole personal queue folder. Keep it somewhere permanent.
2. Open the same launcher, choose **Open personal queue** (Windows) or **Open my queue**
   (Mac), and select **campaign.json** in that folder.
3. Choose your day and night speeds. Choose **Save settings**, then **Start / Resume**.

The default is Medium during the day and Maximum checked speed at night.
You can change the times or choose Pause for either period. Only speeds checked
and approved for this computer are used.

To resume after signing back in, tick **Resume automatically when I sign in to
this computer** and choose **Save automatic start**. Keep the kit and queue folders
in place. Work resumes from saved progress after a program interruption. A power
failure may repeat the last unfinished group. Explicit **Pause** stays paused.

Keep the computer plugged in. Processing pauses on battery by default. Closing the
browser tab leaves processing running; a native window asks to pause and close.
**Pause** or **Exit** stops after saving the
current group. This can take several minutes. Reopen the launcher to return.

The window shows your saved-work folder. Keep it and your assigned queue. Never
give your queue to someone else: each contributor has separate locations.
A five-million-location index needs about 15.4 GB for vectors alone; allow extra
space for setup, metadata and backups. Processing stops safely when disk space is low.

## Sending completed results

Pause, then choose **Save results**. For a large queue, the window shows an
**exports** folder containing all completed results and their checksums. Send
that whole folder to the maintainer using your agreed private transfer method.
For the compatibility check or a small legacy packet, choose where to save its ZIP
in the native file panel (or browser downloads when using the fallback interface).
Nothing is uploaded automatically. Keep the original saved-work folder to resume.

## Search your saved Scenes

Open the launcher and choose **My library**. You can also switch to **My library**
in the processing window. Finished groups are added automatically; **Refresh library**
recovers completed work if an earlier version or interruption missed it.

Pause processing before searching. Describe what you want, optionally choose a
country, generation or camera direction, then choose **Search my Scenes**.
Text searches run on this computer using your saved indexes. The first search
prepares searchable segments and needs additional disk space, roughly another
15.4 GB for five million locations. Later searches reuse unchanged segments.

Choose **Open Street View** to inspect a result, or **Save results as a map** to
download an MMA-compatible JSON map. Under **Use a Street View example**, you
can supply a panorama and camera pose, or choose **Use as example** on a result.
Reference-example searches retrieve imagery from Google; text searches do not.
If Google refuses access, use text search or wait for normal access on that
connection. Uploading an arbitrary photo and direct MMA connections come later.

You can choose a small MMA reference JSON map, up to 2 MB, under **Use a Street
View example**. The app selects up to eight panorama views from it. Other map
fields stay out of the search request. No imagery is fetched until you search.

For local MMA, open a map and drop the saved results JSON onto its window.
To send online, open **Send to an online MMA map**, connect with your own API key,
choose the destination and confirm **Send these results to this map**. The key
stays in memory until disconnect or exit; VISION does not save it. If delivery is
uncertain, check that map before another import. The app holds the export rather
than automatically retrying it.

This invited preview is unsigned. If your computer refuses it, stop and ask the
maintainer for trusted installation help. Do not disable security settings.
The app is free; your electricity, internet data and storage are still used.
To process your own MMA map, open **My library → Add my own MMA map**. Choose
your exported JSON, choose **Prepare my private queue**, then **Open my queue
here**. Choose your day/night speeds and Start. Finish **Check this computer** first.
Use **My saved queues** to return to earlier queues. Opening stays paused until
you choose Start. **Save a queue backup** is optional; extract it and open
**campaign.json** with the launcher if needed.
Your own map results stay local and can be searched under **My MMA maps**.

To search an Object index you already have, open **My library → Search saved
Objects**. Choose **Set up Object search**, accept its optional private download
(about 900 MB), then import an Object library ZIP from the maintainer. Search by
object or description, country, generation and confidence. These results use the
same Save results as a map button. A normal MMA map is not an Object index.
**Stop library action** cancels an outstanding library action.

New Object processing and automatic sharing are planned for later.

The Mac app requires macOS13 or later. Windows uses WebView2 when available;
otherwise the existing browser interface opens. Neither path installs WebView2
automatically. The older **Start Local Scenes.command** remains a Mac fallback.

If Google refuses imagery access, the app stops and keeps your queue. Resume
only after imagery access works normally on that connection. The computer check
uses fixed local images, so passing it does not guarantee Google will supply live imagery.
