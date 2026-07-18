import json, re, time, requests

TOKEN = "nKg4PEPDb9uENnPuL5C5DQ"
BASE = "https://api.crawlbase.com/"

def crawl(url, scraper=None):
    params = {"token": TOKEN, "url": url}
    if scraper:
        params["scraper"] = scraper
    try:
        r = requests.get(BASE, params=params, timeout=90)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"  Request error: {e}")
    return None

def extract_codes(html):
    codes = re.findall(r'/reel/([A-Za-z0-9_-]{11,})', html)
    codes += re.findall(r'"code"\s*:\s*"([A-Za-z0-9_-]{11,})"', html)
    codes += re.findall(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]{11,})"', html)
    return list({c for c in codes if len(c) >= 10 and c not in ('en_US', 'ru_RU', 'zh_CN')})

# Source URLs
source_urls = [
    "https://www.instagram.com/popular/most-viewed-reel-in-instagram/?hl=en",
    "https://www.instagram.com/popular/instagram-highest-views-reel/",
    "https://www.instagram.com/explore/search/keyword/?q=%23trendingreels",
]

all_codes = set()
for url in source_urls:
    print(f"Fetching: {url[:70]}...")
    html = crawl(url)
    if html:
        codes = extract_codes(html)
        all_codes.update(codes)
        print(f"  Found {len(codes)} codes")

all_codes = list(all_codes)[:100]
print(f"\nTotal unique reel codes: {len(all_codes)}")
for c in all_codes:
    print(f"  https://www.instagram.com/reels/{c}/")

results = []
for i, code in enumerate(all_codes):
    reel_url = f"https://www.instagram.com/reels/{code}/"
    print(f"\n[{i+1}/{len(all_codes)}] {code}...", end=" ", flush=True)

    data = crawl(reel_url, "instagram-reel")
    if not data:
        print("scrape fail")
        continue

    try:
        bd = json.loads(data).get("body", {})
    except:
        print("parse fail")
        continue

    uname = bd.get("username", "")
    entry = {
        "username": uname,
        "profile_url": f"https://www.instagram.com/{uname}/" if uname and uname != "Sign up for Instagram to stay in the loop." else None,
        "reel_url": reel_url,
        "reel_id": code,
        "caption": (bd.get("caption") or "")[:200],
        "likes": bd.get("likesCount"),
        "comments": bd.get("commentsCount"),
        "video_url": bd.get("videoUrl"),
        "profile_image": bd.get("profileImage"),
    }

    if entry["profile_url"]:
        pd = crawl(f"https://www.instagram.com/{uname}/", "instagram-profile")
        if pd:
            try:
                pdb = json.loads(pd).get("body", {})
                fc = pdb.get("followersCount", {})
                entry["followers"] = fc.get("value") if isinstance(fc, dict) else fc
                entry["verified"] = pdb.get("verified")
                entry["full_name"] = pdb.get("name", "")
                entry["bio"] = (pdb.get("bio", {}) or {}).get("text", "")[:150]
            except:
                pass

    results.append(entry)
    print(f"@{uname} likes:{entry.get('likes')} followers:{entry.get('followers')}")
    time.sleep(0.5)

with open("trending_reels_output.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\n=== DONE: {len(results)} reels saved to trending_reels_output.json ===")
print(f"\n{'#':<4} {'Username':<22} {'Likes':<10} {'Followers':<12} {'Reel ID':<16}")
print("-"*68)
for i, r in enumerate(results):
    print(f"{i+1:<4} {r.get('username','?'):<22} {str(r.get('likes','')):<10} {str(r.get('followers','')):<12} {r.get('reel_id','')}")
