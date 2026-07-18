from playwright.sync_api import sync_playwright
import time
import csv
import re
from datetime import datetime

# ====================== CONFIG ======================
MIN_LIKES = 500000
CHECK_LAST_N_REELS = 10

def extract_number(text):
    if not text:
        return 0
    text = text.upper().replace(',', '').replace(' ', '')
    if 'M' in text:
        return int(float(text.replace('M', '')) * 1_000_000)
    elif 'K' in text:
        return int(float(text.replace('K', '')) * 1_000)
    return int(''.join(filter(str.isdigit, text))) if any(c.isdigit() for c in text) else 0

# ====================== IMPROVED SEARCH ======================
def search_instagram_profiles():
    usernames = set()
    queries = [
        "instgram sports profiles",
        "best wildlife Instagram accounts",
        "popular nature Instagram influencers",
        "landscape photography Instagram"
    ]
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        for query in queries:
            print(f"🔎 Searching: {query}")
            page.goto("https://duckduckgo.com")
            page.fill('input[name="q"]', query)
            page.keyboard.press("Enter")
            time.sleep(5)
            
            links = page.locator('a[href*="instagram.com"]').all()
            for link in links[:30]:
                try:
                    href = link.get_attribute("href")
                    if href:
                        match = re.search(r'instagram\.com/([^/?#&]+)', href)
                        if match:
                            username = match.group(1).strip().lower()
                            if username and len(username) > 2 and not username.startswith("p/"):
                                usernames.add(username)
                except:
                    continue
        
        browser.close()
    
    username_list = list(usernames)
    print(f"✅ Found {len(username_list)} Nature Instagram Profiles")
    return username_list[:25]   # Limit to 25

# ====================== SCRAPE ======================
def scrape_profiles(usernames):
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        for username in usernames:
            print(f"🌿 Checking @{username}...")
            try:
                page.goto(f"https://www.instagram.com/{username}/", wait_until="networkidle")
                time.sleep(6)
                
                followers = 0
                try:
                    followers = extract_number(page.locator("a[href*='/followers/']").inner_text(timeout=5000))
                except:
                    pass
                
                reel_data = []
                for _ in range(3):
                    page.evaluate("window.scrollBy(0, 1500)")
                    time.sleep(3)
                
                posts = page.locator('article a[href*="/reel/"]').all()[:CHECK_LAST_N_REELS]
                
                for post in posts:
                    try:
                        post.click()
                        time.sleep(4)
                        likes_text = page.locator('span[aria-label*="like"]').first.inner_text(timeout=4000)
                        likes = extract_number(likes_text)
                        if likes > 0:
                            reel_data.append(likes)
                        page.keyboard.press("Escape")
                        time.sleep(2)
                    except:
                        continue
                
                if reel_data:
                    high = sum(1 for x in reel_data if x >= MIN_LIKES)
                    avg = sum(reel_data) // len(reel_data)
                    score = int(avg * 0.7 + high * 200000)
                    
                    results.append({
                        "username": username,
                        "followers": followers,
                        "reels_analyzed": len(reel_data),
                        "posts_500k_plus": high,
                        "avg_likes": avg,
                        "trend_score": score,
                        "is_trending": high >= 1
                    })
                    print(f"   → {high} reels ≥500k | Avg Likes: {avg:,}")
            except:
                print(f"   Failed @{username}")
                continue
        
        browser.close()
    
    return results

# ====================== RUN ======================
if __name__ == "__main__":
    print("🚀 Starting Nature Trend Intelligence Agent")
    
    usernames = search_instagram_profiles()
    results = scrape_profiles(usernames)
    
    if results:
        results.sort(key=lambda x: x["trend_score"], reverse=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        
        with open(f"nature_trending_ranked_{timestamp}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        
        print("\n🏆 TOP RANKED NATURE PROFILES")
        print("="*80)
        for i, r in enumerate(results[:15], 1):
            status = "🔥 TRENDING" if r["is_trending"] else ""
            print(f"{i:2d}. @{r['username']:25} | Followers: {r['followers']:>10,} | 500k+: {r['posts_500k_plus']} | Score: {r['trend_score']:>10,} {status}")
    else:
        print("No results found. Try running again.")