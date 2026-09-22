# How to help

Places use the same four-view indexer as the VISION app. That program cannot run inside the browser, so places run in Terminal. Objects can still use Start on the site.

1. Open the site.
2. Click **Get a free account**. Write down or screenshot the code. That code is your only login.
3. Click **Copy place command**. Open Terminal, paste, and press Return. Leave that window open.
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

The computer needs the VISION `mma-vision` program and the `siglip-b16-224-canonical` model folder. They are not in this repo. Set `VISION_FOUR_VIEW_BINARY` and `VISION_MODEL_DIR` if they are not in the usual VISION folders. Create the account on the site first so the work counts toward the same search. Object indexing in Terminal is still `python3 -m community.contribute --lane object`.
