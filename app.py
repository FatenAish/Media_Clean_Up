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
from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

st.set_page_config(
    page_title="Shutterstock Article Image Checker",
    page_icon="🔎",
    layout="wide",
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

MAX_RESULTS = 40
MATCH_THRESHOLD = 0.86
POSSIBLE_THRESHOLD = 0.76


def clean_url(url):
    url = str(url).strip()
    if not url:
        return ""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def pil_from_bytes(data):
    return Image.open(io.BytesIO(data)).convert("RGB")


def normalize_image(data):
    img = ImageOps.exif_transpose(pil_from_bytes(data))
    img.thumbnail((3900, 3900), Image.Resampling.LANCZOS)

    for quality in (92, 88, 84, 80, 76, 72, 68):
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        result = out.getvalue()
        if len(result) < 4_800_000:
            return result

    img.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=65, optimize=True)
    return out.getvalue()


def crop_variant(img, ratio=0.84):
    w, h = img.size
    nw, nh = int(w * ratio), int(h * ratio)
    left = max(0, (w - nw) // 2)
    top = max(0, (h - nh) // 2)
    return img.crop((left, top, left + nw, top + nh))


def similarity(a_bytes, b_bytes):
    """Robust near-duplicate score for resized/cropped Shutterstock thumbnails."""
    try:
        a = ImageOps.exif_transpose(pil_from_bytes(a_bytes))
        b = ImageOps.exif_transpose(pil_from_bytes(b_bytes))

        a_center = crop_variant(a)
        b_center = crop_variant(b)

        hash_pairs = [
            (imagehash.phash(a, hash_size=16), imagehash.phash(b, hash_size=16)),
            (imagehash.dhash(a, hash_size=16), imagehash.dhash(b, hash_size=16)),
            (imagehash.whash(a, hash_size=16), imagehash.whash(b, hash_size=16)),
            (
                imagehash.phash(a_center, hash_size=16),
                imagehash.phash(b_center, hash_size=16),
            ),
            (
                imagehash.dhash(a_center, hash_size=16),
                imagehash.dhash(b_center, hash_size=16),
            ),
        ]

        scores = [
            max(0.0, 1.0 - ((x - y) / 256.0))
            for x, y in hash_pairs
        ]
        scores.sort(reverse=True)

        return min(
            1.0,
            0.55 * scores[0]
            + 0.25 * scores[1]
            + 0.20 * (sum(scores) / len(scores)),
        )
    except Exception:
        return 0.0


def extract_article_images(page, article_url):
    page.goto(
        article_url,
        wait_until="domcontentloaded",
        timeout=90000,
    )
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
            candidates.append({
                "src": urljoin(article_url, src),
                "width": 1200,
                "height": 600,
                "position": "Feature",
            })

    selectors = [
        "article img",
        "main article img",
        ".entry-content img",
        ".post-content img",
        ".article-content img",
    ]
    selector = next(
        (s for s in selectors if page.locator(s).count()),
        "main img",
    )

    raw = page.locator(selector).evaluate_all(
        """
        imgs => imgs.map((img, idx) => ({
            src: img.currentSrc ||
                 img.src ||
                 img.getAttribute('data-src') ||
                 img.getAttribute('data-lazy-src') ||
                 img.getAttribute('data-original') || '',
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

    excluded = (
        "logo", "icon", "avatar", "emoji", "favicon",
        "sprite", "placeholder", "author", "profile",
        "social", "facebook", "instagram", "linkedin",
        "youtube", "twitter", "whatsapp",
    )

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
    r = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.bayut.com/",
        },
        timeout=45,
    )
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

    return any(
        term in text
        for term in (
            "captcha",
            "verify you are human",
            "security check",
            "access denied",
        )
    )


def dismiss_common_overlays(page):
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Accept All")',
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button:has-text("Agree")',
        '[id*="onetrust-accept" i]',
    ]

    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=1200)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def direct_file_input(page):
    loc = page.locator('input[type="file"]')
    if loc.count():
        return loc.first
    return None


def set_file_via_click(page, locator, temp_path):
    try:
        with page.expect_file_chooser(timeout=3000) as chooser_info:
            locator.click(timeout=3000)
        chooser_info.value.set_files(temp_path)
        return True, "file chooser"
    except Exception:
        pass

    try:
        locator.click(timeout=2500)
    except Exception:
        return False, ""

    page.wait_for_timeout(700)

    upload = direct_file_input(page)
    if upload is not None:
        upload.set_input_files(temp_path)
        return True, "revealed file input"

    return False, ""


def upload_image_to_shutterstock(page, temp_path):
    upload = direct_file_input(page)
    if upload is not None:
        upload.set_input_files(temp_path)
        return True, "direct file input"

    controls = page.locator(
        "button, [role='button'], label, [aria-label], [title]"
    )
    keywords = (
        "search by image",
        "image search",
        "camera",
        "upload image",
        "upload",
        "visual search",
    )

    for i in range(min(controls.count(), 180)):
        el = controls.nth(i)

        try:
            attrs = [
                el.inner_text(timeout=250),
                el.get_attribute("aria-label"),
                el.get_attribute("title"),
                el.get_attribute("data-testid"),
            ]
            hay = " ".join(str(v) for v in attrs if v).lower()
        except Exception:
            continue

        if not any(k in hay for k in keywords):
            continue

        ok, method = set_file_via_click(page, el, temp_path)
        if ok:
            return True, f"semantic control / {method}"

    search = page.locator(
        'input[placeholder*="Search for images" i], '
        'input[placeholder*="Search" i]'
    ).first

    if search.count():
        try:
            search_box = search.bounding_box()
        except Exception:
            search_box = None

        try:
            wrapper_buttons = search.locator(
                "xpath=ancestor::*[self::form or @role='search' "
                "or contains(translate(@class,'SEARCH','search'),'search')][1]"
                "//button"
            )

            for i in reversed(range(min(wrapper_buttons.count(), 12))):
                button = wrapper_buttons.nth(i)
                ok, method = set_file_via_click(page, button, temp_path)
                if ok:
                    return True, f"search-wrapper button / {method}"
        except Exception:
            pass

        if search_box:
            nearby = page.locator(
                "button, [role='button'], label, svg"
            )
            candidates = []

            for i in range(min(nearby.count(), 220)):
                el = nearby.nth(i)

                try:
                    box = el.bounding_box()
                except Exception:
                    continue

                if not box:
                    continue

                vertical_overlap = not (
                    box["y"] + box["height"] < search_box["y"] - 20
                    or box["y"] > search_box["y"] + search_box["height"] + 20
                )

                near_right = (
                    search_box["x"] + search_box["width"] - 150
                    <= box["x"]
                    <= search_box["x"] + search_box["width"] + 80
                )

                if vertical_overlap and near_right:
                    candidates.append((box["x"], el))

            candidates.sort(key=lambda x: x[0], reverse=True)

            for _, el in candidates[:15]:
                ok, method = set_file_via_click(page, el, temp_path)
                if ok:
                    return True, f"near-search control / {method}"

            y = search_box["y"] + search_box["height"] / 2

            for offset in (26, 42, 58, 78, 98):
                x = search_box["x"] + search_box["width"] - offset

                try:
                    with page.expect_file_chooser(timeout=2500) as chooser_info:
                        page.mouse.click(x, y)
                    chooser_info.value.set_files(temp_path)
                    return True, f"camera coordinate offset {offset}px"
                except Exception:
                    pass

                page.wait_for_timeout(350)

                upload = direct_file_input(page)
                if upload is not None:
                    upload.set_input_files(temp_path)
                    return True, f"coordinate revealed input {offset}px"

    return False, ""


def wait_for_shutterstock_results(page):
    try:
        page.wait_for_function(
            """
            () => {
                const body = (document.body.innerText || '').toLowerCase();
                const hasHeading =
                    body.includes('search by image') ||
                    body.includes('results (') ||
                    body.includes('results');
                const links = [...document.querySelectorAll('a[href]')];
                const hasAsset = links.some(a =>
                    a.href.includes('/image-photo/') ||
                    a.href.includes('/image-vector/') ||
                    a.href.includes('/image-illustration/') ||
                    a.href.includes('/image-3d/')
                );
                return hasHeading && hasAsset;
            }
            """,
            timeout=35000,
        )
    except PlaywrightTimeoutError:
        pass


def collect_candidates(page):
    page.wait_for_timeout(3500)

    for _ in range(4):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(450)

    selectors = [
        'a[href*="/image-photo/"] img',
        'a[href*="/image-vector/"] img',
        'a[href*="/image-illustration/"] img',
        'a[href*="/image-3d/"] img',
    ]

    results = []
    seen = set()

    for selector in selectors:
        locs = page.locator(selector)

        for i in range(min(locs.count(), MAX_RESULTS)):
            img = locs.nth(i)

            try:
                href = clean_url(
                    img.evaluate(
                        "el => { const a = el.closest('a'); return a ? a.href : ''; }"
                    )
                )

                if not href or href in seen:
                    continue

                img.scroll_into_view_if_needed(timeout=3000)
                shot = img.screenshot(timeout=5000)

                if len(shot) < 1000:
                    continue

                seen.add(href)
                results.append({"url": href, "bytes": shot})

                if len(results) >= MAX_RESULTS:
                    return results

            except Exception:
                continue

    return results


def safe_screenshot(page):
    try:
        return page.screenshot(full_page=False)
    except Exception:
        return None


def check_shutterstock(page, upload_bytes):
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(upload_bytes)
            temp_path = tmp.name

        page.goto(
            "https://www.shutterstock.com/",
            wait_until="domcontentloaded",
            timeout=90000,
        )
        page.wait_for_timeout(3000)
        dismiss_common_overlays(page)

        if challenge_detected(page):
            return (
                "MANUAL CHECK",
                "",
                0.0,
                "Shutterstock displayed a CAPTCHA/security challenge.",
                safe_screenshot(page),
            )

        uploaded, method = upload_image_to_shutterstock(page, temp_path)

        if not uploaded:
            return (
                "AUTOMATION ERROR",
                "",
                0.0,
                "The Shutterstock camera/upload control could not be triggered.",
                safe_screenshot(page),
            )

        wait_for_shutterstock_results(page)

        if challenge_detected(page):
            return (
                "MANUAL CHECK",
                "",
                0.0,
                "Shutterstock displayed a CAPTCHA/security challenge after upload.",
                safe_screenshot(page),
            )

        candidates = collect_candidates(page)

        if not candidates:
            return (
                "NOT FOUND",
                "",
                0.0,
                f"Upload succeeded via {method}, but no Shutterstock result cards were detected.",
                safe_screenshot(page),
            )

        best_url = ""
        best_score = 0.0

        for candidate in candidates:
            score = similarity(upload_bytes, candidate["bytes"])

            if score > best_score:
                best_url = candidate["url"]
                best_score = score

            if score >= 0.97:
                break

        notes = (
            f"Uploaded via {method}. "
            f"Compared {len(candidates)} Shutterstock results. "
            f"Best similarity: {best_score:.3f}."
        )

        if best_score >= MATCH_THRESHOLD:
            return "MATCH FOUND", best_url, best_score, notes, None

        if best_score >= POSSIBLE_THRESHOLD:
            return "POSSIBLE MATCH", best_url, best_score, notes, None

        return "NOT FOUND", "", best_score, notes, None

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

    headers = [
        "Article URL",
        "Article Title",
        "Image Position",
        "Article Image URL",
        "Status",
        "Shutterstock Image URL",
        "Confidence",
        "Notes",
    ]
    ws.append(headers)

    for c in ws[1]:
        c.font = Font(bold=True)

    for r in results:
        ws.append([
            r.get("article_url", ""),
            r.get("article_title", ""),
            r.get("position", ""),
            r.get("image_url", ""),
            r.get("status", ""),
            r.get("shutterstock_url", ""),
            r.get("confidence", 0),
            r.get("notes", ""),
        ])

        row = ws.max_row

        for col in (1, 4, 6):
            value = ws.cell(row=row, column=col).value
            if value:
                ws.cell(row=row, column=col).hyperlink = value
                ws.cell(row=row, column=col).style = "Hyperlink"

    ws.freeze_panes = "A2"

    widths = {
        "A": 55,
        "B": 40,
        "C": 18,
        "D": 60,
        "E": 20,
        "F": 60,
        "G": 14,
        "H": 65,
    }

    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(out)
    out.seek(0)
    return out.getvalue()


def urls_from_excel(uploaded):
    df = pd.read_excel(uploaded)

    names = {
        str(c).strip().lower(): c
        for c in df.columns
    }

    col = names.get("address") or names.get("url")

    if col is None:
        raise ValueError('Excel must contain a column named "Address" or "URL".')

    return [
        str(v).strip()
        for v in df[col].dropna().tolist()
        if str(v).strip().startswith("http")
    ]


def launch_browser(p, show_browser):
    if os.name == "nt":
        return p.chromium.launch(
            channel="chrome",
            headless=not show_browser,
            args=["--start-maximized"] if show_browser else [],
        )

    chromium = (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
    )

    if not chromium:
        raise RuntimeError(
            "Chromium is missing on the server. packages.txt must contain: chromium"
        )

    return p.chromium.launch(
        executable_path=chromium,
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1500,900",
        ],
    )


st.title("🔎 Shutterstock Article Image Checker")
st.caption(
    "Extract article images, search each image on Shutterstock, "
    "verify returned candidates, and return the Shutterstock asset URL."
)

with st.sidebar:
    st.header("Settings")

    mode = st.radio(
        "Input method",
        ["Single article", "Paste URLs", "Upload Excel"],
    )

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
    single_url = st.text_input(
        "Article URL",
        placeholder="https://www.bayut.com/mybayut/...",
    )
elif mode == "Paste URLs":
    multi_urls = st.text_area("Paste one article URL per line", height=180)
else:
    uploaded_excel = st.file_uploader(
        'Upload Excel with an "Address" or "URL" column',
        type=["xlsx"],
    )

if st.button("Start Check", type="primary", use_container_width=True):
    try:
        if mode == "Single article":
            urls = [single_url.strip()] if single_url.strip() else []
        elif mode == "Paste URLs":
            urls = [
                line.strip()
                for line in multi_urls.splitlines()
                if line.strip().startswith("http")
            ]
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
            context = browser.new_context(
                viewport={"width": 1500, "height": 900},
                user_agent=USER_AGENT,
                locale="en-US",
            )
            article_page = context.new_page()
            shutter_page = context.new_page()

            try:
                for article_index, article_url in enumerate(urls, start=1):
                    status_box.info(
                        f"Article {article_index}/{len(urls)} — extracting images..."
                    )

                    try:
                        title, images = extract_article_images(article_page, article_url)
                    except Exception as e:
                        results.append({
                            "article_url": article_url,
                            "article_title": "",
                            "position": "",
                            "image_url": "",
                            "status": "ARTICLE ERROR",
                            "shutterstock_url": "",
                            "confidence": 0,
                            "notes": str(e),
                        })
                        continue

                    if not images:
                        results.append({
                            "article_url": article_url,
                            "article_title": title,
                            "position": "",
                            "image_url": "",
                            "status": "NO IMAGES FOUND",
                            "shutterstock_url": "",
                            "confidence": 0,
                            "notes": "",
                        })
                        continue

                    for image_index, image in enumerate(images, start=1):
                        status_box.info(
                            f"Article {article_index}/{len(urls)} — "
                            f"image {image_index}/{len(images)} — checking Shutterstock..."
                        )

                        try:
                            original = download_image(image["src"])
                            normalized = normalize_image(original)

                            (
                                status,
                                shutter_url,
                                score,
                                notes,
                                debug_screenshot,
                            ) = check_shutterstock(shutter_page, normalized)

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
                                "_debug": debug_screenshot,
                            })

                        except Exception as e:
                            results.append({
                                "article_url": article_url,
                                "article_title": title,
                                "position": image["position"],
                                "image_url": image["src"],
                                "status": "IMAGE ERROR",
                                "shutterstock_url": "",
                                "confidence": 0,
                                "notes": str(e),
                            })

                        display = [
                            {k: v for k, v in r.items() if not k.startswith("_")}
                            for r in results
                        ]

                        live.dataframe(
                            pd.DataFrame(display),
                            use_container_width=True,
                            hide_index=True,
                        )

                    progress.progress(
                        article_index / len(urls),
                        text=f"Completed {article_index}/{len(urls)} articles",
                    )

            finally:
                context.close()
                browser.close()

    except Exception as e:
        st.error(f"Browser automation could not start: {e}")
        st.stop()

    status_box.success("Check completed.")
    progress.progress(1.0, text="Completed")

    display = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in results
    ]
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

        expanded = row["status"] in (
            "MATCH FOUND",
            "POSSIBLE MATCH",
            "AUTOMATION ERROR",
            "MANUAL CHECK",
        )

        with st.expander(
            f"{i}. {row['position']} — {row['status']}",
            expanded=expanded,
        ):
            c1, c2 = st.columns(2)

            with c1:
                st.image(
                    row["_preview"],
                    caption="Article image",
                    use_container_width=True,
                )

            with c2:
                st.write(f"**{row['status']}**")
                st.write(f"Confidence: **{row['confidence']:.1f}%**")
                st.write(row.get("notes", ""))

                if row["shutterstock_url"]:
                    st.link_button("Open Shutterstock match", row["shutterstock_url"])
                else:
                    st.write("No Shutterstock URL saved.")

                if row.get("_debug"):
                    st.write("**Shutterstock page when the check failed:**")
                    st.image(row["_debug"], use_container_width=True)

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
        st.write(
            "**Summary:** "
            + " · ".join(f"{k}: {v}" for k, v in counts.items())
        )
