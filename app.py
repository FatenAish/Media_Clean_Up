import io
import os
import re
import json
import time
import hashlib
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import cv2
import imagehash
import numpy as np
import pandas as pd
import requests
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font
from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# APP SETTINGS
# ============================================================

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "work"
IMAGE_DIR = WORK_DIR / "images"
PROFILE_DIR = WORK_DIR / "chrome_profile"
CACHE_FILE = WORK_DIR / "match_cache.json"

for folder in (WORK_DIR, IMAGE_DIR, PROFILE_DIR):
    folder.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)

MAX_UPLOAD_BYTES = 4_800_000
MAX_UPLOAD_SIDE = 3900
MAX_RESULTS_TO_COMPARE = 30
REQUEST_TIMEOUT = 45

# Conservative thresholds. Same-image verification uses both
# perceptual hash and SIFT feature geometry.
PHASH_MATCH = 0.88
PHASH_POSSIBLE = 0.78
SIFT_INLIER_MATCH = 0.38
SIFT_INLIER_POSSIBLE = 0.20
MIN_GOOD_SIFT = 12

st.set_page_config(
    page_title="Shutterstock Article Image Checker",
    page_icon="🔎",
    layout="wide",
)


# ============================================================
# HELPERS
# ============================================================

def clean_url(url: str) -> str:
    url = str(url).strip()
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache):
    CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pil_from_bytes(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    return img.convert("RGB")


def normalize_for_shutterstock(data: bytes) -> bytes:
    """
    Shutterstock reverse-search documented limits are 5 MB and 4000 px/side.
    We stay slightly below both limits and always output JPEG.
    """
    img = pil_from_bytes(data)

    width, height = img.size
    longest = max(width, height)

    if longest > MAX_UPLOAD_SIDE:
        scale = MAX_UPLOAD_SIDE / longest
        img = img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    # Step quality down only when needed.
    for quality in (92, 88, 84, 80, 76, 72, 68):
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True)
        result = out.getvalue()
        if len(result) <= MAX_UPLOAD_BYTES:
            return result

    # Last-resort resize if the content still compresses poorly.
    img.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=68, optimize=True)
    return out.getvalue()


def image_to_cv(data: bytes):
    arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def phash_similarity(a: bytes, b: bytes) -> float:
    try:
        ha = imagehash.phash(pil_from_bytes(a), hash_size=16)
        hb = imagehash.phash(pil_from_bytes(b), hash_size=16)
        distance = ha - hb
        return max(0.0, 1.0 - (distance / 256.0))
    except Exception:
        return 0.0


def sift_geometry(a: bytes, b: bytes):
    """
    Returns:
      good_matches, inlier_ratio

    SIFT + RANSAC is useful when the same stock image has been resized,
    watermarked or modestly cropped.
    """
    try:
        img1 = image_to_cv(a)
        img2 = image_to_cv(b)
        if img1 is None or img2 is None:
            return 0, 0.0

        g1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        # Keep feature extraction reasonably fast.
        for name, gray in (("a", g1), ("b", g2)):
            pass

        max_side = 1200
        def shrink(gray):
            h, w = gray.shape[:2]
            longest = max(h, w)
            if longest <= max_side:
                return gray
            s = max_side / longest
            return cv2.resize(gray, (int(w*s), int(h*s)), interpolation=cv2.INTER_AREA)

        g1 = shrink(g1)
        g2 = shrink(g2)

        sift = cv2.SIFT_create(nfeatures=2500)
        kp1, des1 = sift.detectAndCompute(g1, None)
        kp2, des2 = sift.detectAndCompute(g2, None)

        if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
            return 0, 0.0

        matcher = cv2.BFMatcher(cv2.NORM_L2)
        pairs = matcher.knnMatch(des1, des2, k=2)

        good = []
        for pair in pairs:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < 0.74 * n.distance:
                good.append(m)

        if len(good) < 4:
            return len(good), 0.0

        pts1 = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        pts2 = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

        _, mask = cv2.findHomography(pts1, pts2, cv2.RANSAC, 5.0)
        if mask is None:
            return len(good), 0.0

        inliers = int(mask.ravel().sum())
        return len(good), inliers / max(1, len(good))
    except Exception:
        return 0, 0.0


