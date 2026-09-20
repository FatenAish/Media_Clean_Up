# Shutterstock Article Image Checker

A Streamlit + Playwright system for checking article images against Shutterstock Search by Image.

## Important

Shutterstock is currently showing **Verification Required** to Streamlit Community Cloud / datacenter browsers. Because of that, the reliable setup is to run this project **locally on Windows** while Playwright controls your visible Chrome browser.

The GitHub repository remains the source of the project; you simply run it from your PC.

## What the system does

- Accepts one article URL
- Accepts multiple pasted URLs
- Accepts Excel with an `Address` or `URL` column
- Extracts the feature image and article body images
- Excludes obvious logos, icons, author images and social assets
- Opens Shutterstock Search by Image
- Uploads each article image automatically
- Checks returned Shutterstock candidate images
- Returns:
  - `MATCH FOUND`
  - `POSSIBLE MATCH`
  - `NOT FOUND`
  - `MANUAL CHECK`
  - `AUTOMATION ERROR`
- Saves the actual Shutterstock image page URL when a match is found
- Exports results to Excel

## Recommended Python

Use **Python 3.12**.

Do not use the free-threaded Python 3.14t interpreter for this project because Playwright/greenlet may crash under that build.

## Install on Windows

Clone or download this repository, then double-click:

`install_local.bat`

That installs the Python requirements and Playwright browser support.

## Run

Double-click:

`run_local.bat`

Or run manually:

```bat
py -3.12 -m streamlit run app.py
```

The Streamlit interface opens in your browser. A separate visible Chrome window is used for Shutterstock automation.

## Shutterstock verification

If Shutterstock displays its slider / Verification Required screen in the visible Chrome window, complete it manually. The app waits for the verification to finish and then continues automatically.

The app does not bypass CAPTCHAs or security verification.

## Main files

- `app.py` — main entry point; routes Windows users to the working local app
- `app_local.py` — full local automation system
- `requirements.txt` — Python dependencies
- `install_local.bat` — one-time Windows setup
- `run_local.bat` — starts the app

## Excel input example

```text
Address
https://www.bayut.com/mybayut/...
https://www.bayut.com/mybayut/...
```

## Why Streamlit Cloud is not used for the checking step

The hosted Streamlit server is receiving Shutterstock's Verification Required challenge before Search by Image can load. This is an external anti-bot/security restriction from Shutterstock, not an article-image matching issue.

Running the Streamlit app locally keeps the same interface while the Shutterstock requests originate through your normal browser session and connection.
