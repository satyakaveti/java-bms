from curl_cffi import requests
from bs4 import BeautifulSoup
import datetime
import traceback
import urllib.parse
import time
import random
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

WEBSHARE_PROXIES = [
    "31.59.20.176:6754:umfreken:t1kcbpmt3lup",
    "31.56.127.193:7684:umfreken:t1kcbpmt3lup",
    # The other 8 proxies from the Webshare pool are explicitly blocked/timed out by Zomato's WAF
]

def print_curl_request(method, url, headers, json_data=None):
    curl_cmd = f"curl --location --request {method} '{url}' \\\n"
    for k, v in headers.items():
        curl_cmd += f"--header '{k}: {v}' \\\n"
    if json_data:
        import json
        curl_cmd += f"--header 'Content-Type: application/json' \\\n"
        curl_cmd += f"--data '{json.dumps(json_data)}'"
    else:
        # Remove the trailing slash and newline if no data
        curl_cmd = curl_cmd.rsplit(' \\', 1)[0]
    print("\n" + "="*50)
    print(f"[{method}] CURL REQUEST:")
    print(curl_cmd)
    print("="*50 + "\n")

def get_random_proxy():
    proxy_str = random.choice(WEBSHARE_PROXIES)
    ip, port, user, pwd = proxy_str.split(":")
    proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
    return {"http": proxy_url, "https": proxy_url}

HEADERS_DISTRICT = {
    'accept': '*/*',
    'accept-language': 'en-GB,en;q=0.9',
    'content-type': 'application/json',
    'origin': 'https://www.district.in',
    'referer': 'https://www.district.in/',
    'sec-ch-ua': '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
    'x-app-type': 'ed_web',
    'x-app-version': '11.11.1',
    'x-client-id': 'district-web',
    'x-device-id': '1212',
    'x-guest-token': '1212',
    'x-is-movies-supported': 'true'
}

def post_with_retry(url, headers, json_data, retries=5):
    print(f"    -> [POST] Calling API: {url}")
    print_curl_request("POST", url, headers, json_data)
    for i in range(retries):
        proxy = get_random_proxy()
        try:
            res = requests.post(
                url, 
                headers=headers, 
                json=json_data,
                impersonate="chrome124", 
                proxies=proxy,
                timeout=8
            )
            if res.status_code in [404, 400]:
                return res
            res.raise_for_status()
            return res
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(random.uniform(0.5, 1.5))

def get_with_retry(url, headers, retries=5):
    print(f"    -> [GET] Calling API: {url}")
    print_curl_request("GET", url, headers)
    for i in range(retries):
        proxy = get_random_proxy()
        try:
            res = requests.get(
                url, 
                headers=headers, 
                impersonate="chrome124", 
                proxies=proxy,
                timeout=8,
                allow_redirects=True
            )
            if res.status_code in [404, 400]:
                return res
            res.raise_for_status()
            return res
        except Exception as e:
            if i == retries - 1:
                raise e
            time.sleep(random.uniform(0.5, 1.5))
            
def fetch_regions_district():
    url = "https://www.district.in/gw/web/get_location_search"
    res = post_with_retry(url, headers=HEADERS_DISTRICT, json_data={})
    data = res.json()
    return data.get("cities", [])

def fetch_movies_by_city_district(city_id, lat, lon):
    url = "https://www.district.in/gw/web/get_discovery_results"
    
    headers = HEADERS_DISTRICT.copy()
    headers["x-city-id"] = str(city_id)
    headers["x-gps-lat"] = str(lat)
    headers["x-gps-lng"] = str(lon)
    headers["x-user-lat"] = str(lat)
    headers["x-user-lng"] = str(lon)
    
    payload = {
        "location": {
            "city_id": city_id,
            "user_lng": lon,
            "user_lat": lat,
            "gps_lng": lon,
            "gps_lat": lat
        },
        "layout_type": "movies_home_v2",
        "request_type": "tab_switch"
    }
    
    res = post_with_retry(url, headers=headers, json_data=payload)
    data = res.json()
    
    movies = []
    rails = data.get("EDSResponse", {}).get("rails", [])
    for rail in rails:
        for item in rail.get("items", []):
            if item.get("entity_type") == "movie":
                movie_data = item.get("ItemDetails", {}).get("MovieData", {})
                if movie_data:
                    movies.append(movie_data)
                    
    return movies

def fetch_showtimes_district(entity_id, movie_slug, city_key):
    url = f"https://www.district.in/movies/{movie_slug}-movie-tickets-in-{city_key}-MV{entity_id}"
    try:
        res = get_with_retry(url, headers=HEADERS_DISTRICT)
    except Exception:
        return []
    
    soup = BeautifulSoup(res.text, 'html.parser')
    script = soup.find("script", id="__NEXT_DATA__")
    
    if not script:
        return []
        
    data = json.loads(script.string)
    sessions = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("movies", {}).get("movieSessions", {})
    
    theaters = []
    
    for _, val in sessions.items():
        arranged = val.get("arrangedSessions", [])
        if not arranged:
            continue
            
        for group in arranged:
            group_data = group.get("data", {})
            cinema_name = group_data.get("name", "Unknown Theater")
            cinema_sessions = group.get("sessions", [])
            
            capacity = 0
            occupancy = 0
            net_collection = 0
            show_list = []
            
            for session in cinema_sessions:
                show_time = session.get("showTime", "Unknown")
                areas = session.get("areas", [])
                
                show_cats = []
                for area in areas:
                    max_seats = int(area.get("sTotal", 0))
                    avail_seats = int(area.get("sAvail", 0))
                    price = float(area.get("price", 0))
                    cat_name = area.get("label", "Unknown")
                    status = area.get("seatStatus", "Unknown")
                    
                    booked = max_seats - avail_seats
                    capacity += max_seats
                    occupancy += booked
                    net_collection += (booked * price)
                    
                    show_cats.append({
                        "category": cat_name,
                        "price": price,
                        "maxSeats": max_seats,
                        "availSeats": avail_seats,
                        "booked": booked,
                        "status": status,
                        "collection": booked * price
                    })
                    
                show_list.append({
                    "showTime": show_time,
                    "categories": show_cats
                })
                
            occ_pct = round((occupancy / capacity * 100), 2) if capacity > 0 else 0.0
            
            theaters.append({
                "theaterName": cinema_name,
                "capacity": capacity,
                "occupancy": occupancy,
                "occupancyPercentage": occ_pct,
                "netCollection": net_collection,
                "shows": show_list
            })
            
    return theaters

