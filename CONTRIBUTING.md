# How to help

You do not need to be technical. A web browser is enough.

1. Open the site.
2. Click **Get a free account**. Write down or screenshot the code. That code is your only login.
3. Click **Start** and leave the tab open.
4. When the bar reaches 100,000, click **Search**, then **Download**.
5. Open the downloaded file on [map-making.app](https://map-making.app).

Keep the tab in the foreground if you can. Pause if you need to stop.

Coming back later: paste your saved code and click Restore.

## Faster (optional)

Only if you already have this project folder on your computer:

```sh
python3 -m pip install -r requirements.txt
python3 -m community.contribute --lane scene --pace medium --recovery-code YOUR_CODE
python3 -m community.local_search --query community/web/sample-query.json --recovery-code YOUR_CODE
```

Create the account on the site first so the work counts toward the same search. Most people should skip this and just click Start. Search on this computer uses the same folder; there is no extra server to pay for.
