# Start here: VISION Local Scenes

[Download the invited local preview](https://github.com/Andrew454545/vision-community/releases/tag/local-scenes-desktop-app-preview-20261017). Choose Windows x64 or Apple-silicon Mac.


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

## Process your own MMA map

After the computer check, choose **My library → Add my own MMA map**.

1. Choose an MMA JSON export with panorama IDs, up to 100,000 locations or 20 MB.
2. Choose **Prepare my private queue**, then **Open my queue here**.
3. Set your day/night speeds, then choose **Start**.

The same app window handles your queue and library. Use **My saved queues** to
return to another personal map. Opening a queue never starts processing by itself,
and the app prevents two windows from opening the same queue. **Save a queue
backup** is optional: extract it and open **campaign.json** through the launcher
if needed. The received-queue steps below are for assigned or backup ZIPs.

If some locations have no saved country, select their country before preparing.
Only choose a fallback country if it applies to all locations missing one. Your
map and results stay local. Importing overlapping personal maps skips panoramas
already reserved. Community queues still require maintainer review and assignment.

## When you receive or prepare your queue

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
browser tab leaves processing running; the native window asks to pause and close. **Pause** or **Exit** stops after saving the
current group. This can take several minutes. Reopen the launcher to return.

The window shows your saved-work folder. Keep it and your assigned queue. Never
give your queue to someone else: each contributor has separate locations.
A five-million-location index needs about 15.4 GB for vectors alone; allow extra
space for setup, metadata and backups. Processing stops safely when disk space is low.

## Sending completed results

Pause, then choose **Save results**. For a large queue, the window shows an
**exports** folder containing all completed results and their checksums. Send
that whole folder to the maintainer using your agreed private transfer method.
For the compatibility check or a small legacy packet, a ZIP goes to your browser downloads.
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
Objects and automatic sharing are planned for later.

If Google refuses imagery access, the app stops and keeps your queue. Resume
only after imagery access works normally on that connection. The computer check
uses fixed local images, so passing it does not guarantee Google will supply live imagery.

## Have the older hosted version?

Hosted processing and online search are paused. Keep your VISION folder and
private account code; old saved work and credits are preserved. You do not need
to reinstall the old version. Leave its automatic jobs paused. The separate local
preview uses no hosted account, credits or automatic upload.

## Search with a photo

In **My library**, open **Use a photo from this computer**, choose a JPEG, PNG or
WebP, optionally type a description, then choose **Search my Scenes**. The photo
stays local. Choose **My MMA maps** to search only your personal map results.

Downloads now run serially, with 30-second pauses between saved groups. This
reduces request pressure; it does not guarantee that Google will allow access.

## Native app windows

On Mac, use **VISION Local Scenes.app** on macOS13 or later; the older command
starter is a fallback. Windows uses a WebView2 app window when available and
the browser interface otherwise. Setup does not install WebView2 automatically.
Native windows ask to pause before closing. Save maps and report ZIPs using the
native save dialog; the browser fallback uses normal browser downloads.

The Mac page was checked with hidden WebKit. Interactive file dialogs and actual
Windows use still need first-user feedback. These downloads remain unsigned.
