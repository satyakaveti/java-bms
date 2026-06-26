from curl_cffi import requests
import json

HEADERS_BASE = {
    'sec-ch-ua-platform': '"macOS"',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'x-app-code': 'WEB',
    'x-platform-code': 'DESKTOP-WEB',
    'x-region-code': 'HYD',
    'referer': 'https://in.bookmyshow.com/explore/movies-hyderabad?cat=MT'
}

proxy_url = "http://umfreken:t1kcbpmt3lup@31.59.20.176:6754"
proxy = {"http": proxy_url, "https": proxy_url}

url = "https://in.bookmyshow.com/api/explore/v1/discover/movies-hyderabad?region=HYD&cat=MT&embedded=true"
res = requests.get(url, headers=HEADERS_BASE, impersonate="chrome124")

if res.status_code == 200:
    data = res.json()
    print("Found listings", len(data.get("listings", [])))
    for listing in data.get("listings", []):
        for card in listing.get("cards", []):
            cta = card.get("ctaUrl", "")
            if "/movies/" in cta:
                print("Found cta:", cta)
                event_code = cta.split("/")[-1]
                
                # Fetch showtimes for this event
                dyn_url = f"https://in.bookmyshow.com/api/movies-data/v4/showtimes-by-event/primary-dynamic?eventCode={event_code}&dateCode=&isDesktop=true&regionCode=HYD&xLocationShared=false&memberId=&lsId=&subCode="
                dyn_res = requests.get(dyn_url, headers=HEADERS_BASE, impersonate="chrome124", proxies=proxy)
                if dyn_res.status_code == 200:
                    with open("bms_dump_active.json", "w") as f:
                        f.write(dyn_res.text)
                    print("Dumped", event_code)
                    exit(0)
