import asyncio
import os
import runpy
from pathlib import Path

# Streamlit on Windows may run with SelectorEventLoop, but Playwright starts its
# driver as an asyncio subprocess and therefore requires ProactorEventLoop.
# Reset the policy immediately before executing the local checker. This does not
# replace Streamlit's already-running server loop; it only affects new asyncio
# loops created afterward (including Playwright's loop).
if os.name == "nt":
    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_cls is not None:
        asyncio.set_event_loop_policy(policy_cls())

local_app = Path(__file__).resolve().with_name("app_local.py")
runpy.run_path(str(local_app), run_name="__main__")
