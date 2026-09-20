import os
from pathlib import Path
import runpy
import streamlit as st

# Main entry point.
# No Shutterstock API is required.
#
# On Windows, execute app_local.py with runpy on EVERY Streamlit rerun.
# Using `from app_local import *` caused a blank page after Streamlit reran
# because Python cached the imported module and its Streamlit UI code did not
# execute again.

if os.name == "nt":
    local_app = Path(__file__).resolve().with_name("app_local.py")
    runpy.run_path(str(local_app), run_name="__main__")
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

The Streamlit interface is still used, but the browser automation runs through **your own Chrome browser and internet connection**.

1. Download or clone this GitHub repository.
2. Run **`install_local.bat`** once.
3. Run **`run_local.bat`** whenever you want to check articles.

Or run manually:

```bat
py -3.12 -m streamlit run app_local.py
```

The local checker supports:

- one article URL
- multiple pasted URLs
- Excel upload with an `Address` or `URL` column
- automatic feature and body image extraction
- automatic Shutterstock Search by Image
- image matching and confidence checking
- actual Shutterstock asset URL when a match is found
- Excel report export

If Shutterstock shows its verification slider in the visible Chrome window, complete it there once. The app waits and continues automatically. It does not bypass Shutterstock security checks.
        """
    )
