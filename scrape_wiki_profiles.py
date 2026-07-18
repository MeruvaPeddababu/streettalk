import json, re, time, os
from playwright.sync_api import sync_playwright
import requests

WIKI_PROFILES = [
    "deepikapadukone", "hardikpandya", "bgmi", "leomessi",
    "virat.kohli", "mohdarshad", "netflix_in", "narendramodi"
]

MIN_LIKES = 500000
MAX_PER_PROFILE = 10

def get_likes_from_embed(code):
    try:
        resp = requests.get(f"https://www.instagram.com/p/{code}/embed/", timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        m = re.search(r'([\d,]+)\s*(?:likes?)', resp.text)
        return int(m.group(1).replace(",", "")) if m else 0
    except:
        return 0

with open("profile_info.json") as f:
    existing = json.load(f)

existing_usernames = set(existing.keys())
new_profiles = [u for u in WIKI_PROFILES if u not in existing_usernames]
print(f"Existing: {len(existing)} profiles")
print(f"New to scrape: {new_profiles}")

if not new_profiles:
    print("All wiki profiles already exist, nothing to do.")
    exit(0)

all_profiles = dict(existing)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        storage_state="instagram_state.json" if os.path.exists("instagram_state.json") else None
    )
    page = ctx.new_page()

    for idx, username in enumerate(new_profiles):
        url = f"https://www.instagram.com/{username}/"
        print(f"\n[{idx+1}/{len(new_profiles)}] @{username}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except:
            print("  timeout, skip")
            continue
        time.sleep(3)

        profile = {
            "username": username,
            "profile_url": url,
            "profile_pic": "",
            "bio": "",
            "followers": 0,
            "following": 0,
            "posts": 0,
            "top_reels": []
        }

        try:
            meta = page.query_selector("meta[property='og:image']")
            if meta:
                profile["profile_pic"] = meta.get_attribute("content") or ""
        except:
            pass
        try:
            meta = page.query_selector("meta[property='og:description']")
            if meta:
                profile["bio"] = meta.get_attribute("content") or ""
        except:
            pass

        urls_to_try = [url.rstrip("/") + "/reels/", url]
        all_codes = []
        for pu in urls_to_try:
            try:
                page.goto(pu, wait_until="domcontentloaded", timeout=15000)
            except:
                continue
            time.sleep(2)
            seen, ordered = set(), []
            for scroll in range(8):
                links = page.eval_on_selector_all(
                    "a[href*='/reel/'], a[href*='/p/']",
                    "els => els.map(el => el.href)"
                )
                for l in links:
                    m = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]{11,})', l)
                    if m and m.group(1) not in seen:
                        seen.add(m.group(1))
                        ordered.append(m.group(1))
                if len(ordered) >= MAX_PER_PROFILE:
                    break
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                time.sleep(1.5)
            all_codes.extend(ordered)
            if len(all_codes) >= MAX_PER_PROFILE:
                break

        seen2, ordered2 = set(), []
        for c in all_codes:
            if c not in seen2:
                seen2.add(c)
                ordered2.append(c)
        codes = ordered2[:MAX_PER_PROFILE]
        print(f"  reels: {len(codes)}")

        for code in codes:
            likes = get_likes_from_embed(code)
            profile["top_reels"].append({
                "reel_url": f"https://www.instagram.com/reel/{code}/",
                "reel_id": code,
                "likes": likes
            })

        all_profiles[username] = profile
        with open("profile_info.json", "w") as f:
            json.dump(all_profiles, f, indent=2)
        print(f"  saved ({len(all_profiles)} total)")

    ctx.storage_state(path="instagram_state.json")
    browser.close()

print(f"\n=== DONE: {len(all_profiles)} total profiles ({len(new_profiles)} new) ===")
