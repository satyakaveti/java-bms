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
import db_operations

import os
import urllib.request
from dotenv import load_dotenv
load_dotenv(override=True)

import threading
import ssl

class ProxyManager:
    def __init__(self):
        self.tor_enabled = os.environ.get("TOR_ENABLED", "false").lower() == "true"
        env_proxies = os.environ.get("WEBSHARE_PROXIES", "")
        self.static_proxies = [p.strip() for p in env_proxies.split(",") if p.strip()] if env_proxies else []
        self._last_health_check = 0
        
        if self.tor_enabled:
            print("ProxyManager: Tor proxy enabled (socks5h://127.0.0.1:9050)")
        elif self.static_proxies:
            print(f"ProxyManager: Webshare static proxies enabled ({len(self.static_proxies)} proxies loaded)")
        else:
            print("ProxyManager: Direct requests (No proxy)")

    def check_tor_health(self):
        if not self.tor_enabled:
            return True
        try:
            # Fast endpoint to verify if the Tor network proxy can fetch a simple page within 5s
            res = requests.get(
                "https://icanhazip.com",
                proxies={"http": "socks5h://127.0.0.1:9050", "https": "socks5h://127.0.0.1:9050"},
                timeout=5,
                impersonate="chrome124"
            )
            return res.status_code == 200
        except Exception:
            return False

    def rotate_tor_ip(self):
        if not self.tor_enabled:
            return False
            
        now = time.time()
        # Cooldown: Tor rate-limits NEWNYM to once every 10 seconds.
        # Skip rotation if we already sent a NEWNYM signal in the last 12 seconds.
        if hasattr(self, "_last_rotation_time") and (now - self._last_rotation_time < 12):
            return False
            
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(('127.0.0.1', 9051))
            s.send(b'AUTHENTICATE ""\r\n')
            response = s.recv(1024)
            if b'250' in response:
                s.send(b'SIGNAL NEWNYM\r\n')
                response = s.recv(1024)
                if b'250' in response:
                    print("Tor IP rotated successfully via NEWNYM signal.")
                    self._last_rotation_time = now
                    time.sleep(1.5)
                    return True
            print(f"Tor rotation signal failed: {response}")
        except Exception as e:
            print(f"Failed to connect to Tor ControlPort on port 9051: {e}")
        return False

    def get_proxy(self):
        if self.tor_enabled:
            now = time.time()
            # Verify Tor health if it has been more than 60 seconds since the last check
            if now - self._last_health_check > 60:
                self._last_health_check = now
                if not self.check_tor_health():
                    print("Tor proxy health check failed. Rotating IP before request...")
                    self.rotate_tor_ip()
            return "socks5h://127.0.0.1:9050"
        if self.static_proxies:
            return random.choice(self.static_proxies)
        return None

    def report_failure(self, proxy_str):
        if self.tor_enabled and (proxy_str == "socks5h://127.0.0.1:9050" or proxy_str == "tor"):
            print("Tor proxy request failed. Requesting new Tor identity (IP rotation)...")
            self.rotate_tor_ip()
        elif proxy_str:
            print(f"Proxy request failed for static/webshare proxy: {proxy_str}")

proxy_manager = ProxyManager()

def print_curl_request(method, url, headers=None, json_data=None):
    print(f"{method} - {url}")

def get_random_proxy():
    proxy_str = proxy_manager.get_proxy()
    if not proxy_str:
        return None, None
    
    if proxy_str.startswith("socks5"):
        return "tor", {"http": proxy_str, "https": proxy_str}
    
    parts = proxy_str.split(":")
    if len(parts) == 4:
        # Authenticated Proxy (ip:port:user:pass)
        ip, port, user, pwd = parts
        proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
    elif len(parts) == 2:
        # Free Proxy (ip:port)
        ip, port = parts
        proxy_url = f"http://{ip}:{port}"
    else:
        return None, None
        
    return proxy_str, {"http": proxy_url, "https": proxy_url}

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
    for i in range(retries):
        if i >= retries - 2:
            proxy_str, proxy = None, None
            print(f"    -> [POST] Falling back to direct request (Attempt {i+1}/{retries}): {url}")
        else:
            proxy_str, proxy = get_random_proxy()
            if i == 0:
                print(f"    -> [POST] Calling API: {url} via {proxy}")
            else:
                print(f"    -> [POST] Retrying API (Attempt {i+1}/{retries}): {url} via {proxy}")
        start_time = time.time()
        try:
            res = requests.post(
                url, 
                headers=headers, 
                json=json_data,
                impersonate="chrome124", 
                proxies=proxy,
                timeout=30
            )
            # If successful but took longer than 15s, rotate Tor IP for next requests
            duration = time.time() - start_time
            if duration > 15 and proxy_str in ["tor", "socks5h://127.0.0.1:9050"]:
                print(f"Request took {duration:.2f}s (slow Tor circuit). Rotating IP in background...")
                proxy_manager.rotate_tor_ip()
                
            if res.status_code in [404, 400]:
                return res
            res.raise_for_status()
            return res
        except Exception as e:
            if proxy_str:
                proxy_manager.report_failure(proxy_str)
            if i == retries - 1:
                raise e
            time.sleep(random.uniform(0.5, 1.5))

