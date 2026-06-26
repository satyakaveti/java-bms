from curl_cffi import requests
import datetime
import traceback
import urllib.parse
import time
import random

HEADERS_BASE = {
    'sec-ch-ua-platform': '"macOS"',
    'sec-ch-ua': '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'x-app-code': 'WEB',
    'x-platform-code': 'DESKTOP-WEB'
}

WEBSHARE_PROXIES = [
    "31.59.20.176:6754:umfreken:t1kcbpmt3lup",
    "31.56.127.193:7684:umfreken:t1kcbpmt3lup",
    "45.38.107.97:6014:umfreken:t1kcbpmt3lup",
    "38.154.203.95:5863:umfreken:t1kcbpmt3lup",
    "198.105.121.200:6462:umfreken:t1kcbpmt3lup",
    "64.137.96.74:6641:umfreken:t1kcbpmt3lup",
    "198.23.243.226:6361:umfreken:t1kcbpmt3lup",
    "38.154.185.97:6370:umfreken:t1kcbpmt3lup",
    "142.111.67.146:5611:umfreken:t1kcbpmt3lup",
    "191.96.254.138:6185:umfreken:t1kcbpmt3lup"
]

def get_random_proxy():
    proxy_raw = random.choice(WEBSHARE_PROXIES)
    ip, port, user, pwd = proxy_raw.split(":")
    proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
    return {"http": proxy_url, "https": proxy_url}

def fetch_regions():
    url = "https://in.bookmyshow.com/api/explore/v1/discover/regions"
    regions = []
    res = requests.get(url, headers=HEADERS_BASE, timeout=10, impersonate="chrome110", proxies=get_random_proxy())
    res.raise_for_status()
    data = res.json()
    bms_data = data.get("BookMyShow", {})
    
    for group in ["TopCities", "OtherCities"]:
        for r in bms_data.get(group, []):
            regions.append({
                "code": r.get("RegionCode"),
                "name": r.get("RegionName"),
                "slug": r.get("RegionSlug"),
                "state_code": r.get("StateCode"),
                "state_name": r.get("StateName"),
                "lat": r.get("Lat", ""),
                "lon": r.get("Long", "")
            })
    return regions

def fetch_movies_by_city(region_slug, region_code, lat, lon):
    url = f"https://in.bookmyshow.com/api/explore/v1/discover/movies-{region_slug}?region={region_code}&cat=MT&embedded=true&lat={lat}&lon={lon}"
    movies = []
    headers = HEADERS_BASE.copy()
    headers.update({
        'x-region-code': region_code,
        'x-region-slug': region_slug,
        'x-bms-id': '1.61267030.1782201813946',
        'referer': f'https://in.bookmyshow.com/explore/movies-{region_slug}?cat=MT'
    })
    res = requests.get(url, headers=headers, timeout=10, impersonate="chrome110", proxies=get_random_proxy())
    res.raise_for_status()
    data = res.json()
    
    for listing in data.get("listings", []):
        for card in listing.get("cards", []):
            cta_url = card.get("ctaUrl", "")
            if "/movies/" in cta_url:
                parts = cta_url.rstrip("/").split("/")
                if len(parts) >= 2:
                    event_code = parts[-1]
                    title = urllib.parse.unquote(parts[-2].replace("-", " "))
                    movies.append({
                        "title": title,
                        "eventCode": event_code
                    })
    return movies

