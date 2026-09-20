import asyncio
import os
import runpy
from pathlib import Path

# On Windows, Playwright needs a Proactor event loop because it launches its
# driver as a subprocess. Set the policy before executing the Streamlit checker.
if os.name == "nt":
    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_cls is not None:
        asyncio.set_event_loop_policy(policy_cls())

local_app = Path(__file__).resolve().with_name("app_local2.py")
runpy.run_path(str(local_app), run_name="__main__")
