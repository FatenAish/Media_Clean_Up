Shutterstock Article Image Checker
Local Streamlit app for checking whether article images appear in Shutterstock reverse-image search.
What it does
Accepts:
one article URL
multiple pasted article URLs
Excel with an `Address` or `URL` column
Extracts feature and body images from each article
Excludes obvious logos/icons/social images
Resizes images before upload
Opens Shutterstock Search by Image automatically with Playwright
Compares Shutterstock result thumbnails with the article image using:
perceptual hash
SIFT feature matching + RANSAC geometry
Returns:
MATCH FOUND
POSSIBLE MATCH
NOT FOUND
MANUAL CHECK
AUTOMATION ERROR
Saves the actual Shutterstock asset URL for matches
Shows article images in Streamlit
Exports results to Excel
Caches previously checked exact images so duplicates are not searched again
Important: use Python 3.12
Your PC has Python 3.12 and Python 3.14t. Use Python 3.12 for this app because the free-threaded 3.14t build can crash Playwright/greenlet.
Install
Extract this folder anywhere, for example:
C:\Users\User\Desktop\ShutterstockChecker
Double-click:
install.bat
When installation finishes, double-click:
run_app.bat
The app opens in your browser.
Manual commands
Install:
    cd /d C:\Users\User\Desktop\ShutterstockChecker
    py -3.12 -m pip install -r requirements.txt
    py -3.12 -m playwright install chromium

Run:
    py -3.12 -m streamlit run app.py

Notes
Keep "Show Chrome while checking" enabled initially.
The app does not bypass CAPTCHAs or security checks. If Shutterstock displays one, that image is marked MANUAL CHECK.
Shutterstock can change its website interface. If its Search by Image control changes, the Playwright selectors may need updating.
The `work` folder stores the persistent Chrome profile and a small result cache.
