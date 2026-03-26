<p align="center">
  <img src="riftbound-oracle.png" alt="Riftbound Oracle" width="100%" />
</p>

# Riftbound Oracle

A processing pipeline that converts Riftbound TCG source material (cards, rules, tournament guidelines) into structured markdown, then syncs it to Google Drive for consumption by NotebookLM.

## Setup

```bash
npm install
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
npm run build
```

## Usage

```bash
# Process all sources from manifest
npm run oracle process

# Process only a specific category
npm run oracle process -- --only=cards
npm run oracle process -- --only=rules
npm run oracle process -- --only=tournament

# Upload to Google Drive
npm run oracle upload

# Check processing status
npm run oracle status
```

## Sources

All sources are declared in [`manifests/sources.yaml`](manifests/sources.yaml). Supported types:

| Type | Description |
|---|---|
| `riftcodex` | Fetches card data from the [Riftcodex API](https://riftcodex.com/) |
| `pdf` | Extracts text from local PDF files via pdfplumber |
| `html` | Converts local HTML files to markdown via turndown |
| `url` | Fetches a URL and converts to markdown |

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_CLIENT_ID` | OAuth2 client ID for Drive upload |
| `GOOGLE_CLIENT_SECRET` | OAuth2 client secret |
| `DRIVE_FOLDER_ID` | Target Google Drive folder ID |
| `RIFTCODEX_API_URL` | Riftcodex API base URL (default: `https://api.riftcodex.com`) |
