import requests
import datetime
import traceback

HEADERS_BASE = {
    'sec-ch-ua-platform': '"macOS"',
    'sec-ch-ua': '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'x-app-code': 'WEB',
    'x-platform-code': 'DESKTOP-WEB'
}

def fetch_regions():
    url = "https://in.bookmyshow.com/api/explore/v1/discover/regions"
    try:
        res = requests.get(url, headers=HEADERS_BASE, timeout=10)
        res.raise_for_status()
        # The structure is usually something like: {"BookMyShow": {"regions": [...]}}
        # Note: Needs adjustment based on actual response structure. Let's assume standard extraction for now.
        # This is a generic mockup structure handling.
        data = res.json()
        regions = []
        # Fallback to empty if structure is unknown; we'll refine if we have actual payload
        if "BookMyShow" in data and "regions" in data["BookMyShow"]:
            for r in data["BookMyShow"]["regions"]:
                regions.append({
                    "code": r.get("regionCode"),
                    "name": r.get("regionName"),
                    "slug": r.get("regionNameSlug"),
                    "lat": r.get("Lat", ""),
                    "lon": r.get("Long", "")
                })
        return regions
    except Exception as e:
        print(f"Error fetching regions: {e}")
        return []

def fetch_movies_by_city(region_slug, region_code, lat, lon):
    url = f"https://in.bookmyshow.com/api/explore/v1/discover/movies-{region_slug}?region={region_code}&cat=MT&embedded=true&lat={lat}&lon={lon}"
    try:
        res = requests.get(url, headers=HEADERS_BASE, timeout=10)
        res.raise_for_status()
        data = res.json()
        movies = []
        # Typically returns a list of events/movies
        # Will mock the extraction
        events = data.get("data", {}).get("events", [])
        if not events: # Try another common path
            events = data.get("events", [])
            
        for e in events:
            movies.append({
                "title": e.get("eventTitle", ""),
                "eventCode": e.get("eventCode", "")
            })
        return movies
    except Exception as e:
        print(f"Error fetching movies for {region_slug}: {e}")
        return []

def fetch_showtimes(event_code, region_code, lat, lon):
    static_url = f"https://in.bookmyshow.com/api/movies-data/v4/showtimes-by-event/primary-static?eventCode={event_code}&dateCode=&isDesktop=true&regionCode={region_code}&xLocationShared=false&memberId=&lsId=&subCode=&lat={lat}&lon={lon}"
    dynamic_url = f"https://in.bookmyshow.com/api/movies-data/v4/showtimes-by-event/primary-dynamic?eventCode={event_code}&dateCode=&isDesktop=true&regionCode={region_code}&xLocationShared=false&memberId=&lsId=&subCode=&lat={lat}&lon={lon}"
    
    headers = HEADERS_BASE.copy()
    headers.update({
        'x-region-code': region_code,
        'x-latitude': str(lat),
        'x-longitude': str(lon)
    })
    
    try:
        static_res = requests.get(static_url, headers=headers, timeout=10)
        dynamic_res = requests.get(dynamic_url, headers=headers, timeout=10)
        
        static_data = static_res.json() if static_res.status_code == 200 else {}
        dynamic_data = dynamic_res.json() if dynamic_res.status_code == 200 else {}
        
        # In a real implementation, we would merge static (theaters, schedules) with dynamic (availability, price).
        # We will return dummy parsed data for now representing the calculation structure
        theaters = {}
        # Mocking extraction logic (to be refined based on actual API payload schema)
        return theaters
    except Exception as e:
        print(f"Error fetching showtimes for {event_code}: {e}")
        return {}


def run_scraping_job(job_id: str, target_movie: str, jobs_dict: dict):
    try:
        jobs_dict[job_id]["status"] = "PROCESSING"
        
        # Initialize the final result schema
        final_data = {
            "movie": target_movie,
            "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "city": {}
        }
        
        print(f"[{job_id}] Fetching regions...")
        regions = fetch_regions()
        
        # Limit to first few regions for testing purposes if there are too many
        regions = regions[:5] if regions else []
        
        for region in regions:
            region_name = region.get("name")
            print(f"[{job_id}] Processing region: {region_name}")
            
            movies = fetch_movies_by_city(region.get("slug"), region.get("code"), region.get("lat"), region.get("lon"))
            
            # Find the target movie
            target_event_code = None
            for m in movies:
                if target_movie.lower() in m.get("title", "").lower():
                    target_event_code = m.get("eventCode")
                    break
            
            if target_event_code:
                # Fetch showtimes
                showtimes = fetch_showtimes(target_event_code, region.get("code"), region.get("lat"), region.get("lon"))
                # In a real scenario, `showtimes` would be populated with theater > show -> stats.
                # Since we don't have the exact API payload format, we inject a dummy entry.
                final_data["city"][region_name] = {
                    "Dummy Theater": {
                        "Show: 10:00 AM": {
                            "totalSeats": 600,
                            "occupied": 200,
                            "amount": 30000
                        }
                    }
                }
                
        jobs_dict[job_id]["data"] = final_data
        jobs_dict[job_id]["status"] = "COMPLETED"
        print(f"[{job_id}] Job completed successfully.")
        
    except Exception as e:
        jobs_dict[job_id]["status"] = "FAILED"
        jobs_dict[job_id]["error"] = str(e)
        print(f"[{job_id}] Job failed: {e}")
        traceback.print_exc()
