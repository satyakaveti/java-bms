from curl_cffi import requests
import json

HEADERS_BASE = {
    'sec-ch-ua-platform': '"macOS"',
    'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'x-app-code': 'WEB',
    'x-platform-code': 'DESKTOP-WEB'
}

# Try global search
url = "https://in.bookmyshow.com/api/explore/v1/discover/movies-national?cat=MT" # national region?
res = requests.get("https://in.bookmyshow.com/api/explore/v1/search?query=java&type=movies", headers=HEADERS_BASE, impersonate="chrome124")
print("Search Status:", res.status_code)
if res.status_code == 200:
    print(res.text[:1000])

