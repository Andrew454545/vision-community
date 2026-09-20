# Contribute with the local worker

The website assigns exclusive batches and stores embeddings. **Street View is
fetched on your computer**, then discarded. Do not upload JPEG/PNG bytes.

## Setup

You need Python 3.12+ and [Pillow](https://pypi.org/project/Pillow/).

```sh
cd vision-community
python3 -m pip install -r requirements.txt
```

The GitHub repository is private. Clone it from the invitation you were sent,
not from a public URL. After a clone:

```sh
python3 -m community.contribute \
  --url https://vision-community.visioncommunity.workers.dev \
  --lane scene \
  --pace medium \
  --recovery-code YOUR_CODE
```

`--pace` is `slow`, `medium`, or `max`. That only changes how many CPU workers
you run. Credits stay 1 per verified scene and 10 per verified object. One
search still costs 100,000 units. There is no trial.

Processing uses the same Street View views as VISION.app: four compass views
for scenes, a six-face cube for objects. This worker does **not** run SigLIP,
RF-DETR, YOLOE, or OWLv2. Those stay in the local VISION app. After locations
are published here, the owner can export poses and index them there.

`--lane object` indexes the six-face object cube instead of four-view scenes.

Create an anonymous account on the site first and paste the recovery code so
CLI work lands on the same balance you search with. The CLI writes that code to
`~/.config/vision-community/session.json` (mode 0600). Later runs can omit
`--recovery-code`. `Ctrl+C` releases the exclusive lease so someone else can
claim those locations.

`--url` defaults to the hosted Worker. Pass a loopback URL only for a local
server.

## What this machine does

Each leased location downloads VISION’s Street View views (four compass
thumbnails for scenes, six cube faces for objects), downsamples them to 16×16,
and uploads only the `community-visual-v1` embedding. The site audits one Street
View location per batch by re-fetching it; invented test panos are always
recomputed.

## Browser processing

The site can still process a **small** batch in a tab. Browsers cannot call
Google directly, so that path proxies thumbnails through the Worker and is
capped (1/4/8 scenes). Use the CLI for real volume.
