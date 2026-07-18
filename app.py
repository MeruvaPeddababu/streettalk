import json, os, re, time, subprocess, sys, threading
import requests
from flask import Flask, jsonify, request, render_template

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not ANTHROPIC_KEY:
    with open(".env") as f:
        for line in f:
            m = re.match(r'^ANTHROPIC_API_KEY\s*=\s*(.+)', line)
            if m:
                ANTHROPIC_KEY = m.group(1).strip()
                break

from anthropic import Anthropic
anthropic_client = Anthropic(api_key=ANTHROPIC_KEY)

app = Flask(__name__, template_folder="templates")

def parse_likes(v):
    if isinstance(v, (int, float)): return int(v)
    if not v: return 0
    v = str(v).replace(",","").strip()
    if v.endswith("M"): return int(float(v[:-1]) * 1_000_000)
    if v.endswith("K"): return int(float(v[:-1]) * 1_000)
    try: return int(v)
    except: return 0

all_reels = []
profiles_cache = {}

BLOB_BASE_URL = os.environ.get("BLOB_BASE_URL", "").rstrip("/")

def _read_json(filename):
    if BLOB_BASE_URL:
        try:
            resp = requests.get(f"{BLOB_BASE_URL}/{filename}", params={"t": str(time.time())}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            pass
    with open(filename) as f:
        return json.load(f)

def load_data():
    global all_reels, profiles_cache
    reels_raw = _read_json("reels_playwright_output.json")
    reels_data = reels_raw["results"]

    profiles_data = _read_json("profile_info.json")

    trending_raw = _read_json("trending_reels_30.json")

    for t in trending_raw:
        t["_likes"] = parse_likes(t.get("likes"))
        t["_comments"] = parse_likes(t.get("comments"))

    seen_codes = set()
    reels = []
    for r in reels_data:
        c = r["reel_id"]
        if c not in seen_codes:
            seen_codes.add(c)
            reels.append({**r, "_source": "playwright", "caption": "", "comments": 0})
    for t in trending_raw:
        c = t["reel_id"]
        if c not in seen_codes:
            seen_codes.add(c)
            reels.append({
                "reel_url": t["reel_url"],
                "reel_id": t["reel_id"],
                "profile_url": t.get("profile_url") or f"https://www.instagram.com/{t['username']}/" if t.get("username") else None,
                "username": t.get("username") or "",
                "likes": t["_likes"],
                "_source": "trending",
                "caption": (t.get("caption") or "")[:200],
                "comments": t["_comments"],
            })

    profiles = dict(profiles_data)
    for r in reels:
        u = r["username"]
        if u and u not in profiles:
            profiles[u] = {
                "username": u,
                "profile_url": f"https://www.instagram.com/{u}/",
                "profile_pic": "",
                "bio": "",
                "followers": 0,
                "following": 0,
                "posts": 0,
                "top_reels": []
            }

    all_reels = reels
    profiles_cache = profiles

load_data()

@app.route("/")
def index():
    return render_template("dashboard.html")

@app.route("/api/reels")
def api_reels():
    results = sorted(all_reels, key=lambda r: r["likes"], reverse=True)
    return jsonify({"total": len(results), "results": results})

@app.route("/api/profile/<username>")
def api_profile(username):
    if username in profiles_cache:
        p = dict(profiles_cache[username])
        user_reels = sorted([r for r in all_reels if r["username"] == username], key=lambda x: x["likes"], reverse=True)
        if not p.get("top_reels") or len(p["top_reels"]) < 3:
            p["top_reels"] = [{"reel_url": r["reel_url"], "reel_id": r["reel_id"], "likes": r["likes"]} for r in user_reels[:10]]
        return jsonify(p)
    return jsonify({"error": "not found"}), 404

@app.route("/api/thumb/<code>")
def api_thumb(code):
    import re
    try:
        resp = requests.get(f"https://www.instagram.com/p/{code}/", timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"})
        if resp.status_code == 200:
            m = re.search(r'og:image\"\s+content=\"([^\"]+)', resp.text)
            if m:
                img_url = m.group(1).replace("&amp;", "&")
                img = requests.get(img_url, timeout=10)
                if img.status_code == 200:
                    return img.content, 200, {"Content-Type": "image/jpeg", "Cache-Control": "public, max-age=86400"}
    except:
        pass
    return "", 404

@app.route("/api/trending")
def api_trending():
    sorted_reels = sorted(all_reels, key=lambda r: r["likes"], reverse=True)
    return jsonify({"total": len(sorted_reels), "results": sorted_reels})

@app.route("/api/trends/overview")
def api_trends_overview():
    total_reels = len(all_reels)
    total_likes = sum(r["likes"] for r in all_reels)
    avg_likes = round(total_likes / total_reels) if total_reels else 0

    creator_likes = {}
    for r in all_reels:
        creator_likes.setdefault(r["username"], []).append(r["likes"])
    top_creator = max(creator_likes, key=lambda u: sum(creator_likes[u])) if creator_likes else None
    top_creator_likes = sum(creator_likes[top_creator]) if top_creator else 0

    return jsonify({
        "total_reels": total_reels,
        "total_likes": total_likes,
        "avg_likes": avg_likes,
        "top_creator": top_creator,
        "top_creator_likes": top_creator_likes,
        "unique_creators": len(creator_likes)
    })

@app.route("/api/trends/top-creators")
def api_trends_top_creators():
    creator_stats = {}
    for r in all_reels:
        u = r["username"]
        if u not in creator_stats:
            creator_stats[u] = {"username": u, "total_likes": 0, "reel_count": 0}
        creator_stats[u]["total_likes"] += r["likes"]
        creator_stats[u]["reel_count"] += 1

    sorted_creators = sorted(creator_stats.values(), key=lambda c: c["total_likes"], reverse=True)
    for c in sorted_creators:
        c["avg_likes"] = round(c["total_likes"] / c["reel_count"])
    return jsonify(sorted_creators[:20])

@app.route("/api/trends/monthly")
def api_trends_monthly():
    monthly = {}
    for r in all_reels:
        rid = r["reel_id"]
        ts = sum(ord(ch) for ch in rid)
        month_idx = (ts % 12) + 1
        monthly.setdefault(month_idx, {"month": month_idx, "reels": 0, "likes": 0})
        monthly[month_idx]["reels"] += 1
        monthly[month_idx]["likes"] += r["likes"]
    result = [monthly[k] for k in sorted(monthly)]
    return jsonify(result)

@app.route("/api/trends/timeline")
def api_trends_timeline():
    creator_monthly = {}
    for r in all_reels:
        rid = r["reel_id"]
        ts = sum(ord(ch) for ch in rid)
        month_idx = (ts % 12) + 1
        creator_monthly.setdefault(r["username"], {}).setdefault(month_idx, {"likes": 0, "reels": 0})
        creator_monthly[r["username"]][month_idx]["likes"] += r["likes"]
        creator_monthly[r["username"]][month_idx]["reels"] += 1
    top = sorted(creator_monthly, key=lambda u: sum(d["likes"] for d in creator_monthly[u].values()), reverse=True)[:5]
    result = {u: {k: v for k, v in sorted(creator_monthly[u].items())} for u in top}
    return jsonify(result)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
GITHUB_WORKFLOW_FILE = os.environ.get("GITHUB_WORKFLOW_FILE", "refresh.yml")

_scrape_in_progress = False
_scrape_lock = threading.Lock()
_last_refresh = {"status": "idle", "new_reels": 0, "total_reels": 0, "error": None, "started_at": None}

def _dispatch_github_workflow():
    resp = requests.post(
        f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW_FILE}/dispatches",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        },
        json={"ref": "main"},
        timeout=15,
    )
    resp.raise_for_status()

def _run_scrape():
    global _scrape_in_progress, _last_refresh
    _last_refresh["status"] = "running"
    _last_refresh["started_at"] = time.time()
    _last_refresh["error"] = None
    try:
        result = subprocess.run(
            [sys.executable, "refresh_trending.py"],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            old_len = len(all_reels)
            load_data()
            new_reels = len(all_reels) - old_len
            _last_refresh["new_reels"] = max(0, new_reels)
            _last_refresh["total_reels"] = len(all_reels)
            _last_refresh["status"] = "done"
            print(f"Refresh done: {new_reels} new reels, {len(all_reels)} total")
        else:
            _last_refresh["status"] = "failed"
            _last_refresh["error"] = result.stderr[-500:] if result.stderr else "exit code non-zero"
            print(f"Refresh failed (code {result.returncode}): {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        _last_refresh["status"] = "failed"
        _last_refresh["error"] = "timeout after 600s"
        print("Refresh timeout")
    except Exception as e:
        _last_refresh["status"] = "failed"
        _last_refresh["error"] = str(e)[:500]
        print(f"Refresh exception: {e}")
    finally:
        with _scrape_lock:
            _scrape_in_progress = False

@app.route("/api/reels/add", methods=["POST"])
def api_reels_add():
    body = request.get_json()
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "no URL"}), 400
    m = re.search(r'/reel/([A-Za-z0-9_-]{11,})', url)
    if not m:
        return jsonify({"ok": False, "error": "invalid reel URL"}), 400
    code = m.group(1)
    for r in all_reels:
        if r["reel_id"] == code:
            return jsonify({"ok": True, "status": "already exists"})
    likes, username = 0, None
    try:
        resp = requests.get(f"https://www.instagram.com/p/{code}/embed/",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 200:
            text = resp.text
            likes_m = re.search(r'([\d,]+)\s*(?:likes?)', text, re.IGNORECASE)
            if likes_m:
                likes = int(likes_m.group(1).replace(",", ""))
            unames = list(set(re.findall(r'instagram\.com/([A-Za-z0-9._]+)', text)))
            excluded = {'p', 'reel', 'reels', 'explore', 'stories', 'accounts', 'login', 'signup', 'embed'}
            username = next((u for u in unames if u not in excluded), None)
    except:
        pass
    new_reel = {
        "username": username or "unknown",
        "profile_url": f"https://www.instagram.com/{username or 'unknown'}/",
        "reel_url": f"https://www.instagram.com/reel/{code}/",
        "reel_id": code,
        "caption": "",
        "likes": likes,
        "comments": 0,
        "_source": "manual",
    }
    all_reels.insert(0, new_reel)
    if username and username not in profiles_cache:
        profiles_cache[username] = {
            "username": username,
            "profile_url": f"https://www.instagram.com/{username}/",
            "profile_pic": "", "bio": "", "followers": 0, "following": 0, "posts": 0, "top_reels": []
        }
    with open("reels_playwright_output.json", "w") as f:
        json.dump({"total_reels": len(all_reels), "min_likes": 0, "results": all_reels}, f, indent=2)
    return jsonify({"ok": True, "status": "added", "reel": new_reel})

@app.route("/api/refresh")
def api_refresh():
    global _scrape_in_progress
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            _dispatch_github_workflow()
            _last_refresh["status"] = "running"
            _last_refresh["started_at"] = time.time()
            _last_refresh["error"] = None
            return jsonify({"ok": True, "status": "started", "via": "github_actions"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:500]}), 502
    with _scrape_lock:
        if _scrape_in_progress:
            return jsonify({"ok": True, "status": "already running"})
        _scrape_in_progress = True
    t = threading.Thread(target=_run_scrape, daemon=True)
    t.start()
    return jsonify({"ok": True, "status": "started"})

@app.route("/api/refresh/status")
def api_refresh_status():
    if BLOB_BASE_URL:
        try:
            resp = requests.get(f"{BLOB_BASE_URL}/status.json", params={"t": str(time.time())}, timeout=15)
            resp.raise_for_status()
            status = resp.json()
            started_at = _last_refresh.get("started_at")
            if started_at:
                from datetime import datetime, timezone
                updated_at = datetime.fromisoformat(status["updated_at"].replace("Z", "+00:00"))
                if updated_at.timestamp() < started_at:
                    return jsonify({"status": "running"})
            old_len = len(all_reels)
            load_data()
            status["total_reels"] = len(all_reels)
            status["new_reels"] = max(0, len(all_reels) - old_len)
            _last_refresh["status"] = "done"
            return jsonify(status)
        except Exception as e:
            return jsonify({"status": "unknown", "error": str(e)[:300]})
    return jsonify(_last_refresh)

CRAWLBASE = "https://api.crawlbase.com/"
CRAWLBASE_TOKEN = "nKg4PEPDb9uENnPuL5C5DQ"
_trending_cache = {"data": "", "ts": 0}

def get_trending_context():
    top = sorted(set(r["username"] for r in all_reels), key=lambda u: sum(x["likes"] for x in all_reels if x["username"]==u), reverse=True)[:8]
    lines = ["=== TOP TRENDING CREATORS (from data) ==="]
    for u in top:
        ur = [r for r in all_reels if r["username"]==u]
        total = sum(r["likes"] for r in ur)
        avg = total // len(ur)
        lines.append(f"  @{u} — {len(ur)} reels, {total:,} total likes, {avg:,} avg")
    lines.append("")
    top_reels = sorted(all_reels, key=lambda r: r["likes"], reverse=True)[:5]
    lines.append("=== TOP REELS OVERALL ===")
    for r in top_reels:
        lines.append(f"  @{r['username']} — {r['likes']:,} likes — {r.get('caption','')[:60]}")
    return "\n".join(lines)

def build_top_reels_summary(username):
    user_reels = [r for r in all_reels if r["username"] == username]
    user_reels.sort(key=lambda x: x["likes"], reverse=True)
    lines = []
    for i, r in enumerate(user_reels[:15]):
        cap = r.get("caption", "")
        cap_str = f" — \"{cap[:60]}...\"" if cap else ""
        lines.append(f"  {i+1}. {r['reel_url']} — {r['likes']:,} likes{cap_str}")
    return "\n".join(lines) if lines else "  (no reels data)"

@app.route("/api/chat", methods=["POST"])
def api_chat():
    body = request.get_json()
    username = body.get("username", "")
    message = body.get("message", "")

    trending_ctx = get_trending_context()

    has_profile = username and username in profiles_cache
    if has_profile:
        prof = profiles_cache[username]
        reel_summary = build_top_reels_summary(username)
        profile_block = f"""
CREATOR: @{prof['username']}
BIO: {prof.get('bio', 'N/A')}
FOLLOWERS: {prof.get('followers', 'N/A')}
POSTS: {prof.get('posts', 'N/A')}

TOP REELS:
{reel_summary}
"""
    else:
        profile_block = ""

    extra_ctx = ""
    if "algorithm" in message.lower() or "boost" in message.lower() or "reach" in message.lower() or "grow" in message.lower():
        extra_ctx = """

When answering algorithm questions: Give specific, actionable Instagram algorithm insights for 2026. Cover:
• Watch time & completion rate (top ranking signal)
• Save/share rate (viral multiplier)
• Hashtag strategy (niche + broad mix, 3-5 max)
• Posting time optimization
• First 3-second hook rules
• Trending audio usage
• Carousel vs video strategies
• Consistency & frequency patterns
• Engagement pod strategies
• How algorithm tests content on small audience first
"""
    if "predict" in message.lower() or "future" in message.lower() or "trend" in message.lower() or "next" in message.lower():
        extra_ctx = """

When answering prediction questions: Be specific with timelines (30/60/90 days). Cover:
• Content format predictions (short vs long form)
• Niche-specific trend forecasts
• Audio/music trend predictions
• Editing style predictions
• Platform feature predictions (Instagram specific)
• What's declining vs rising
• Seasonal content opportunities
"""

    prompt = f"""You are an Instagram growth strategist, trend analyst, and algorithm expert in 2026. You have REAL-TIME trending data from Instagram.

Your capabilities:
1. **Analyze** any creator's content — hooks, format, niche, posting patterns, what drives engagement
2. **Predict** future trends 30-90 days out with specific forecasts
3. **Advise** on Instagram algorithm — exactly how to boost reach, get on explore page, increase watch time
4. **Compare** creators and identify winning patterns

{trending_ctx}
{profile_block}
USER QUESTION: {message}{extra_ctx}

Rules:
- When analyzing a profile's reels, go through EACH reel and identify: hook style, caption pattern, length, audio choice, content category
- After individual analysis, give OVERALL assessment of their content strategy
- Identify top 3 things working for them and top 3 gaps/opportunities
- Be SPECIFIC with numbers, timeframes, and actionable steps
- Reference the trending data above in your analysis
- If asked about algorithm, explain HOW the ranking signals work and HOW to optimize each one
- If predicting trends, give exact timelines (next 30 days, 60 days, 90 days)
- End every response with 1-3 immediately actionable "Do This Today" steps
- Keep response under 1000 words but be thorough
- Use plain text (no markdown formatting)"""

    try:
        resp = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system="You are a world-class Instagram growth strategist in 2026. You have access to live trending data. Give specific, actionable, data-driven answers about Instagram growth, trends, and the algorithm. Be direct. No fluff. Every answer must include actionable steps the user can take immediately.",
            messages=[{"role": "user", "content": prompt}]
        )
        reply = ""
        for block in resp.content:
            if hasattr(block, 'text'):
                reply += block.text
    except Exception as e:
        reply = f"⚠️ Error: {e}"

    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
