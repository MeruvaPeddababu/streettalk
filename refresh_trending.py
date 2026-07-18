import json, re, time, requests, os, sys, urllib.parse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
MIN_LIKES = 500_000
MAX_REELS = 1500
STATE_FILE = HERE / "instagram_state.json"

env_path = HERE / ".env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

IG_USER = os.getenv("IG_USER", "")
IG_PASS = os.getenv("IG_PASS", "")

# Hashtags to search for popular reels
HASHTAGS = [
    "#trendingreels", "#viral", "#fyp", "#explorepage", "#trending",
    "#viralreels", "#reelsinstagram", "#explore", "#reels", "#viralshorts",
    "#foryou", "#foryoupage", "#viralvideo", "#instareels", "#reelit",
    "#reeltrending", "#viralvideos", "#fypage", "#trendingvideo",
    "#reelkarofeelkaro", "#reelinstagram", "#viralpost", "#trendingsongs",
    "#comedyreels", "#dancereels", "#fashionreels", "#fitnessreels",
    "#beautyreels", "#foodreels", "#travelreels", "#musicreels",
    "#motivationreels", "#diyreels", "#sportsreels",
    "#memereels", "#makeupreels",
]

SESSION_TOKENS = {}

def get_reel_data_from_embed(code):
    url = f"https://www.instagram.com/p/{code}/embed/"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200 or len(r.text) < 100000:
            return 0, None
        text = r.text
        likes_m = re.search(r'([\d,]+)\s*(?:likes?)', text, re.IGNORECASE)
        likes = int(likes_m.group(1).replace(",", "")) if likes_m else 0
        unames = list(set(re.findall(r'instagram\.com/([A-Za-z0-9._]+)', text)))
        excluded = {'p', 'reel', 'reels', 'explore', 'stories', 'accounts', 'login', 'signup', 'embed', 'v', 'rsrc.php', 'jpg', 'png', 'fb', 'static', '_n'}
        username = next((u for u in unames if u not in excluded), None)
        return likes, username
    except:
        return 0, None

