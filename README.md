# Shutterstock Article Image Checker — Local V2

A local Streamlit + Playwright system for checking Bayut/MyBayut article images against Shutterstock Search by Image.

## No Shutterstock API required

This project does **not** require a Shutterstock API key, API secret, or token.

The checker runs locally on Windows because Shutterstock challenges Streamlit Community Cloud/datacenter browsers with its **Verification Required** screen. The actual Shutterstock check runs through the user's visible Chrome browser and normal internet connection.

## Current V2 flow

- Accept one article URL
- Accept multiple pasted URLs
- Accept Excel with an `Address` or `URL` column
- Extract feature and body images from Bayut/MyBayut articles
- Exclude obvious logos, icons, author images and social assets
- Open Shutterstock Search by Image in visible Chrome
- Try direct file inputs, Search by Image controls, camera controls, search-bar controls, frame inputs and upload areas
- Upload each article image automatically when Shutterstock exposes a usable upload control
- Compare returned Shutterstock candidate images with the article image
- Return `MATCH FOUND`, `POSSIBLE MATCH`, `NOT FOUND`, `MANUAL CHECK`, or `AUTOMATION ERROR`
- Save the actual Shutterstock asset URL when a match is detected
- Export results to Excel
- Capture the Shutterstock page when an automation failure occurs so the exact page state can be reviewed

## Main files

- `app.py` — main entry point
- `app_windows.py` — Windows wrapper that configures the event loop Playwright needs
- `app_local2.py` — current V2 Shutterstock automation checker
- `app_local.py` — previous local checker kept for reference
- `requirements.txt` — Python dependencies
- `install_local.bat` — one-time installation helper
- `run_local.bat` — starts the current V2 checker
- `START_SHUTTERSTOCK_CHECKER.bat` — downloads/updates the latest GitHub version and starts it

## Recommended Python

Use **Python 3.12**.

Do not use the free-threaded Python 3.14t interpreter for this project because Playwright/greenlet can fail under that build.

## Easiest way to run

Double-click:

`START_SHUTTERSTOCK_CHECKER.bat`

It stops an old checker on port 8501, downloads the latest GitHub project, updates the local folder, installs requirements and starts the Windows wrapper.

## Run from an existing project folder

Double-click:

`run_local.bat`

Or run manually:

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 -m streamlit run app_windows.py --server.address localhost --server.port 8501
```

## Shutterstock verification

If Shutterstock displays its slider / Verification Required screen in the visible Chrome window, complete it manually. The checker waits and continues after the verification disappears.

The app does not bypass CAPTCHA or Shutterstock security verification.

## Excel input example

```text
Address
https://www.bayut.com/mybayut/...
https://www.bayut.com/mybayut/...
```

## Hosted Streamlit Cloud

The hosted Streamlit Cloud page is not used for the Shutterstock browser automation because Shutterstock challenges datacenter browsers. The reliable free workflow is local Windows + visible Chrome.