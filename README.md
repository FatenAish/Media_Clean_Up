# Media_Clean_Up — Shutterstock Article Image Checker

Checks article images against Shutterstock and returns the matching Shutterstock asset URL when a likely match is found.

## Streamlit Cloud

The hosted app now uses Shutterstock's **official Computer Vision API** instead of automating the Shutterstock website. This avoids the `Verification Required` challenge that blocks cloud/datacenter browsers.

You need a Shutterstock API application with Computer Vision access enabled. The app accepts either:

- a Shutterstock API bearer token, or
- an API key + API secret

You can enter credentials in the Streamlit sidebar, or add them as Streamlit secrets:

```toml
SHUTTERSTOCK_API_TOKEN = "your-token"
```

or:

```toml
SHUTTERSTOCK_API_KEY = "your-key"
SHUTTERSTOCK_API_SECRET = "your-secret"
```

The official reverse-image flow used by the app is:

1. `POST /v2/cv/images`
2. `GET /v2/cv/similar/images`
3. Compare returned Shutterstock previews against the article image
4. Return `MATCH FOUND`, `POSSIBLE MATCH`, or `NOT FOUND`
5. Save the Shutterstock asset page URL and asset ID

> Shutterstock requires Computer Vision access to be enabled for the API application. A normal website subscription alone does not automatically enable these API endpoints.

## Local Windows mode

On Windows, `app.py` automatically loads `app_local.py`, which uses visible Chrome and Playwright.

Install once:

```bat
install_local.bat
```

Run:

```bat
run_local.bat
```

Or manually:

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium
py -3.12 -m streamlit run app.py
```

Use Python **3.12**, not the free-threaded `3.14t` build.

## Inputs

The app accepts:

- one article URL
- multiple pasted URLs
- Excel with an `Address` or `URL` column

## Output

The report includes:

- Article URL
- Article title
- Image position
- Article image URL
- Shutterstock status
- Shutterstock asset URL
- Shutterstock asset ID
- Confidence
- Number of API results
- Notes

The results can be downloaded as Excel.
