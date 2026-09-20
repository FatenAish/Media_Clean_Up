import io
import os
import shutil
import tempfile
from urllib.parse import urljoin, urlsplit, urlunsplit

import imagehash
import pandas as pd
import requests
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font
from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

st.set_page_config(page_title="Shutterstock Article Image Checker", page_icon="🔎", layout="wide")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

MAX_RESULTS = 30
MATCH_THRESHOLD = 0.90
POSSIBLE_THRESHOLD = 0.80


def clean_url(url):
    url = str(url).strip()
    if not url:
        return ""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def pil_from_bytes(data):
    return Image.open(io.BytesIO(data)).convert("RGB")


def normalize_image(data):
    img = pil_from_bytes(data)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((3900, 3900), Image.Resampling.LANCZOS)

    for quality in (92, 88, 84, 80, 76, 72, 68):
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        result = out.getvalue()
        if len(result) < 4_800_000:
            return result

    out = io.BytesIO()
    img.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
    img.save(out, "JPEG", quality=65, optimize=True)
    return out.getvalue()


def center_crop(img, ratio=0.82):
    w, h = img.size
    nw, nh = int(w * ratio), int(h * ratio)
    left, top = (w - nw) // 2, (h - nh) // 2
    return img.crop((left, top, left + nw, top + nh))


def similarity(a_bytes, b_bytes):
    try:
        a = ImageOps.exif_transpose(pil_from_bytes(a_bytes))
        b = ImageOps.exif_transpose(pil_from_bytes(b_bytes))
        ac = center_crop(a)
        bc = center_crop(b)

        pairs = [
            (imagehash.phash(a, hash_size=16), imagehash.phash(b, hash_size=16)),
            (imagehash.dhash(a, hash_size=16), imagehash.dhash(b, hash_size=16)),
            (imagehash.whash(a, hash_size=16), imagehash.whash(b, hash_size=16)),
            (imagehash.phash(ac, hash_size=16), imagehash.phash(bc, hash_size=16)),
        ]

        scores = [max(0.0, 1.0 - ((x - y) / 256.0)) for x, y in pairs]
        scores.sort(reverse=True)
        return min(1.0, 0.7 * scores[0] + 0.3 * (sum(scores) / len(scores)))
    except Exception:
        return 0.0


def extract_article_images(page, article_url):
    page.goto(article_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)
    title = page.title()

    for _ in range(8):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(250)

    candidates = []

    og = page.locator('meta[property="og:image"]')
    if og.count():
        src = og.get_attribute("content")
        if src:
            candidates.append({"src": urljoin(article_url, src), "width": 1200, "height": 600, "position": "Feature"})

    selectors = ["article img", "main article img", ".entry-content img", ".post-content img", ".article-content img"]
    selector = next((s for s in selectors if page.locator(s).count()), "main img")

    raw = page.locator(selector).evaluate_all(
        """
        imgs => imgs.map((img, idx) => ({
            src: img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '',
            width: img.naturalWidth || img.width || 0,
            height: img.naturalHeight || img.height || 0,
            idx: idx + 1
        }))
        """
    )

    for item in raw:
        src = str(item.get("src") or "").strip()
        if src and not src.startswith("data:"):
            candidates.append({
                "src": urljoin(article_url, src),
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
                "position": f"Body {item.get('idx', '')}",
            })

    excluded = ("logo", "icon", "avatar", "emoji", "favicon", "sprite", "placeholder", "author", "profile", "social", "facebook", "instagram", "linkedin", "youtube", "twitter", "whatsapp")
    seen = set()
    final = []

    for item in candidates:
        src = clean_url(item["src"])
        if not src or src in seen:
            continue
        if any(term in src.lower() for term in excluded):
            continue
        if item["width"] and item["width"] < 450:
            continue
        if item["height"] and item["height"] < 220:
            continue
        seen.add(src)
        item["src"] = src
        final.append(item)

    return title, final


def download_image(url):
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Referer": "https://www.bayut.com/"}, timeout=45)
    r.raise_for_status()
    if len(r.content) < 3000:
        raise RuntimeError("Downloaded image is too small.")
    pil_from_bytes(r.content)
    return r.content


def challenge_detected(page):
    try:
        text = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    return any(term in text for term in ("captcha", "verify you are human", "security check", "access denied"))


def find_upload_input(page):
    direct = page.locator('input[type="file"]')
    if direct.count():
        return direct.first

    controls = page.locator("button, [role='button'], label")
    for i in range(min(controls.count(), 120)):
        el = controls.nth(i)
        try:
            text = " ".join(filter(None, [
                el.inner_text(timeout=400),
                el.get_attribute("aria-label"),
                el.get_attribute("title"),
                el.get_attribute("data-testid"),
            ])).lower()
        except Exception:
            continue

        if not any(k in text for k in ("search by image", "image search", "camera", "upload image", "upload")):
            continue

        try:
            el.click(timeout=2500)
            page.wait_for_timeout(700)
            direct = page.locator('input[type="file"]')
            if direct.count():
                return direct.first
        except Exception:
            pass

    try:
        search = page.locator('input[placeholder*="Search for images" i], input[placeholder*="Search" i]').first
        if search.count():
            buttons = search.locator("xpath=ancestor::*[self::form or @role='search' or contains(@class,'search')][1]//button")
            for i in reversed(range(min(buttons.count(), 8))):
                try:
                    buttons.nth(i).click(timeout=2500)
                    page.wait_for_timeout(600)
                    direct = page.locator('input[type="file"]')
                    if direct.count():
                        return direct.first
                except Exception:
                    pass
    except Exception:
        pass

    return None