def login_and_capture_tokens():
    global SESSION_TOKENS
    print("Logging into Instagram...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,
            args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        if STATE_FILE.exists():
            page.goto("https://www.instagram.com/", wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)
            if page.locator('input[name="username"]').is_visible(timeout=3000):
                print("Session expired, logging in...")
                page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
                page.wait_for_timeout(3000)
                for sel in ['input[name="username"]', 'input[type="text"]']:
                    try:
                        if page.locator(sel).first.is_visible(timeout=2000):
                            page.locator(sel).first.fill(IG_USER)
                            break
                    except: pass
                for sel in ['input[name="password"]', 'input[type="password"]']:
                    try:
                        if page.locator(sel).first.is_visible(timeout=2000):
                            page.locator(sel).first.fill(IG_PASS)
                            break
                    except: pass
                page.keyboard.press('Enter')
                page.wait_for_timeout(8000)
        else:
            print("No session, logging in...")
            page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
            page.wait_for_timeout(3000)
            for sel in ['input[name="username"]', 'input[type="text"]']:
                try:
                    if page.locator(sel).first.is_visible(timeout=2000):
                        page.locator(sel).first.fill(IG_USER)
                        break
                except: pass
            for sel in ['input[name="password"]', 'input[type="password"]']:
                try:
                    if page.locator(sel).first.is_visible(timeout=2000):
                        page.locator(sel).first.fill(IG_PASS)
                        break
                except: pass
            page.keyboard.press('Enter')
            page.wait_for_timeout(8000)

        context.storage_state(path=str(STATE_FILE))

        # Extract tokens from initial page load
        raw = page.evaluate("document.documentElement.innerHTML")
        fb_dtsg = None
        for m in re.finditer(r'"fb_dtsg"[^:]*:\s*"([^"]+)"', raw):
            fb_dtsg = m.group(1)
            break
        lsd = None
        for m in re.finditer(r'"lsd"[^:]*:\s*"([^"]+)"', raw):
            lsd = m.group(1)
            break

        cookies = {c['name']: c['value'] for c in context.cookies()}

        SESSION_TOKENS = {
            "cookies": cookies,
            "fb_dtsg": fb_dtsg,
            "lsd": lsd,
        }
        print(f"  Logged in as: {cookies.get('ds_user_id', '?')}")
        print(f"  fb_dtsg: {'✓' if fb_dtsg else '✗'}")
        print(f"  lsd: {'✓' if lsd else '✗'}")

        # Now collect reel codes from multiple hashtag searches
        all_seen = set()
        all_codes_with_data = []

        for ht in HASHTAGS:
            if len(all_seen) >= MAX_REELS:
                break
            print(f"\nSearching: {ht}")
            page.goto(f"https://www.instagram.com/explore/search/keyword/?q={urllib.parse.quote(ht)}",
                wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            for s in range(2):
                page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)

            # Extract reel codes from page HTML (links even without full render)
            html = page.content()
            codes_in_page = set(re.findall(r'/reel/([A-Za-z0-9_-]{11,})', html))
            new_codes = codes_in_page - all_seen
            all_seen.update(new_codes)
            print(f"  Found {len(new_codes)} new codes (total: {len(all_seen)})")

        # Fallback: also use any existing codes
        if len(all_seen) < 10:
            print("\nNot enough codes from API, adding existing codes...")
            for fname in ["reels_playwright_output.json", "trending_reels_30.json"]:
                fp = HERE / fname
                if fp.exists():
                    try:
                        data = json.loads(fp.read_text())
                        items = data if isinstance(data, list) else data.get("results", [])
                        for item in items:
                            code = item.get("reel_id")
                            if code and code not in all_seen:
                                all_seen.add(code)
                    except:
                        pass

        # Load previous results to scrape profiles of top creators
        previous_results = []
        for fname in ["reels_playwright_output.json"]:
            fp = HERE / fname
            if fp.exists():
                try:
                    data = json.loads(fp.read_text())
                    previous_results = data if isinstance(data, list) else data.get("results", [])
                except:
                    pass

        # Add existing known codes
        for item in previous_results:
            code = item.get("reel_id")
            if code and code not in all_seen:
                all_seen.add(code)

        # Scrape profile pages of top creators from previous results
        top_creators = list(dict.fromkeys(r["username"] for r in previous_results if r.get("username")))[:5]
        if top_creators:
            print(f"\nScraping profiles of {len(top_creators)} top creators...")
            for username in top_creators:
                if len(all_seen) >= MAX_REELS:
                    break
                print(f"  Profile: @{username}")
                try:
                    page.goto(f"https://www.instagram.com/{username}/",
                        wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(4000)
                    for s in range(5):
                        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                        page.wait_for_timeout(1500)
                    html = page.content()
                    codes_in_page = set(re.findall(r'/reel/([A-Za-z0-9_-]{11,})', html))
                    new_codes = codes_in_page - all_seen
                    all_seen.update(new_codes)
                    print(f"    Found {len(new_codes)} new reel codes")
                except Exception as e:
                    print(f"    Error: {e}")

        print(f"\nTotal unique codes collected: {len(all_seen)}")
        browser.close()
    return list(all_seen)[:MAX_REELS]

print("=== REFRESH TRENDING REELS ===")

codes = login_and_capture_tokens()

print(f"\nChecking {len(codes)} codes via embed...")

results = []
done = 0
def check_code(code):
    likes, username = get_reel_data_from_embed(code)
    ok = likes >= MIN_LIKES and username is not None
    return (code, likes, username, ok)

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = {executor.submit(check_code, code): code for code in codes}
    for future in as_completed(futures):
        code, likes, username, ok = future.result()
        done += 1
        print(f"  [{done}/{len(codes)}] {code}: {likes:,} {'✓' if ok else '✗'} @{username or '?'}")
        if ok:
            results.append({
                "username": username,
                "profile_url": f"https://www.instagram.com/{username}/",
                "reel_url": f"https://www.instagram.com/reel/{code}/",
                "reel_id": code,
                "caption": "",
                "likes": likes,
                "comments": 0,
            })
        time.sleep(0.1)

results.sort(key=lambda r: r["likes"], reverse=True)

# Merge with existing results (don't overwrite - accumulate)
existing_results = []
existing_path = HERE / "reels_playwright_output.json"
if existing_path.exists():
    try:
        existing_data = json.loads(existing_path.read_text())
        existing_results = existing_data if isinstance(existing_data, list) else existing_data.get("results", [])
    except:
        pass

seen_codes = set(r["reel_id"] for r in existing_results)
for r in results:
    if r["reel_id"] not in seen_codes:
        seen_codes.add(r["reel_id"])
        existing_results.append(r)

merged = sorted(existing_results, key=lambda x: x["likes"], reverse=True)
merged = merged[:MAX_REELS]

profiles = {}
for r in merged:
    u = r["username"]
    if u and u not in profiles:
        profiles[u] = {
            "username": u,
            "profile_url": r.get("profile_url", f"https://www.instagram.com/{u}/"),
            "profile_pic": "",
            "bio": "",
            "followers": 0,
            "following": 0,
            "posts": 0,
            "top_reels": []
        }

with open(HERE / "reels_playwright_output.json", "w") as f:
    json.dump({"total_reels": len(merged), "min_likes": MIN_LIKES, "results": merged}, f, indent=2)
with open(HERE / "profile_info.json", "w") as f:
    json.dump(profiles, f, indent=2)
with open(HERE / "trending_reels_30.json", "w") as f:
    json.dump(merged, f, indent=2)

print(f"\n=== DONE: {len(results)} new + {len(merged) - len(results)} existing = {len(merged)} total reels with {MIN_LIKES:,}+ likes ===")
