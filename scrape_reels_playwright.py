import json, re, time, os, sys, requests
from playwright.sync_api import sync_playwright

env_path = os.path.join(os.path.dirname(__file__), ".env")
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

IG_USER = os.getenv("IG_USER", "")
IG_PASS = os.getenv("IG_PASS", "")

URLS = [
    "https://www.instagram.com/explore/search/keyword/?q=%23trendingreels",
]

MAX_REELS = 150
MIN_LIKES = 500_000
STATE_FILE = "instagram_state.json"

def login(page):
    page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
    page.wait_for_timeout(5000)
    for sel in ['input[name="username"]', 'input[name="email"]', 'input[type="text"]', 'input[autocomplete="username"]']:
        try:
            if page.locator(sel).first.is_visible(timeout=3000):
                page.locator(sel).first.fill(IG_USER)
                break
        except:
            continue
    for sel in ['input[name="password"]', 'input[name="pass"]', 'input[type="password"]']:
        try:
            if page.locator(sel).first.is_visible(timeout=3000):
                page.locator(sel).first.fill(IG_PASS)
                break
        except:
            continue
    page.keyboard.press('Enter')
    page.wait_for_timeout(8000)
    for _ in range(2):
        try:
            page.locator("button:has-text('Not Now')").first.click(timeout=5000)
            page.wait_for_timeout(2000)
        except:
            pass

def collect_reel_codes(page, url, max_reels=50):
    print(f"\n=== {url[:60]} ===")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except:
        print("  Skipping (timeout)")
        return []
    time.sleep(4)
    seen = set()
    ordered = []
    for scroll in range(20):
        links = page.eval_on_selector_all(
            "a[href*='/reel/'], a[href*='/p/']",
            'els => els.map(el => el.href)'
        )
        for l in links:
            m = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]{11,})', l)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                ordered.append(m.group(1))
        print(f"  Scroll {scroll+1}: {len(ordered)} reels found")
        if len(ordered) >= max_reels:
            break
        page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        time.sleep(1.5)
    return ordered[:max_reels]

def get_reel_data_from_embed(code):
    """Fetch like count + username from public Instagram embed page."""
    url = f"https://www.instagram.com/p/{code}/embed/"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return 0, None
        text = r.text
        likes_m = re.search(r'([\d,]+)\s*(?:likes?)', text, re.IGNORECASE)
        likes = int(likes_m.group(1).replace(",", "")) if likes_m else 0
        unames = list(set(re.findall(r'instagram\.com/([A-Za-z0-9._]+)', text)))
        # Filter valid usernames
        excluded = {'p', 'reel', 'reels', 'explore', 'stories', 'accounts', 'login', 'signup', 'embed', 'v', 'rsrc.php', 'jpg', 'png'}
        username = next((u for u in unames if u not in excluded), None)
        return likes, username
    except:
        return 0, None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        storage_state=STATE_FILE if os.path.exists(STATE_FILE) else None,
    )
    page = context.new_page()
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)

    if os.path.exists(STATE_FILE):
        print("Loaded saved session. Checking login...")
        page.goto("https://www.instagram.com/", wait_until="networkidle")
        page.wait_for_timeout(3000)
        if page.locator('input[name="username"]').is_visible(timeout=3000):
            print("Session expired, re-logging in...")
            login(page)
        else:
            print("Session valid!")
    else:
        print("Logging in...")
        login(page)

    context.storage_state(path=STATE_FILE)
    print("Session saved!")

    # Step 1: Collect reel codes from search page
    all_codes = []
    for url in URLS:
        codes = collect_reel_codes(page, url, MAX_REELS)
        all_codes.extend(codes)
    all_codes = list(dict.fromkeys(all_codes))
    print(f"\nTotal unique reel codes: {len(all_codes)}")

    browser.close()

    # Step 2: Check each reel via public embed API
    print(f"\nChecking likes via embed (min {MIN_LIKES:,})...")
    results = []
    OUTPUT_PATH = "reels_playwright_output.json"

    for i, code in enumerate(all_codes):
        likes, username = get_reel_data_from_embed(code)
        ok = likes >= MIN_LIKES and username is not None
        label = f"{likes:,}" if likes else "0"
        print(f"  [{i+1}/{len(all_codes)}] {code}: {label} {'✓' if ok else '✗'} @{username or '?'}")

        if ok:
            results.append({
                "reel_url": f"https://www.instagram.com/reel/{code}/",
                "reel_id": code,
                "profile_url": f"https://www.instagram.com/{username}/",
                "username": username,
                "likes": likes,
            })

        if results:
            with open(OUTPUT_PATH, "w") as f:
                json.dump({"total_reels": len(results), "min_likes": MIN_LIKES, "results": results}, f, indent=2)

    with open(OUTPUT_PATH, "w") as f:
        json.dump({"total_reels": len(results), "min_likes": MIN_LIKES, "results": results}, f, indent=2)

    total_time = "N/A"
    print(f"\n=== DONE: {len(results)} reels with {MIN_LIKES:,}+ likes saved to {OUTPUT_PATH} ===")
    for i, r in enumerate(results):
        print(f"{i+1}. @{r['username']} | {r['likes']:,} likes | {r['reel_url']}")