def run_district_scraping_job(job_id, target_movie, jobs_db, target_state=None):
    try:
        final_data = {
            "movie": target_movie,
            "states": {}
        }
        
        print(f"[{job_id}] Fetching district.in regions...")
        regions = fetch_regions_district()
        
        if target_state:
            regions = [r for r in regions if r.get("state_name", "").lower() == target_state.lower()]
            
        target_entity_id = None
        target_movie_slug = "movie"
        
        # Priority sort: put major cities first so we discover the entity_id instantly
        major_cities = ["hyderabad", "bengaluru", "mumbai", "delhi", "chennai", "kolkata", "pune", "ahmedabad", "vijayawada", "visakhapatnam", "kochi", "chandigarh"]
        regions.sort(key=lambda x: 0 if x.get("city_key", "").lower() in major_cities else 1)
        
        print(f"[{job_id}] Attempting to resolve movie ID...")
        for region in regions:
            if target_entity_id: break
            city_id = region.get("city_id")
            city_name = region.get("city_name")
            try:
                movies = fetch_movies_by_city_district(int(city_id), region.get("city_lat", 0), region.get("city_long", 0))
                for m in movies:
                    if target_movie.lower().replace(" ", "") in m.get("name", "").lower().replace(" ", ""):
                        target_entity_id = m.get("movie_id")
                        target_movie_slug = re.sub(r'[^a-z0-9]+', '-', m.get("name", "").lower()).strip('-')
                        print(f"[{job_id}] Resolved movie '{target_movie}' to ID {target_entity_id} (slug: {target_movie_slug}) in {city_name}.")
                        break
            except Exception:
                pass
                
        if not target_entity_id:
            jobs_db[job_id]["status"] = "FAILED"
            jobs_db[job_id]["error"] = "Movie could not be found in any major Zomato/District region."
            print(f"[{job_id}] Job failed: Movie not found.")
            return

        print(f"[{job_id}] Processing {len(regions)} regions concurrently...")
        
        def process_region(region):
            region_start = time.time()
            state_name = region.get("state_name", "Unknown State")
            city_name = region.get("city_name")
            
            try:
                showtimes = fetch_showtimes_district(target_entity_id, target_movie_slug, region.get("city_key", ""))
                elapsed = time.time() - region_start
                
                if showtimes:
                    total_theaters = len(showtimes)
                    total_capacity = sum(t.get("capacity", 0) for t in showtimes if isinstance(t.get("capacity"), (int, float)))
                    total_occupancy = sum(t.get("occupancy", 0) for t in showtimes if isinstance(t.get("occupancy"), (int, float)))
                    total_collection = sum(t.get("netCollection", 0) for t in showtimes if isinstance(t.get("netCollection"), (int, float)))
                    print(f"[{job_id}] Finished {city_name} in {elapsed:.2f}s | Theaters: {total_theaters} | Capacity: {total_capacity} | Occupancy: {total_occupancy} | Collection: Rs. {total_collection:.2f}")
                    return (state_name, city_name, showtimes)
                else:
                    print(f"[{job_id}] Finished {city_name} in {elapsed:.2f}s | No showtimes found.")
                    return None
            except Exception as e:
                elapsed = time.time() - region_start
                print(f"[{job_id}] Error fetching showtimes for {city_name} in {elapsed:.2f}s: {e}")
                return None

        # Execute concurrently with 15 workers for speed
        with ThreadPoolExecutor(max_workers=15) as executor:
            future_to_region = {executor.submit(process_region, r): r for r in regions}
            for future in as_completed(future_to_region):
                result = future.result()
                if result:
                    state_name, city_name, showtimes = result
                    if state_name not in final_data["states"]:
                        final_data["states"][state_name] = {"cities": {}}
                    if city_name not in final_data["states"][state_name]["cities"]:
                        final_data["states"][state_name]["cities"][city_name] = []
                    final_data["states"][state_name]["cities"][city_name].extend(showtimes)
                
        jobs_db[job_id]["status"] = "COMPLETED"
        jobs_db[job_id]["data"] = final_data
        print(f"[{job_id}] Job completed successfully.")
        
    except Exception as e:
        jobs_db[job_id]["status"] = "FAILED"
        jobs_db[job_id]["error"] = str(e)
        jobs_db[job_id]["data"] = traceback.format_exc()
        print(f"[{job_id}] Job failed: {str(e)}")
        traceback.print_exc()