def collect_candidates(page):
    page.wait_for_timeout(4500)
    for _ in range(3):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(500)

    selectors = [
        'a[href*="/image-photo/"] img',
        'a[href*="/image-vector/"] img',
        'a[href*="/image-illustration/"] img',
        'a[href*="/image-3d/"] img',
    ]

    results, seen = [], set()

    for selector in selectors:
        locs = page.locator(selector)
        for i in range(min(locs.count(), MAX_RESULTS)):
            img = locs.nth(i)
            try:
                href = clean_url(img.evaluate("el => { const a = el.closest('a'); return a ? a.href : ''; }"))
                if not href or href in seen:
                    continue
                img.scroll_into_view_if_needed(timeout=3000)
                shot = img.screenshot(timeout=5000)
                seen.add(href)
                results.append({"url": href, "bytes": shot})
                if len(results) >= MAX_RESULTS:
                    return results
            except Exception:
                continue

    return results


def check_shutterstock(page, upload_bytes):
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(upload_bytes)
            temp_path = tmp.name

        page.goto("https://www.shutterstock.com/", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)

        if challenge_detected(page):
            return "MANUAL CHECK", "", 0.0, "Shutterstock displayed a CAPTCHA/security challenge."

        upload = find_upload_input(page)
        if upload is None:
            return "AUTOMATION ERROR", "", 0.0, "Could not locate Shutterstock Search by Image upload control."

        upload.set_input_files(temp_path)

        try:
            page.wait_for_function(
                """
                () => [...document.querySelectorAll('a[href]')].some(a =>
                    a.href.includes('/image-photo/') ||
                    a.href.includes('/image-vector/') ||
                    a.href.includes('/image-illustration/') ||
                    a.href.includes('/image-3d/')
                )
                """,
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            pass

        if challenge_detected(page):
            return "MANUAL CHECK", "", 0.0, "Shutterstock displayed a CAPTCHA/security challenge after upload."

        candidates = collect_candidates(page)
        if not candidates:
            return "NOT FOUND", "", 0.0, "No Shutterstock reverse-image results were detected."

        best_url, best_score = "", 0.0
        for candidate in candidates:
            score = similarity(upload_bytes, candidate["bytes"])
            if score > best_score:
                best_url, best_score = candidate["url"], score
            if score >= 0.96:
                break

        if best_score >= MATCH_THRESHOLD:
            return "MATCH FOUND", best_url, best_score, f"Compared against {len(candidates)} Shutterstock results."
        if best_score >= POSSIBLE_THRESHOLD:
            return "POSSIBLE MATCH", best_url, best_score, f"Compared against {len(candidates)} Shutterstock results."
        return "NOT FOUND", "", best_score, f"Compared against {len(candidates)} Shutterstock results."

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def make_excel(results):
    out = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    headers = ["Article URL", "Article Title", "Image Position", "Article Image URL", "Status", "Shutterstock Image URL", "Confidence", "Notes"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)

    for r in results:
        ws.append([r.get("article_url", ""), r.get("article_title", ""), r.get("position", ""), r.get("image_url", ""), r.get("status", ""), r.get("shutterstock_url", ""), r.get("confidence", 0), r.get("notes", "")])
        row = ws.max_row
        for col in (1, 4, 6):
            value = ws.cell(row=row, column=col).value
            if value:
                ws.cell(row=row, column=col).hyperlink = value
                ws.cell(row=row, column=col).style = "Hyperlink"

    ws.freeze_panes = "A2"
    for col, width in {"A":55,"B":40,"C":18,"D":60,"E":20,"F":60,"G":14,"H":50}.items():
        ws.column_dimensions[col].width = width
    wb.save(out)
    out.seek(0)
    return out.getvalue()


def urls_from_excel(uploaded):
    df = pd.read_excel(uploaded)
    names = {str(c).strip().lower(): c for c in df.columns}
    col = names.get("address") or names.get("url")
    if col is None:
        raise ValueError('Excel must contain a column named "Address" or "URL".')
    return [str(v).strip() for v in df[col].dropna().tolist() if str(v).strip().startswith("http")]


def launch_browser(p, show_browser):
    if os.name == "nt":
        return p.chromium.launch(channel="chrome", headless=not show_browser, args=["--start-maximized"] if show_browser else [])

    chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not chromium:
        raise RuntimeError("Chromium is missing on the server. packages.txt must contain: chromium")

    return p.chromium.launch(
        executable_path=chromium,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
    )


st.title("🔎 Shutterstock Article Image Checker")
st.caption("Extract article images, search them on Shutterstock, compare the results, and return the Shutterstock asset URL when a likely match is found.")

with st.sidebar:
    st.header("Settings")
    mode = st.radio("Input method", ["Single article", "Paste URLs", "Upload Excel"])
    if os.name == "nt":
        show_browser = st.checkbox("Show Chrome while checking", value=True)
        st.info("Windows mode: Chrome can be shown while checking.")
    else:
        show_browser = False
        st.info("Cloud mode: Chromium runs headlessly on the server.")

single_url = ""
multi_urls = ""
uploaded_excel = None

if mode == "Single article":
    single_url = st.text_input("Article URL", placeholder="https://www.bayut.com/mybayut/...")
elif mode == "Paste URLs":
    multi_urls = st.text_area("Paste one article URL per line", height=180)
else:
    uploaded_excel = st.file_uploader('Upload Excel with an "Address" or "URL" column', type=["xlsx"])

if st.button("Start Check", type="primary", use_container_width=True):
    try:
        if mode == "Single article":
            urls = [single_url.strip()] if single_url.strip() else []
        elif mode == "Paste URLs":
            urls = [line.strip() for line in multi_urls.splitlines() if line.strip().startswith("http")]
        else:
            urls = urls_from_excel(uploaded_excel) if uploaded_excel else []
    except Exception as e:
        st.error(str(e))
        st.stop()

    if not urls:
        st.warning("Add at least one article URL.")
        st.stop()

    results = []
    progress = st.progress(0, text="Starting...")
    status_box = st.empty()
    live = st.empty()

    try:
        with sync_playwright() as p:
            browser = launch_browser(p, show_browser)
            context = browser.new_context(viewport={"width": 1500, "height": 900}, user_agent=USER_AGENT)
            article_page = context.new_page()
            shutter_page = context.new_page()

            try:
                for article_index, article_url in enumerate(urls, start=1):
                    status_box.info(f"Article {article_index}/{len(urls)} — extracting images...")
                    try:
                        title, images = extract_article_images(article_page, article_url)
                    except Exception as e:
                        results.append({"article_url": article_url, "article_title": "", "position": "", "image_url": "", "status": "ARTICLE ERROR", "shutterstock_url": "", "confidence": 0, "notes": str(e)})
                        continue

                    if not images:
                        results.append({"article_url": article_url, "article_title": title, "position": "", "image_url": "", "status": "NO IMAGES FOUND", "shutterstock_url": "", "confidence": 0, "notes": ""})
                        continue

                    for image_index, image in enumerate(images, start=1):
                        status_box.info(f"Article {article_index}/{len(urls)} — image {image_index}/{len(images)} — checking Shutterstock...")
                        try:
                            original = download_image(image["src"])
                            normalized = normalize_image(original)
                            status, shutter_url, score, notes = check_shutterstock(shutter_page, normalized)
                            results.append({
                                "article_url": article_url,
                                "article_title": title,
                                "position": image["position"],
                                "image_url": image["src"],
                                "status": status,
                                "shutterstock_url": shutter_url,
                                "confidence": round(score * 100, 1),
                                "notes": notes,
                                "_preview": normalized,
                            })
                        except Exception as e:
                            results.append({"article_url": article_url, "article_title": title, "position": image["position"], "image_url": image["src"], "status": "IMAGE ERROR", "shutterstock_url": "", "confidence": 0, "notes": str(e)})

                        display = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
                        live.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)

                    progress.progress(article_index / len(urls), text=f"Completed {article_index}/{len(urls)} articles")
            finally:
                context.close()
                browser.close()
    except Exception as e:
        st.error(f"Browser automation could not start: {e}")
        st.stop()

    status_box.success("Check completed.")
    progress.progress(1.0, text="Completed")

    display = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    df = pd.DataFrame(display)

    st.subheader("Results")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "article_url": st.column_config.LinkColumn("Article URL"),
            "image_url": st.column_config.LinkColumn("Article Image URL"),
            "shutterstock_url": st.column_config.LinkColumn("Shutterstock Image URL"),
            "confidence": st.column_config.NumberColumn("Confidence", format="%.1f%%"),
        },
    )

    st.subheader("Image Review")
    for i, row in enumerate(results, start=1):
        if "_preview" not in row:
            continue
        with st.expander(f"{i}. {row['position']} — {row['status']}", expanded=row["status"] in ("MATCH FOUND", "POSSIBLE MATCH")):
            c1, c2 = st.columns(2)
            with c1:
                st.image(row["_preview"], caption="Article image", use_container_width=True)
            with c2:
                st.write(f"**{row['status']}**")
                st.write(f"Confidence: **{row['confidence']:.1f}%**")
                if row["shutterstock_url"]:
                    st.link_button("Open Shutterstock match", row["shutterstock_url"])
                else:
                    st.write("No Shutterstock URL saved.")

    excel = make_excel(results)
    st.download_button(
        "Download Excel Report",
        data=excel,
        file_name="shutterstock_check_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    if not df.empty:
        counts = df["status"].value_counts().to_dict()
        st.write("**Summary:** " + " · ".join(f"{k}: {v}" for k, v in counts.items()))