def get_with_retry(url, headers, retries=5):
    for i in range(retries):
        if i >= retries - 2:
            proxy_str, proxy = None, None
            print(f"    -> [GET] Falling back to direct request (Attempt {i+1}/{retries}): {url}")
        else:
            proxy_str, proxy = get_random_proxy()
            if i == 0:
                print(f"    -> [GET] Calling API: {url} via {proxy}")
            else:
                print(f"    -> [GET] Retrying API (Attempt {i+1}/{retries}): {url} via {proxy}")
        start_time = time.time()
        try:
            res = requests.get(
                url, 
                headers=headers, 
                impersonate="chrome124", 
                proxies=proxy,
                timeout=30,
                allow_redirects=True
            )
            # If successful but took longer than 15s, rotate Tor IP for next requests
            duration = time.time() - start_time
            if duration > 15 and proxy_str in ["tor", "socks5h://127.0.0.1:9050"]:
                print(f"Request took {duration:.2f}s (slow Tor circuit). Rotating IP in background...")
                proxy_manager.rotate_tor_ip()
                
            if res.status_code in [404, 400]:
                return res
            res.raise_for_status()
            return res
        except Exception as e:
            if proxy_str:
                proxy_manager.report_failure(proxy_str)
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
            "city_id": int(city_id) if city_id else 0,
            "user_lng": float(lon) if lon else None,
            "user_lat": float(lat) if lat else None,
            "gps_lng": float(lon) if lon else None,
            "gps_lat": float(lat) if lat else None
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

def fetch_cinemas_direct(city_name):
    slug = city_name.lower().replace(" ", "-")
    url = f"https://www.district.in/movies/cinemas-in-{slug}"
    
    headers = HEADERS_DISTRICT.copy()
    try:
        res = get_with_retry(url, headers=headers)
        if res.status_code == 404:
            return []
            
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        
        theaters = {}
        if script:
            data = json.loads(script.string)
            rails = data.get("props", {}).get("pageProps", {}).get("data", {}).get("serverState", {}).get("EDSResponse", {}).get("rails", [])
            for rail in rails:
                for item in rail.get("items", []):
                    cinema_data = item.get("ItemDetails", {}).get("CinemaData")
                    if cinema_data:
                        tid = str(cinema_data.get("cinema_id"))
                        if tid not in theaters:
                            theaters[tid] = {
                                "theater_id": tid,
                                "theater_name": cinema_data.get("cinema_name"),
                                "lat": cinema_data.get("lat"),
                                "lon": cinema_data.get("lon"),
                                "address": cinema_data.get("address")
                            }
        theaters_list = list(theaters.values())
        # Sort alphabetically
        theaters_list.sort(key=lambda x: x["theater_name"])
        return theaters_list
    except Exception as e:
        print(f"Error fetching cinemas for {city_name}: {e}")
        return []

