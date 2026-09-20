import os

# Shutterstock is currently challenging Streamlit Community Cloud / datacenter
# browsers with its "Verification Required" page. That means the reverse-image
# search cannot be made reliable from the hosted Streamlit server.
#
# The working mode for this project is local Windows: Streamlit still provides
# the UI, but Playwright controls the user's normal visible Chrome browser and
# keeps a persistent Shutterstock browser profile.

if os.name == "nt":
    # app_local.py contains the full working Streamlit application.
    # Importing it here lets users run the normal entry point:
    #   py -3.12 -m streamlit run app.py
    from app_local import *  # noqa: F401,F403
else:
    import streamlit as st

    st.set_page_config(
        page_title="Shutterstock Article Image Checker",
        page_icon="🔎",
        layout="wide",
    )

    st.title("🔎 Shutterstock Article Image Checker")
    st.error("Shutterstock is blocking the Streamlit Cloud browser with its Verification Required challenge.")
    st.write(
        "The checker must run locally on Windows so Shutterstock is opened through your own visible Chrome browser and connection."
    )
    st.markdown(
        """
### Run the working version

1. Download or clone this GitHub repository to your Windows PC.
2. Double-click **`install_local.bat`** once.
3. Double-click **`run_local.bat`** whenever you want to use the checker.

Or run it manually with Python 3.12:

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 -m playwright install chromium
py -3.12 -m streamlit run app.py
```

The local app will:

- extract the feature and body images from each article
- open Shutterstock Search by Image automatically
- upload each article image
- compare the returned Shutterstock images
- save the matching Shutterstock asset URL
- export the results to Excel

If Shutterstock asks for its slider verification in the visible Chrome window, complete it there. The app waits and continues automatically afterward.
        """
    )
