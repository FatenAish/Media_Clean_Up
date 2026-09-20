# Shutterstock Article Image Checker

A local Streamlit + Playwright system for checking article images against Shutterstock Search by Image.

## No Shutterstock API required

This project does **not** require a Shutterstock API key, API secret, or token.

The checker is designed to run locally on Windows because Shutterstock currently shows its **Verification Required** challenge to Streamlit Community Cloud/datacenter browsers. The GitHub repository remains the source of the project, while the actual Shutterstock checking runs through your own visible Chrome browser and internet connection.

## What the system does

- Accepts one article URL
- Accepts multiple pasted URLs
- Accepts Excel with an `Address` or `URL` column
- Extracts feature and body images
- Excludes obvious logos, icons, author images and social assets
- Opens Shutterstock Search by Image automatically
- Uploads each article image
- Compares returned Shutterstock candidates with the article image
- Returns `MATCH FOUND`, `POSSIBLE MATCH`, `NOT FOUND`, `MANUAL CHECK`, or `AUTOMATION ERROR`
- Saves the actual Shutterstock asset URL when a match is detected
- Exports results to Excel

## Recommended Python

Use **Python 3.12**.

Do not use the free-threaded Python 3.14t interpreter for this project because Playwright/greenlet can crash under that build.

## Install on Windows

Download or clone this repository, then double-click:

`install_local.bat`

This installs the Python dependencies and Playwright browser support.

## Run

Double-click:

`run_local.bat`

Or run manually:

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium
py -3.12 -m streamlit run app.py
```

The Streamlit interface opens in your browser. A separate visible Chrome window is used for Shutterstock automation.

## Shutterstock verification

If Shutterstock displays its slider / Verification Required screen in the visible Chrome window, complete it manually. The app waits for verification to finish and then continues automatically.

The app does not bypass CAPTCHA or Shutterstock security verification.

## Main files

- `app.py` — main entry point
- `app_local.py` — local Shutterstock automation
- `requirements.txt` — Python dependencies
- `install_local.bat` — one-time Windows setup
- `run_local.bat` — starts the checker

## Excel input example

```text
Address
https://www.bayut.com/mybayut/...
https://www.bayut.com/mybayut/...
```

## Why the hosted Streamlit Cloud page does not perform the check

Shutterstock challenges the cloud/datacenter browser before Search by Image can load. Because the user does not have Shutterstock API access, the reliable free workflow is to keep the Streamlit UI local and let Playwright control the user's own Chrome session.