def get_movies_by_region_district(region_name, language=None):
    regions = fetch_regions_district()
    
    matching_regions = []
    for r in regions:
        if r.get("city_lat") is not None and r.get("city_long") is not None:
            if r.get("city_name", "").lower() == region_name.lower():
                matching_regions.insert(0, r)
            elif r.get("state_name", "").lower() == region_name.lower():
                matching_regions.append(r)
                
    if not matching_regions:
        return {"error": "Region not found or no GPS data available"}
        
    if matching_regions[0].get("city_name", "").lower() != region_name.lower():
        matching_regions.sort(key=lambda x: (not x.get("is_popular_city", False), x.get("city_name")))
        
    region = matching_regions[0]
        
    city_id = region.get("city_id")
    lat = region.get("city_lat")
    lon = region.get("city_long")
    
    movies_data = fetch_movies_by_city_district(city_id, lat, lon)
    
    unique_movies = {}
    for m in movies_data:
        m_id = m.get("movie_id")
        if m_id not in unique_movies:
            langs = m.get("languages", [])
            m_lang = langs[0] if langs else "Unknown"
            
            unique_movies[m_id] = {
                "title": m.get("name"),
                "eventCode": m_id,
                "language": m_lang
            }
            
    movies = list(unique_movies.values())
        
    if language:
        movies = [m for m in movies if m.get("language", "").lower() == language.lower()]
        
    return {"region": region.get("city_name"), "movies": movies}

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
    
    cinema_dict = {}
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    
    for format_id, val in sessions.items():
        arranged = val.get("arrangedSessions", [])
        if not arranged:
            continue
            
        for group in arranged:
            group_data = group.get("data", {})
            cinema_id = group_data.get("id") or group_data.get("name")
            cinema_name = group_data.get("name", "Unknown Theater")
            cinema_sessions = group.get("sessions", [])
            
            if cinema_id not in cinema_dict:
                cinema_dict[cinema_id] = {
                    "theaterId": cinema_id,
                    "theaterName": cinema_name,
                    "capacity": 0,
                    "occupancy": 0,
                    "netCollection": 0,
                    "shows": []
                }
            
            c_entry = cinema_dict[cinema_id]
            
            for session in cinema_sessions:
                show_id = session.get("sid", "Unknown")
                screen_name = session.get("audi", "Unknown Screen")
                show_time_str = session.get("showTime", "Unknown")
                show_time_raw = show_time_str
                if show_time_str != "Unknown":
                    try:
                        st = datetime.datetime.strptime(show_time_str, "%Y-%m-%dT%H:%M")
                        # Convert UTC to IST
                        st = st + datetime.timedelta(hours=5, minutes=30)
                        
                        # Filter out past shows for today
                        if st < now:
                            continue
                        show_time_formatted = st.strftime("%I:%M %p").lstrip("0")
                    except Exception:
                        show_time_formatted = show_time_str
                else:
                    show_time_formatted = show_time_str
                    
                areas = session.get("areas", [])
                
                show_cats = []
                capacity_this_show = 0
                occupancy_this_show = 0
                net_collection_this_show = 0
                
                price_breakdown = {}
                
                for area in areas:
                    max_seats = int(area.get("sTotal", 0))
                    avail_seats = int(area.get("sAvail", 0))
                    price = float(area.get("price", 0))
                    cat_name = area.get("label", "Unknown")
                    status = area.get("seatStatus", "Unknown")
                    
                    booked = max_seats - avail_seats
                    
                    if price not in price_breakdown:
                        price_breakdown[price] = {"capacity": 0, "occupancy": 0}
                    price_breakdown[price]["capacity"] += max_seats
                    price_breakdown[price]["occupancy"] += booked
                    
                    capacity_this_show += max_seats
                    occupancy_this_show += booked
                    net_collection_this_show += (booked * price)
                    
                    c_entry["capacity"] += max_seats
                    c_entry["occupancy"] += booked
                    c_entry["netCollection"] += (booked * price)
                    
                    show_cats.append({
                        "category": cat_name,
                        "price": price,
                        "maxSeats": max_seats,
                        "availSeats": avail_seats,
                        "booked": booked,
                        "status": status,
                        "collection": booked * price
                    })
                    
                c_entry["shows"].append({
                    "showId": show_id,
                    "screenName": screen_name,
                    "showTime": show_time_formatted,
                    "showTimeRaw": show_time_raw,
                    "capacity": capacity_this_show,
                    "occupancy": occupancy_this_show,
                    "netCollection": net_collection_this_show,
                    "categories": show_cats,
                    "priceBreakdown": price_breakdown
                })
                
    theaters = []
    for k, v in cinema_dict.items():
        if not v["shows"]:
            continue
            
        capacity = v["capacity"]
        occupancy = v["occupancy"]
        occ_pct = round((occupancy / capacity * 100), 2) if capacity > 0 else 0.0
        
        v["occupancyPercentage"] = occ_pct
        theaters.append(v)
        
    return theaters