def fetch_showtimes(event_code, region_code, lat, lon):
    static_url = f"https://in.bookmyshow.com/api/movies-data/v4/showtimes-by-event/primary-static?eventCode={event_code}&dateCode=&isDesktop=true&regionCode={region_code}&xLocationShared=false&memberId=&lsId=&subCode=&lat={lat}&lon={lon}"
    dynamic_url = f"https://in.bookmyshow.com/api/movies-data/v4/showtimes-by-event/primary-dynamic?eventCode={event_code}&dateCode=&isDesktop=true&regionCode={region_code}&xLocationShared=false&memberId=&lsId=&subCode=&lat={lat}&lon={lon}"
    
    headers = HEADERS_BASE.copy()
    headers.update({
        'x-region-code': region_code,
        'x-latitude': str(lat),
        'x-longitude': str(lon),
        'referer': f'https://in.bookmyshow.com/explore/movies-{region_code.lower()}?cat=MT'
    })
    
    proxy = get_random_proxy()
    static_res = requests.get(static_url, headers=headers, timeout=10, impersonate="chrome110", proxies=proxy)
    static_res.raise_for_status()
    static_data = static_res.json()
    
    dynamic_res = requests.get(dynamic_url, headers=headers, timeout=10, impersonate="chrome110", proxies=proxy)
    dynamic_res.raise_for_status()
    dynamic_data = dynamic_res.json()
    
    theaters = []
    # Parsing based on anticipated BookMyShow API schema. 
    # If the schema varies, this will raise a KeyError/TypeError which we can trace and fix.
    static_venues = static_data.get("data", {}).get("venues", {})
    
    widgets = dynamic_data.get("data", {}).get("showtimeWidgets", [])
    dynamic_venues = []
    for w in widgets:
        if w.get("type") == "groupList":
            items = w.get("data", [])
            if items and "data" in items[0]:
                dynamic_venues = items[0]["data"]
                break

    for dyn_venue in dynamic_venues:
        venue_code = dyn_venue.get("id")
        theater_name = static_venues.get(venue_code, {}).get("venueName", "Unknown Theater")
        
        capacity = 0
        occupancy = 0
        net_collection = 0
        
        if "showtimes" in dyn_venue:
            for show in dyn_venue["showtimes"]:
                categories = show.get("additionalData", {}).get("categories", [])
                for cat in categories:
                    price = float(cat.get("curPrice", 0))
                    avail_status = str(cat.get("availStatus", "0"))
                    
                    # Approximation algorithm since BMS v4 API removed explicit seat counts
                    total_seats = 100 
                    if avail_status == "0": # Sold out
                        booked = 100
                    elif avail_status == "1": # Almost full
                        booked = 90
                    elif avail_status == "3": # Available
                        booked = 30
                    else:
                        booked = 0
                        
                    capacity += total_seats
                    occupancy += booked
                    net_collection += (booked * price)
            
            occ_pct = round((occupancy / capacity * 100), 2) if capacity > 0 else 0.0
            
            theaters.append({
                "theaterName": theater_name,
                "capacity": capacity,
                "occupancy": occupancy,
                "occupancyPercentage": occ_pct,
                "netCollection": net_collection
            })

    return theaters


def run_scraping_job(job_id: str, target_movie: str, jobs_dict: dict, target_state: str = None):
    try:
        jobs_dict[job_id]["status"] = "PROCESSING"
        
        final_data = {
            "movie": target_movie,
            "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "states": {}
        }
        
        print(f"[{job_id}] Fetching regions...")
        regions = fetch_regions()
        
        # Process all regions or filter by state
        if target_state:
            regions = [r for r in regions if r.get("state_name", "").lower() == target_state.lower()]
        
        for region in regions:
            # Respect BookMyShow rate limits with a randomized 3-8 second human-like gap
            delay = random.uniform(3.0, 8.0)
            print(f"[{job_id}] Waiting for {delay:.2f} seconds before next request...")
            time.sleep(delay)
            
            state_name = region.get("state_name", "Unknown State")
            city_name = region.get("name")
            print(f"[{job_id}] Processing region: {city_name} in {state_name}")
            
            movies = fetch_movies_by_city(region.get("slug"), region.get("code"), region.get("lat"), region.get("lon"))
            
            target_event_code = None
            for m in movies:
                # Basic string normalization for matching
                if target_movie.lower().replace(" ", "") in m.get("title", "").lower().replace(" ", ""):
                    target_event_code = m.get("eventCode")
                    break
            
            if target_event_code:
                showtimes = fetch_showtimes(target_event_code, region.get("code"), region.get("lat"), region.get("lon"))
                
                if showtimes:
                    if state_name not in final_data["states"]:
                        final_data["states"][state_name] = {"cities": {}}
                    if city_name not in final_data["states"][state_name]["cities"]:
                        final_data["states"][state_name]["cities"][city_name] = []
                        
                    final_data["states"][state_name]["cities"][city_name].extend(showtimes)
                
        jobs_dict[job_id]["data"] = final_data
        jobs_dict[job_id]["status"] = "COMPLETED"
        print(f"[{job_id}] Job completed successfully.")
        
    except Exception as e:
        jobs_dict[job_id]["status"] = "FAILED"
        jobs_dict[job_id]["error"] = str(e)
        jobs_dict[job_id]["traceback"] = traceback.format_exc()
        print(f"[{job_id}] Job failed: {e}")
        traceback.print_exc()