def classify_match(original: bytes, candidate: bytes):
    p_sim = phash_similarity(original, candidate)
    good, inlier = sift_geometry(original, candidate)

    # Strong agreement from either an extremely close pHash,
    # or enough geometrically consistent local features.
    if (
        p_sim >= PHASH_MATCH
        or (good >= MIN_GOOD_SIFT and inlier >= SIFT_INLIER_MATCH)
    ):
        return "MATCH FOUND", p_sim, good, inlier

    if (
        p_sim >= PHASH_POSSIBLE
        or (good >= 8 and inlier >= SIFT_INLIER_POSSIBLE)
    ):
        return "POSSIBLE MATCH", p_sim, good, inlier

    return "NOT FOUND", p_sim, good, inlier


# ============================================================
# ARTICLE EXTRACTION
# ============================================================

def extract_images_from_article(page, article_url: str):
    page.goto(article_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(2500)

    title = page.title()

    # Load lazy images.
    for _ in range(8):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(250)

    # Feature image from metadata can live outside the article DOM.
    og_image = page.locator('meta[property="og:image"]').get_attribute("content")
    candidates = []
    if og_image:
        candidates.append({
            "src": urljoin(article_url, og_image),
            "width": 1200,
            "height": 600,
            "position": "Feature",
        })

    # Prefer content containers to avoid nav/footer images.
    selectors = [
        "article img",
        "main article img",
        ".entry-content img",
        ".post-content img",
        ".article-content img",
    ]

    selector = None
    for s in selectors:
        if page.locator(s).count() > 0:
            selector = s
            break
    if selector is None:
        selector = "main img"

    raw = page.locator(selector).evaluate_all(
        """
        imgs => imgs.map((img, idx) => ({
            src: img.currentSrc ||
                 img.getAttribute('src') ||
                 img.getAttribute('data-src') ||
                 img.getAttribute('data-lazy-src') ||
                 img.getAttribute('data-original') || '',
            width: img.naturalWidth || img.width || 0,
            height: img.naturalHeight || img.height || 0,
            alt: img.getAttribute('alt') || '',
            idx: idx + 1
        }))
        """
    )

    for item in raw:
        src = str(item.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        candidates.append({
            "src": urljoin(article_url, src),
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
            "position": f"Body {item.get('idx', '')}",
        })

    excluded_terms = (
        "logo", "icon", "avatar", "emoji", "favicon", "sprite",
        "placeholder", "author", "profile", "social", "facebook",
        "instagram", "linkedin", "youtube", "twitter", "whatsapp",
    )

    seen = set()
    images = []

    for item in candidates:
        src = clean_url(item["src"])
        if not src:
            continue

        low = src.lower()
        if any(term in low for term in excluded_terms):
            continue

        w = item["width"]
        h = item["height"]

        # Ignore obvious UI / tiny thumbnails.
        if w and w < 450:
            continue
        if h and h < 220:
            continue

        if src in seen:
            continue

        seen.add(src)
        item["src"] = src
        images.append(item)

    return title, images


def download_article_image(url: str):
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://www.bayut.com/"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()

    if len(r.content) < 3000:
        raise RuntimeError("Downloaded file is too small to be a usable article image.")

    # Validate.
    _ = pil_from_bytes(r.content)
    return r.content


# ============================================================
# SHUTTERSTOCK AUTOMATION
# ============================================================

def find_shutterstock_upload_input(page):
    """
    Tries several DOM strategies. The upload input is often hidden and can
    still receive set_input_files() without being visible.
    """
    direct = page.locator('input[type="file"]')
    if direct.count() > 0:
        return direct.first

    # Inspect clickable controls semantically instead of relying on one selector.
    handle = page.locator("button, [role='button'], label").evaluate_all(
        """
        els => els.map((el, i) => ({
            i,
            text: (el.innerText || '').trim(),
            aria: el.getAttribute('aria-label') || '',
            title: el.getAttribute('title') || '',
            testid: el.getAttribute('data-testid') || '',
            cls: typeof el.className === 'string' ? el.className : ''
        }))
        """
    )

    keywords = ("search by image", "image search", "camera", "upload image", "upload")
    for info in handle:
        hay = " ".join(
            str(info.get(k, "")) for k in ("text", "aria", "title", "testid", "cls")
        ).lower()
        if any(k in hay for k in keywords):
            try:
                page.locator("button, [role='button'], label").nth(info["i"]).click(timeout=3500)
                page.wait_for_timeout(800)
                direct = page.locator('input[type="file"]')
                if direct.count() > 0:
                    return direct.first
            except Exception:
                pass

    # Search specifically around the main search box and click nearby buttons.
    try:
        search = page.locator(
            'input[placeholder*="Search for images" i], '
            'input[placeholder*="Search" i]'
        ).first
        if search.count() > 0:
            buttons = search.locator(
                "xpath=ancestor::*[self::form or @role='search' or contains(@class,'search')][1]//button"
            )
            # Camera control is typically one of the last buttons in the search container.
            for i in reversed(range(min(buttons.count(), 8))):
                try:
                    buttons.nth(i).click(timeout=2500)
                    page.wait_for_timeout(700)
                    direct = page.locator('input[type="file"]')
                    if direct.count() > 0:
                        return direct.first
                except Exception:
                    pass
    except Exception:
        pass

    # Last DOM attempt: click small buttons containing SVGs near the top search area.
    svg_buttons = page.locator("button:has(svg)")
    for i in range(min(svg_buttons.count(), 20)):
        try:
            box = svg_buttons.nth(i).bounding_box()
            if not box:
                continue
            # Search bar is normally near the top of the page.
            if box["y"] > 260:
                continue
            svg_buttons.nth(i).click(timeout=1800)
            page.wait_for_timeout(600)
            direct = page.locator('input[type="file"]')
            if direct.count() > 0:
                return direct.first
        except Exception:
            pass

    return None


def is_challenge_page(page):
    text = page.locator("body").inner_text(timeout=5000).lower()
    challenge_terms = ("captcha", "verify you are human", "security check", "access denied")
    return any(term in text for term in challenge_terms)


def collect_shutterstock_candidates(page):
    # Let results load and lazy-load a few rows.
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

    results = []
    seen = set()

    for selector in selectors:
        locs = page.locator(selector)
        for i in range(min(locs.count(), MAX_RESULTS_TO_COMPARE)):
            img = locs.nth(i)
            try:
                href = img.evaluate(
                    "el => { const a = el.closest('a'); return a ? a.href : ''; }"
                )
                if not href:
                    continue
                href = clean_url(href)
                if href in seen:
                    continue

                # Screenshot the result image element itself. This avoids CDN
                # anti-hotlink restrictions and gives us the image displayed
                # by Shutterstock.
                img.scroll_into_view_if_needed(timeout=3000)
                screenshot = img.screenshot(timeout=5000)

                seen.add(href)
                results.append({"url": href, "bytes": screenshot})

                if len(results) >= MAX_RESULTS_TO_COMPARE:
                    return results
            except Exception:
                continue

    return results


def check_on_shutterstock(page, upload_jpg: bytes):
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(upload_jpg)
            temp_path = tmp.name

        page.goto("https://www.shutterstock.com/", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)

        if is_challenge_page(page):
            return {
                "status": "MANUAL CHECK",
                "shutterstock_url": "",
                "score": 0.0,
                "phash_similarity": 0.0,
                "sift_good_matches": 0,
                "sift_inlier_ratio": 0.0,
                "notes": "Shutterstock displayed a CAPTCHA/security challenge.",
            }

        upload = find_shutterstock_upload_input(page)

        if upload is None:
            return {
                "status": "AUTOMATION ERROR",
                "shutterstock_url": "",
                "score": 0.0,
                "phash_similarity": 0.0,
                "sift_good_matches": 0,
                "sift_inlier_ratio": 0.0,
                "notes": "Could not locate the Shutterstock Search by Image upload control.",
            }

        upload.set_input_files(temp_path)

        # Wait for reverse-search results to appear.
        try:
            page.wait_for_function(
                """
                () => {
                    const links = [...document.querySelectorAll('a[href]')];
                    return links.some(a =>
                        a.href.includes('/image-photo/') ||
                        a.href.includes('/image-vector/') ||
                        a.href.includes('/image-illustration/') ||
                        a.href.includes('/image-3d/')
                    );
                }
                """,
                timeout=30000,
            )
        except PlaywrightTimeoutError:
            pass

        if is_challenge_page(page):
            return {
                "status": "MANUAL CHECK",
                "shutterstock_url": "",
                "score": 0.0,
                "phash_similarity": 0.0,
                "sift_good_matches": 0,
                "sift_inlier_ratio": 0.0,
                "notes": "Shutterstock displayed a CAPTCHA/security challenge after upload.",
            }

        candidates = collect_shutterstock_candidates(page)

        if not candidates:
            return {
                "status": "NOT FOUND",
                "shutterstock_url": "",
                "score": 0.0,
                "phash_similarity": 0.0,
                "sift_good_matches": 0,
                "sift_inlier_ratio": 0.0,
                "notes": "No Shutterstock reverse-search result images were detected.",
            }

        best = None
        for candidate in candidates:
            status, p_sim, good, inlier = classify_match(upload_jpg, candidate["bytes"])

            # Combined score is only for picking the best candidate.
            # The final label is still based on the conservative rules above.
            combined = max(
                p_sim,
                min(1.0, inlier + min(good, 40) / 200.0),
            )

            row = {
                "status": status,
                "shutterstock_url": candidate["url"],
                "score": combined,
                "phash_similarity": p_sim,
                "sift_good_matches": good,
                "sift_inlier_ratio": inlier,
                "notes": f"Compared against {len(candidates)} Shutterstock results.",
            }

            if best is None or row["score"] > best["score"]:
                best = row

            if status == "MATCH FOUND" and p_sim >= 0.94:
                break

        if best is None:
            return {
                "status": "NOT FOUND",
                "shutterstock_url": "",
                "score": 0.0,
                "phash_similarity": 0.0,
                "sift_good_matches": 0,
                "sift_inlier_ratio": 0.0,
                "notes": "Candidate results could not be compared.",
            }

        # Don't preserve a result URL when the system says no match.
        if best["status"] == "NOT FOUND":
            best["shutterstock_url"] = ""

        return best

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


# ============================================================
# EXCEL EXPORT
# ============================================================

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
        "pHash Similarity",
        "SIFT Good Matches",
        "SIFT Inlier Ratio",
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
            r.get("phash_similarity", 0),
            r.get("sift_good_matches", 0),
            r.get("sift_inlier_ratio", 0),
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
        "A": 55, "B": 40, "C": 18, "D": 60, "E": 20,
        "F": 60, "G": 14, "H": 18, "I": 18, "J": 18, "K": 50,
    }
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(out)
    out.seek(0)
    return out.getvalue()


# ============================================================
# URL INPUT
# ============================================================

def urls_from_excel(uploaded_file):
    df = pd.read_excel(uploaded_file)
    lookup = {str(c).strip().lower(): c for c in df.columns}

    if "address" in lookup:
        col = lookup["address"]
    elif "url" in lookup:
        col = lookup["url"]
    else:
        raise ValueError('Excel must contain a column named "Address" or "URL".')

    return [
        str(v).strip()
        for v in df[col].dropna().tolist()
        if str(v).strip().startswith("http")
    ]


def get_urls(mode, single, multi, upload):
    if mode == "Single article":
        return [single.strip()] if single.strip() else []

    if mode == "Paste URLs":
        return [
            line.strip()
            for line in multi.splitlines()
            if line.strip().startswith("http")
        ]

    if mode == "Upload Excel":
        if upload is None:
            return []
        return urls_from_excel(upload)

    return []


# ============================================================
# STREAMLIT UI
# ============================================================

st.title("🔎 Shutterstock Article Image Checker")
st.caption(
    "Paste an article URL, extract its feature/body images, run Shutterstock "
    "reverse image search, compare the results, and save the matched Shutterstock URL."
)

with st.sidebar:
    st.header("Settings")
    mode = st.radio(
        "Input method",
        ["Single article", "Paste URLs", "Upload Excel"],
    )
    use_cache = st.checkbox("Reuse previous image results", value=True)
    show_browser = st.checkbox(
        "Show Chrome while checking",
        value=True,
        help="Recommended. It is more reliable than headless mode for Shutterstock.",
    )
    st.info(
        "Run this app with Python 3.12 on your PC. "
        "The browser automation runs locally."
    )

single_url = ""
multi_urls = ""
uploaded_excel = None

if mode == "Single article":
    single_url = st.text_input(
        "Article URL",
        placeholder="https://www.bayut.com/mybayut/...",
    )
elif mode == "Paste URLs":
    multi_urls = st.text_area(
        "Paste one article URL per line",
        height=180,
    )
else:
    uploaded_excel = st.file_uploader(
        'Upload Excel with an "Address" or "URL" column',
        type=["xlsx"],
    )

start = st.button("Start Check", type="primary", use_container_width=True)

if start:
    try:
        urls = get_urls(mode, single_url, multi_urls, uploaded_excel)
    except Exception as e:
        st.error(str(e))
        st.stop()

    urls = [u for u in urls if u]
    if not urls:
        st.warning("Add at least one article URL.")
        st.stop()

    cache = load_cache() if use_cache else {}
    results = []

    overall = st.progress(0, text="Starting...")
    status_box = st.empty()
    live_table = st.empty()

    with sync_playwright() as p:
        # Use a persistent local browser profile so cookies/session can survive.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=not show_browser,
            viewport={"width": 1500, "height": 900},
            user_agent=USER_AGENT,
            args=["--start-maximized"] if show_browser else [],
        )

        pages = context.pages
        article_page = pages[0] if pages else context.new_page()
        shutter_page = context.new_page()

        try:
            for article_idx, article_url in enumerate(urls, start=1):
                status_box.info(
                    f"Article {article_idx}/{len(urls)} — extracting images..."
                )

                try:
                    title, images = extract_images_from_article(
                        article_page, article_url
                    )
                except Exception as e:
                    results.append({
                        "article_url": article_url,
                        "article_title": "",
                        "position": "",
                        "image_url": "",
                        "status": "ARTICLE ERROR",
                        "shutterstock_url": "",
                        "confidence": 0,
                        "phash_similarity": 0,
                        "sift_good_matches": 0,
                        "sift_inlier_ratio": 0,
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
                        "phash_similarity": 0,
                        "sift_good_matches": 0,
                        "sift_inlier_ratio": 0,
                        "notes": "",
                    })
                    continue

                for image_idx, image in enumerate(images, start=1):
                    status_box.info(
                        f"Article {article_idx}/{len(urls)} — "
                        f"image {image_idx}/{len(images)} — checking Shutterstock..."
                    )

                    try:
                        original = download_article_image(image["src"])
                        upload_jpg = normalize_for_shutterstock(original)
                        fingerprint = sha256_bytes(upload_jpg)

                        if use_cache and fingerprint in cache:
                            check = cache[fingerprint]
                            check = dict(check)
                            check["notes"] = (
                                "Reused cached result. " +
                                str(check.get("notes", ""))
                            )
                        else:
                            check = check_on_shutterstock(
                                shutter_page, upload_jpg
                            )
                            if use_cache and check["status"] not in (
                                "AUTOMATION ERROR",
                                "MANUAL CHECK",
                            ):
                                cache[fingerprint] = check
                                save_cache(cache)

                        row = {
                            "article_url": article_url,
                            "article_title": title,
                            "position": image["position"],
                            "image_url": image["src"],
                            "status": check["status"],
                            "shutterstock_url": check["shutterstock_url"],
                            "confidence": round(float(check["score"]) * 100, 1),
                            "phash_similarity": round(
                                float(check["phash_similarity"]) * 100, 1
                            ),
                            "sift_good_matches": int(
                                check["sift_good_matches"]
                            ),
                            "sift_inlier_ratio": round(
                                float(check["sift_inlier_ratio"]) * 100, 1
                            ),
                            "notes": check["notes"],
                            "_preview": upload_jpg,
                        }
                        results.append(row)

                    except Exception as e:
                        results.append({
                            "article_url": article_url,
                            "article_title": title,
                            "position": image["position"],
                            "image_url": image["src"],
                            "status": "IMAGE ERROR",
                            "shutterstock_url": "",
                            "confidence": 0,
                            "phash_similarity": 0,
                            "sift_good_matches": 0,
                            "sift_inlier_ratio": 0,
                            "notes": str(e),
                        })

                    display_rows = [
                        {k: v for k, v in r.items() if not k.startswith("_")}
                        for r in results
                    ]
                    live_table.dataframe(
                        pd.DataFrame(display_rows),
                        use_container_width=True,
                        hide_index=True,
                    )

                overall.progress(
                    article_idx / len(urls),
                    text=f"Completed {article_idx}/{len(urls)} articles",
                )

        finally:
            context.close()

    status_box.success("Check completed.")
    overall.progress(1.0, text="Completed")

    st.subheader("Results")

    display_rows = [
        {k: v for k, v in r.items() if not k.startswith("_")}
        for r in results
    ]
    result_df = pd.DataFrame(display_rows)

    st.dataframe(
        result_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "article_url": st.column_config.LinkColumn("Article URL"),
            "image_url": st.column_config.LinkColumn("Article Image URL"),
            "shutterstock_url": st.column_config.LinkColumn(
                "Shutterstock Image URL"
            ),
            "confidence": st.column_config.NumberColumn(
                "Confidence", format="%.1f%%"
            ),
        },
    )

    st.subheader("Image Review")
    for i, r in enumerate(results, start=1):
        if "_preview" not in r:
            continue

        with st.expander(
            f"{i}. {r['position']} — {r['status']}",
            expanded=r["status"] in ("MATCH FOUND", "POSSIBLE MATCH"),
        ):
            c1, c2 = st.columns([1, 1])

            with c1:
                st.write("Article image")
                st.image(r["_preview"], use_container_width=True)

            with c2:
                st.write("Result")
                st.write(f"**{r['status']}**")
                st.write(f"Confidence: **{r['confidence']:.1f}%**")
                if r["shutterstock_url"]:
                    st.link_button(
                        "Open Shutterstock match",
                        r["shutterstock_url"],
                    )
                else:
                    st.write("No Shutterstock URL saved.")

    excel_bytes = make_excel(results)

    st.download_button(
        "Download Excel Report",
        data=excel_bytes,
        file_name="shutterstock_check_results.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        use_container_width=True,
    )

    counts = result_df["status"].value_counts().to_dict() if not result_df.empty else {}
    st.write(
        "**Summary:** "
        + " · ".join(f"{k}: {v}" for k, v in counts.items())
    )
