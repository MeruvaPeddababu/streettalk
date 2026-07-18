import json, re, time, os
from playwright.sync_api import sync_playwright
import requests

MIN_LIKES = 500000
MAX_PER_PROFILE = 30
MAX_PROFILES = 3

with open("reels_playwright_output.json") as f:
    data = json.load(f)

profiles = sorted(set(r["profile_url"] for r in data["results"]))
print(f"Profiles: {len(profiles)}")
if MAX_PROFILES:
    profiles = profiles[:MAX_PROFILES]

def get_likes_from_embed(code):
    url = f"https://www.instagram.com/p/{code}/embed/"
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        html = resp.text
        m = re.search(r'([\d,]+)\s*(?:likes?)', html)
        likes = int(m.group(1).replace(",", "")) if m else 0
        m2 = re.search(r'instagram\.com/([A-Za-z0-9._]+)', html)
        username = m2.group(1) if m2 else "?"
        return likes, username
    except:
        return 0, "?"

all_results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
        storage_state="instagram_state.json" if os.path.exists("instagram_state.json") else None
    )
    page = ctx.new_page()

    for idx, profile_url in enumerate(profiles):
        username = profile_url.rstrip("/").split("/")[-1]
        # Try reels tab first
        urls_to_try = [
            profile_url.rstrip("/") + "/reels/",
            profile_url
        ]
        
        all_codes = []
        for pu in urls_to_try:
            print(f"\n[{idx+1}/{len(profiles)}] {pu}")
            try:
                page.goto(pu, wait_until="domcontentloaded", timeout=20000)
            except:
                print("  timeout")
                continue
            time.sleep(3)

            seen, ordered = set(), []
            for scroll in range(10):
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
            print(f"  found {len(ordered)}")
            all_codes.extend(ordered)
            if len(all_codes) >= MAX_PER_PROFILE:
                break
        
        # dedup keeping order
        seen2, ordered2 = set(), []
        for c in all_codes:
            if c not in seen2:
                seen2.add(c)
                ordered2.append(c)
        
        print(f"  total unique: {len(ordered2)}")
        for j, code in enumerate(ordered2[:MAX_PER_PROFILE]):
            likes, user = get_likes_from_embed(code)
            mark = "✓" if likes >= MIN_LIKES else "✗"
            print(f"    [{j+1}/{min(len(ordered2), MAX_PER_PROFILE)}] {code}: {likes:,} {mark} @{user}")
            if likes >= MIN_LIKES:
                all_results.append({
                    "reel_url": f"https://www.instagram.com/reel/{code}/",
                    "reel_id": code,
                    "username": user,
                    "profile_url": f"https://www.instagram.com/{user}/",
                    "likes": likes
                })
                with open("profile_reels_output.json", "w") as f:
                    json.dump({"total": len(all_results), "results": all_results}, f, indent=2)

    ctx.storage_state(path="instagram_state.json")
    browser.close()

print(f"\n=== DONE: {len(all_results)} reels from {len(profiles)} profiles ===")
for r in all_results:
    print(f"  @{r['username']} | {r['likes']:,} likes | {r['reel_url']}")
