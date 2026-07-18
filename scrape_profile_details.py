import json, re, time, os
from playwright.sync_api import sync_playwright
import requests

MIN_LIKES = 500000
MAX_PER_PROFILE = 10

with open("reels_playwright_output.json") as f:
    data = json.load(f)

profiles = sorted(set(r["profile_url"] for r in data["results"]))
print(f"Profiles: {len(profiles)}")

def get_likes_from_embed(code):
    url = f"https://www.instagram.com/p/{code}/embed/"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        html = resp.text
        m = re.search(r'([\d,]+)\s*(?:likes?)', html)
        likes = int(m.group(1).replace(",", "")) if m else 0
        return likes
    except:
        return 0

all_profiles = {}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        storage_state="instagram_state.json" if os.path.exists("instagram_state.json") else None
    )
    page = ctx.new_page()

    for idx, profile_url in enumerate(profiles):
        username = profile_url.rstrip("/").split("/")[-1]
        print(f"\n[{idx+1}/{len(profiles)}] @{username}")

        try:
            page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
        except:
            print("  timeout, skip")
            continue
        time.sleep(3)

        profile_info = {
            "username": username,
            "profile_url": profile_url,
            "profile_pic": "",
            "bio": "",
            "followers": 0,
            "following": 0,
            "posts": 0,
            "top_reels": []
        }

        try:
            meta_img = page.query_selector("meta[property='og:image']")
            if meta_img:
                profile_info["profile_pic"] = meta_img.get_attribute("content")
        except:
            pass

        try:
            bio_el = page.query_selector("meta[property='og:description']")
            if bio_el:
                content = bio_el.get_attribute("content") or ""
                profile_info["bio"] = content
        except:
            pass

        try:
            text = page.inner_text("header section")
            followers_m = re.search(r'([\d,.KMkmB]+)\s*(?:follower|Follower)', text)
            if followers_m:
                val = followers_m.group(1)
                if "M" in val or "m" in val:
                    profile_info["followers"] = int(float(val.replace("M", "").replace("m", "")) * 1000000)
                elif "K" in val or "k" in val:
                    profile_info["followers"] = int(float(val.replace("K", "").replace("k", "")) * 1000)
                else:
                    profile_info["followers"] = int(val.replace(",", ""))
        except:
            pass

        try:
            text = page.inner_text("header section")
            posts_m = re.search(r'([\d,]+)\s*(?:posts|Posts)', text)
            if posts_m:
                profile_info["posts"] = int(posts_m.group(1).replace(",", ""))
        except:
            pass

        try:
            text = page.inner_text("header section")
            following_m = re.search(r'([\d,]+)\s*(?:following|Following)', text)
            if following_m:
                profile_info["following"] = int(following_m.group(1).replace(",", ""))
        except:
            pass

        urls_to_try = [
            profile_url.rstrip("/") + "/reels/",
            profile_url
        ]

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
            profile_info["top_reels"].append({
                "reel_url": f"https://www.instagram.com/reel/{code}/",
                "reel_id": code,
                "likes": likes
            })

        all_profiles[username] = profile_info
        with open("profile_info.json", "w") as f:
            json.dump(all_profiles, f, indent=2)
        print(f"  saved ({len(all_profiles)}/{len(profiles)})")

    ctx.storage_state(path="instagram_state.json")
    browser.close()

print(f"\n=== DONE: {len(all_profiles)} profiles ===")
