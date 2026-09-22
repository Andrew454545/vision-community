# How to help

Scenes use the same four-view indexer as the VISION app. Objects use the same hybrid object indexer (RF-DETR, YOLOE, and OWLv2). Those programs cannot run inside the browser, so both run in Terminal.

1. Open the site.
2. Click **Get a free account**. Write down or screenshot the code. That code is your only login.
3. Click **Copy scene command**, or switch to Objects and click **Copy object command**. Open Terminal, paste, and press Return. Leave that window open.
4. When the bar reaches 100,000, copy the search command and run it in Terminal.
5. Connect [map-making.app](https://map-making.app) with an API key to add the results to a map, or copy/download the JSON and drop it onto the local Map Making App.

If the VISION app is already indexing on the same computer, leave speed on Gentle.

Coming back later: paste your saved code and click Restore.

```sh
python3 -m pip install -r requirements.txt
python3 -m community.vision_index --pace slow --recovery-code YOUR_CODE
python3 -m community.vision_index --search --prompt "red barn in snow" --recovery-code YOUR_CODE
python3 -m community.send_mma YourSearch.json --new-map
```

The computer needs the VISION `mma-vision` program, the `siglip-b16-224-canonical` model folder, the `vision-object` program, and the `object-hybrid-v1` model folder. They are not in this repo. Set `VISION_FOUR_VIEW_BINARY`, `VISION_MODEL_DIR`, `VISION_OBJECT_BINARY`, and `VISION_OBJECT_MODEL_DIR` if they are not in the usual VISION folders. Create the account on the site first so the work counts toward the same search. Object indexing is `python3 -m community.object_index`.
