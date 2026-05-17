# gcdocs-update-collector

Watch `https://cloud.google.com/sitemap.xml`, detect added/updated docs pages
under configured path prefixes for chosen languages, and store HTML snapshots
+ rendered-text diffs in GCS for later notification (Discord, etc.).

State lives in a single SQLite file on GCS; the Cloud Run Job downloads it at
startup and writes it back at the end of each run. Inspect locally with the
ubiquitous `sqlite3` CLI:

```sh
gcloud storage cp gs://<bucket>/state/state.sqlite /tmp/state.sqlite
sqlite3 /tmp/state.sqlite \
  "SELECT detected_at, change_type, url FROM revisions ORDER BY detected_at DESC LIMIT 20;"
```

## Layout

```
src/collector/
  main.py        # entrypoint, orchestrates a single run
  config.py      # config + URL classification (language + watch_paths)
  sitemap.py     # sitemap index + child sitemap parsing
  state.py       # SQLite schema and access (downloaded from / uploaded to GCS)
  fetcher.py     # HTTP client with simple retry
  extractor.py   # strip header/footer/nav, keep main article HTML + text
  differ.py      # unified text diff + difflib.HtmlDiff HTML page
  storage.py     # GCS client + key conventions
config/config.yaml
Dockerfile
terraform/      # bucket, Artifact Registry, Cloud Run Job, two Schedulers
```

## GCS layout

```
gs://<bucket>/
  state/state.sqlite
  snapshots/<lang>/<sha256(url)[0:2]>/<sha256(url)>/<revision_id>.html
  diffs/<lang>/<sha256(url)[0:2]>/<sha256(url)>/<revision_id>.diff.txt
  diffs/<lang>/<sha256(url)[0:2]>/<sha256(url)>/<revision_id>.diff.html
```

## Run locally

```sh
pip install -e .
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
export GCDOCS__BUCKET=your-bucket
python -m collector.main
```

Edit `config/config.yaml` to add/remove `watch_paths` or `languages`.
URL filtering takes effect on the next run; existing rows are kept.

## Build and push the image

```sh
REGION=asia-northeast1
PROJECT=your-gcp-project
REPO=gcdocs-collector-docker
IMAGE=$REGION-docker.pkg.dev/$PROJECT/$REPO/collector:0.1.0

gcloud auth configure-docker $REGION-docker.pkg.dev
docker build -t $IMAGE .
docker push $IMAGE
```

## Deploy with Terraform

```sh
cd terraform
cp terraform.tfvars.example terraform.tfvars
# fill in project_id and image_uri
terraform init
terraform apply
```

The two Cloud Scheduler jobs fire at 03:00 and 19:00 Asia/Tokyo by default
(`var.schedule_morning_cron` / `var.schedule_evening_cron`).

## Tuning

- `max_fetch_per_run`: safety cap on HTML fetches per run. URLs beyond the cap
  remain "new/updated" and are picked up on the next run.
- `watch_paths`: path prefix after the language segment, e.g. `/vertex-ai`
  matches `https://cloud.google.com/vertex-ai/...` and
  `https://cloud.google.com/ja/vertex-ai/...`.
- Child sitemaps whose `lastmod` did not advance since the last run are
  skipped entirely (180 sitemaps -> usually a handful per run).
