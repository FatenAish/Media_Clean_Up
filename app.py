import os
from pathlib import Path
import runpy
import streamlit as st

# Main entry point. No Shutterstock API is required.
# Windows must route through app_windows.py so Playwright gets a Proactor
# event-loop policy before it creates its driver subprocess.
if os.name == "nt":
    windows_app = Path(__file__).resolve().with_name("app_windows.py")
    runpy.run_path(str(windows_app), run_name="__main__")
else:
    st.set_page_config(
        page_title="Shutterstock Article Image Checker",
        page_icon="🔎",
        layout="wide",
    )
    st.title("🔎 Shutterstock Article Image Checker")
    st.info("No Shutterstock API is required for this project.")
    st.warning(
        "The actual Shutterstock image check cannot run from Streamlit Community Cloud because Shutterstock challenges the cloud/datacenter browser with its Verification Required screen."
    )
    st.markdown(
        """
### Use the working checker on your Windows PC

Run the included **START_SHUTTERSTOCK_CHECKER.bat** file, or use:

```bat
py -3.12 -m streamlit run app_windows.py
```

The Windows wrapper configures the event loop required by Playwright, then launches the local checker through your visible Chrome browser.
        """
    )