def run_district_scraping_job(job_id, target_movie, jobs_db, target_state=None, target_city=None, preloaded_regions=None, target_movie_id=None, target_movie_slug=None):
    try:
        final_data = {
            "movie": target_movie,
            "states": {}
        }
        
        if preloaded_regions is not None:
            regions = preloaded_regions
            print(f"[{job_id}] Using {len(regions)} preloaded regions (skipping fetch & sync)...")
        else:
            print(f"[{job_id}] Fetching district.in regions...")
            regions = fetch_regions_district()
            
            if target_state:
                regions = [r for r in regions if r.get("state_name", "").lower() == target_state.lower()]
                
            if target_city:
                regions = [r for r in regions if r.get("city_name", "").lower() == target_city.lower()]
                
            # Pre-populate regions in DB to ensure FK constraints and joins work
            print(f"[{job_id}] Syncing {len(regions)} locations to database... (this may take a moment)")
            for i, r in enumerate(regions):
                c_id = r.get("city_id")
                c_name = r.get("city_name")
                s_name = r.get("state_name", "Unknown State")
                if c_id and c_name:
                    print(f"[{job_id}] Syncing Location: {c_name} ({s_name})")
                    db_operations.upsert_location(int(c_id), c_name, s_name)
            print(f"[{job_id}] Finished syncing locations.")
        
        target_entity_id = target_movie_id
        target_movie_slug = target_movie_slug if target_movie_slug else "movie"
        
        if not target_entity_id:
            # Priority sort: put major cities first so we discover the entity_id instantly
            major_cities = ["hyderabad", "bengaluru", "mumbai", "delhi", "chennai", "kolkata", "pune", "ahmedabad", "vijayawada", "visakhapatnam", "kochi", "chandigarh"]
            regions.sort(key=lambda x: 0 if x.get("city_key", "").lower() in major_cities else 1)
            
            print(f"[{job_id}] Attempting to resolve movie ID...")
            resolved_attempts = 0
            for region in regions:
                if target_entity_id: break
                if resolved_attempts >= 5:
                    print(f"[{job_id}] Checked 5 major regions to resolve ID, stopping further searches to avoid rate limits.")
                    break
                
                city_lat = region.get("city_lat")
                city_long = region.get("city_long")
                if city_lat is None or city_long is None:
                    continue
                    
                city_id = region.get("city_id")
                city_name = region.get("city_name")
                resolved_attempts += 1
                try:
                    movies = fetch_movies_by_city_district(int(city_id), city_lat, city_long)
                    for m in movies:
                        if target_movie.lower().replace(" ", "") in m.get("name", "").lower().replace(" ", ""):
                            target_entity_id = m.get("movie_id")
                            target_movie_slug = re.sub(r'[^a-z0-9]+', '-', m.get("name", "").lower()).strip('-')
                            print(f"[{job_id}] Resolved movie '{target_movie}' to ID {target_entity_id} (slug: {target_movie_slug}) in {city_name}.")
                            # Save the location and movie to DB
                            db_operations.upsert_location(city_id, city_name, region.get("state_name", "Unknown State"))
                            db_operations.upsert_movie(str(target_entity_id), target_movie, "Unknown")
                            break
                except Exception as e:
                    print(f"[{job_id}] Error resolving movie {target_movie} in {city_name}: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            print(f"[{job_id}] Using pre-resolved movie ID {target_entity_id} (slug: {target_movie_slug}).")

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
                    
                    city_id = region.get("city_id")
                    for theater in showtimes:
                        theater_id = theater.get("theaterId")
                        if not theater_id:
                            continue
                            
                        theater_name = theater.get("theaterName")
                        print(f"[{job_id}] Syncing Theater: {theater_name} in {city_name}")
                        db_operations.upsert_theater(str(theater_id), city_id, theater_name)
                        
                        for show in theater.get("shows", []):
                            show_id = str(show.get("showId"))
                            screen_name = show.get("screenName")
                            show_time_raw = show.get("showTimeRaw")
                            
                            show_date = None
                            if show_time_raw and show_time_raw != "Unknown":
                                show_date = show_time_raw.split("T")[0]
                                
                            db_operations.upsert_show_and_record_metric(
                                show_id=show_id,
                                theater_id=str(theater_id),
                                movie_id=str(target_entity_id),
                                screen_name=screen_name,
                                show_time=show_time_raw,
                                show_date=show_date,
                                capacity=show.get("capacity", 0),
                                occupancy=show.get("occupancy", 0),
                                net_collection=show.get("netCollection", 0.0),
                                price_breakdown=show.get("priceBreakdown")
                            )
                            
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
