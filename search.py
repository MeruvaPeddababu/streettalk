import requests
from bs4 import BeautifulSoup
import csv
import re
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SEARCH_QUERIES = [
    "football",
    "football player",
    "footballer",
    "soccer",
    "soccer player",
    "cricket",
    "cricketer name",
    "cricket player",
    "cricket news",
    "basketball",
    "nba",
    "tennis",
    "tennis player",
    "badminton",
    "volleyball",
    "olympics",
    "sports",
    "athlete",
    "runner",
    "cyclist",
    "fitness athlete",
    "sports news",
    "sports highlights",
    "fifa",
    "uefa",
    "premier league",
    "ipl",
    "champions league",
    "formula 1",
    "motogp",
    "ufc",
    "wwe"
]

USERNAME_REGEX = re.compile(
    r"instagram\.com/([A-Za-z0-9._]+)/?"
)


def search_ddg(query):
    url = "https://html.duckduckgo.com/html/"

    response = requests.post(
        url,
        headers=HEADERS,
        data={
            "q": f"site:instagram.com {query}"
        },
        timeout=30
    )

    soup = BeautifulSoup(response.text, "html.parser")

    usernames = []

    for a in soup.find_all("a", href=True):

        href = a["href"]

        m = USERNAME_REGEX.search(href)

        if m:
            username = m.group(1)

            if username not in [
                "p",
                "reel",
                "explore",
                "stories"
            ]:
                usernames.append(username)

    return usernames


all_users = set()

for q in SEARCH_QUERIES:

    print("Searching:", q)

    try:
        users = search_ddg(q)

        all_users.update(users)

        print("Found", len(users))

    except Exception as e:
        print(e)

    time.sleep(2)


rows = []

for user in sorted(all_users):
    rows.append({
        "username": user,
        "profile_url": f"https://www.instagram.com/{user}/"
    })

with open(
    "instagram_profiles.csv",
    "w",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "username",
            "profile_url"
        ]
    )

    writer.writeheader()
    writer.writerows(rows)

print("Total unique profiles:", len(rows))