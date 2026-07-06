from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import uvicorn
from typing import Dict, Any, Optional, List
import asyncio
import datetime
import traceback
from database import get_connection
import db_operations
from contextlib import asynccontextmanager

try:
    from district_scraper import run_district_scraping_job, fetch_regions_district, get_movies_by_region_district, fetch_cinemas_direct
except ImportError:
    run_district_scraping_job = None
    fetch_regions_district = None
    get_movies_by_region_district = None
    get_movies_by_region_district = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    import database
    import asyncio
    
    database.init_db()
    asyncio.create_task(cron_scheduler())
    
    db_mode = getattr(database, 'DB_MODE', 'LOCAL')
    if db_mode == "PROD":
        print(f"Connected DB: POSTGRES PROD (DB_MODE: {db_mode})")
    else:
        print(f"Connected DB: SQLite Local (DB_MODE: {db_mode})")
    
    # Start the periodic background scheduler (Disabled per user request)
    # asyncio.create_task(run_scheduler())
    yield

app = FastAPI(
    title="District Ticketing Analyzer",
    docs_url="/bms-district-api-docs",
    redoc_url="/bms-district-api-redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tollybo.com",
        "http://129.159.225.102:8282",
        "http://129.159.225.102"
    ],
    allow_origin_regex=r"https://.*\.tollybo\.com|http://localhost:\d+|http://127\.0\.0\.1:\d+|http://129\.159\.225\.102:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def run_scheduler():
    while True:
        try:
            print("[Scheduler] Starting periodic background job...")
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT movie_id, title FROM movies")
            movies = cursor.fetchall()
            conn.close()
            
            for m in movies:
                movie_title = m['title']
                movie_id = m['movie_id']
                print(f"[Scheduler] Scraping updates for movie {movie_title} (ID: {movie_id})")
                job_id = f"scheduler-{movie_id}-{int(datetime.datetime.utcnow().timestamp())}"
                jobs_db[job_id] = {"status": "PROCESSING", "data": None, "error": None}
                
                if run_district_scraping_job:
                    # this will run and save to DB
                    run_district_scraping_job(job_id, movie_title, jobs_db)
            
            # Finalize past shows
            finalized_count = db_operations.finalize_past_or_missing_shows(None)
            print(f"[Scheduler] Finalized {finalized_count} shows.")
            
            now_ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
            if now_ist.hour == 23 and now_ist.minute >= 30:
                eod_count = db_operations.finalize_end_of_day(now_ist.strftime("%Y-%m-%d"))
                print(f"[Scheduler] End of Day Process finalized {eod_count} shows.")
                
            print("[Scheduler] Sleeping for 30 minutes...")
        except Exception as e:
            print(f"[Scheduler] Error: {e}")
            traceback.print_exc()
            
        await asyncio.sleep(30 * 60)

# In-memory global dictionary to store job statuses and results
# Format: { "job_id": { "status": "PROCESSING", "data": {}, "error": "" } }
jobs_db: Dict[str, Dict[str, Any]] = {}

class AnalysisRequest(BaseModel):
    movieName: str

class AnalysisResponse(BaseModel):
    jobId: str
    status: str
    message: str = None

@app.post("/api/v1/district/analyze/{region_name}", response_model=AnalysisResponse, status_code=202)
async def analyze_movie_by_region(region_name: str, request: AnalysisRequest, background_tasks: BackgroundTasks):
    movie_name = request.movieName.strip()
    if not movie_name:
        raise HTTPException(status_code=400, detail="movieName is required")

    job_id = str(uuid.uuid4())
    jobs_db[job_id] = {
        "status": "PROCESSING",
        "data": None,
        "error": None
    }
    
    if run_district_scraping_job:
        background_tasks.add_task(run_district_scraping_job, job_id, movie_name, jobs_db, region_name)
    else:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    return {
        "jobId": job_id,
        "status": "PROCESSING",
        "message": f"Scraping job initiated for region {region_name}. Check status using the jobId."
    }

@app.post("/api/v1/district/analyze/{region_name}/{city_name}", response_model=AnalysisResponse, status_code=202)
async def analyze_movie_by_city(region_name: str, city_name: str, request: AnalysisRequest, background_tasks: BackgroundTasks):
    movie_name = request.movieName.strip()
    if not movie_name:
        raise HTTPException(status_code=400, detail="movieName is required")

    job_id = str(uuid.uuid4())
    jobs_db[job_id] = {
        "status": "PROCESSING",
        "data": None,
        "error": None
    }
    
    if run_district_scraping_job:
        background_tasks.add_task(run_district_scraping_job, job_id, movie_name, jobs_db, region_name, city_name)
    else:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    return {
        "jobId": job_id,
        "status": "PROCESSING",
        "message": f"Scraping job initiated for {city_name}, {region_name}. Check status using the jobId."
    }

@app.get("/api/v1/district/movies/{region_name}")
async def get_movies(region_name: str, language: str = None):
    if not get_movies_by_region_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
    try:
        return get_movies_by_region_district(region_name, language)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/district/status/{jobId}")
async def get_analysis_status(jobId: str):
    job = jobs_db.get(jobId)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found")
        
    response = {
        "jobId": jobId,
        "status": job["status"]
    }
    
    if job["status"] == "COMPLETED":
        response["data"] = job["data"]
    elif job["status"] == "FAILED":
        response["error"] = job["error"]
        
    return response

@app.get("/api/v1/district/regions")
def get_regions():
    if not fetch_regions_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    regions = fetch_regions_district()
    result = {}
    for r in regions:
        state = r.get("state_name") or "Unknown State"
        city = r.get("city_name") or "Unknown City"
        
        if state not in result:
            result[state] = {}
            
        result[state][city] = {
            "city_id": r.get("city_id"),
            "city_key": r.get("city_key"),
            "lat": r.get("lat"),
            "lon": r.get("lon")
        }
    return result

@app.get("/api/v1/district/regions/{region}")
def get_regions_by_name(region: str):
    if not fetch_regions_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    regions = fetch_regions_district()
    result = {}
    for r in regions:
        state = r.get("state_name") or "Unknown State"
        city = r.get("city_name") or "Unknown City"
        
        if state.lower() == region.lower():
            if state not in result:
                result[state] = {}
            result[state][city] = {
                "city_id": r.get("city_id"),
                "city_key": r.get("city_key"),
                "lat": r.get("lat"),
                "lon": r.get("lon")
            }
    if not result:
        raise HTTPException(status_code=404, detail=f"Region/State '{region}' not found")
    return result

@app.get("/api/v1/district/theaters/{state_name}")
def get_theaters_by_state(state_name: str):
    if not fetch_regions_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    regions = fetch_regions_district()
    state_cities = [r for r in regions if (r.get("state_name") or "").lower() == state_name.lower()]
    
    if not state_cities:
        raise HTTPException(status_code=404, detail=f"No cities found in state '{state_name}'")
        
    all_theaters = []
    
    # Process cities concurrently
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def process_city(city_data):
        c_name = city_data.get("city_name")
        if c_name:
            theaters = fetch_cinemas_direct(c_name)
            for t in theaters:
                t["city_name"] = c_name
                t["state_name"] = city_data.get("state_name")
            return theaters
        return []

    # Using max_workers=5 so we don't completely spam the district APIs for an entire state
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_city = {executor.submit(process_city, c): c for c in state_cities}
        for future in as_completed(future_to_city):
            try:
                result = future.result()
                if result:
                    city_data = future_to_city[future]
                    city_id = city_data.get("city_id")
                    for t in result:
                        tid = t.get("theater_id")
                        if tid and city_id:
                            db_operations.upsert_theater(
                                theater_id=tid,
                                city_id=int(city_id),
                                name=t.get("theater_name"),
                                lat=t.get("lat"),
                                lon=t.get("lon"),
                                address=t.get("address")
                            )
                    all_theaters.extend(result)
            except Exception as e:
                pass
                
    all_theaters.sort(key=lambda x: (x.get("city_name", ""), x.get("theater_name", "")))
    return all_theaters

@app.get("/api/v1/district/theaters/city/{city_name}")
def get_theaters_by_city(city_name: str):
    theaters = fetch_cinemas_direct(city_name)
    
    if not theaters:
        raise HTTPException(status_code=404, detail=f"No theaters found for city '{city_name}'")
        
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city_id FROM locations WHERE LOWER(city_name) = %s", (city_name.lower(),))
    row = cursor.fetchone()
    conn.close()
    
    city_id = row['city_id'] if row else None
        
    for t in theaters:
        t["city_name"] = city_name
        tid = t.get("theater_id")
        if tid and city_id:
            db_operations.upsert_theater(
                theater_id=tid,
                city_id=city_id,
                name=t.get("theater_name"),
                lat=t.get("lat"),
                lon=t.get("lon"),
                address=t.get("address")
            )
        
    return theaters

class SyncRequest(BaseModel):
    region: Optional[str] = None

class FullRunRequest(BaseModel):
    regions: List[str]
    language: str
    movieName: Optional[str] = None

def execute_full_run_job(req: FullRunRequest):
    try:
        from district_scraper import fetch_regions_district, run_district_scraping_job, get_movies_by_region_district
        import db_operations
        
        print(f"[Full Run] Initializing and syncing locations from district...")
        all_regions = fetch_regions_district()
        
        # Filter regions down to just the ones requested across all states
        target_regions_map = {}
        for state in req.regions:
            state_regions = [r for r in all_regions if r.get("state_name", "").lower() == state.lower()]
            target_regions_map[state] = state_regions
            
            print(f"[Full Run] Syncing {len(state_regions)} locations for {state} to database...")
            for r in state_regions:
                c_id = r.get("city_id")
                c_name = r.get("city_name")
                s_name = r.get("state_name", "Unknown State")
                if c_id and c_name:
                    print(f"[Full Run] Syncing Location: {c_name} ({s_name})")
                    db_operations.upsert_location(int(c_id), c_name, s_name)
        
        print(f"[Full Run] Getting active movies in Hyderabad for language: {req.language}")
        movies_resp = get_movies_by_region_district("Hyderabad", language=req.language)
        movies = movies_resp.get("movies", []) if isinstance(movies_resp, dict) else []
        print(f"[Full Run] Found {len(movies)} movies.")
        
        for m in movies:
            movie_name = m.get("title")
            if not movie_name: continue
            
            # If a specific movieName is requested, skip all others
            if req.movieName and req.movieName.lower().replace(" ", "") not in movie_name.lower().replace(" ", ""):
                continue
            
            print(f"\n[Full Run] Processing movie: {movie_name}")
            for state in req.regions:
                job_id = str(uuid.uuid4())
                print(f"[Full Run] Starting scraping job {job_id} for '{movie_name}' in state '{state}'")
                jobs_db[job_id] = {"status": "PROCESSING", "data": None, "error": None}
                
                preloaded = target_regions_map.get(state, [])
                run_district_scraping_job(job_id, movie_name, jobs_db, target_state=state, preloaded_regions=preloaded)
                
        print("[Full Run] Completed successfully.")
    except Exception as e:
        print(f"[Full Run] Error: {e}")
        import traceback
        traceback.print_exc()

@app.post("/api/v1/district/full-run", status_code=202)
def full_run_sync(req: FullRunRequest, background_tasks: BackgroundTasks):
    from district_scraper import fetch_regions_district
    if not fetch_regions_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    background_tasks.add_task(execute_full_run_job, req)
    return {"status": "ACCEPTED", "message": f"Full run started in background for {req.regions} and language {req.language}"}

async def cron_scheduler():
    import asyncio
    import os
    
    while True:
        try:
            enabled = os.environ.get("CRON_ENABLED", "false").lower() == "true"
            if enabled:
                print("\n[Scheduler] CRON_ENABLED is true. Triggering scheduled full run...")
                regions_env = os.environ.get("CRON_REGIONS", "")
                regions = [r.strip() for r in regions_env.split(",")] if regions_env else []
                lang = os.environ.get("CRON_LANGUAGE", "Telugu")
                movie = os.environ.get("CRON_MOVIENAME", "")
                if not movie: 
                    movie = None
                
                req = FullRunRequest(regions=regions, language=lang, movieName=movie)
                
                loop = asyncio.get_running_loop()
                # Run the blocking function in a separate thread
                await loop.run_in_executor(None, execute_full_run_job, req)
                
        except Exception as e:
            print(f"[Scheduler] Error in cron loop: {e}")
            import traceback
            traceback.print_exc()
            
        interval = int(os.environ.get("CRON_INTERVAL_MINUTES", "20"))
        # Wait before next iteration
        await asyncio.sleep(interval * 60)

@app.post("/api/v1/district/add-update-locations-theaters", status_code=202)
def add_update_locations_theaters(background_tasks: BackgroundTasks, sync_req: SyncRequest = None):
    if not fetch_regions_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    def sync_job():
        try:
            regions = fetch_regions_district()
            
            # If region is provided, filter the regions list
            if sync_req and sync_req.region:
                target_region = sync_req.region.lower()
                regions = [r for r in regions if (r.get("state_name") or "").lower() == target_region]
                
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def process_region_sync(r):
                c_id = r.get("city_id")
                if not c_id: return None
                c_name = r.get("city_name")
                s_name = r.get("state_name", "Unknown State")
                c_key = r.get("city_key")
                
                try:
                    db_operations.upsert_location(int(c_id), c_name, s_name, c_key)
                    
                    # fetch_cinemas_direct does lower().replace(" ", "-")
                    # To ensure it uses the exact correct slug provided by the API, we pass c_key (e.g. 'abu-dhabi') 
                    # which will just remain 'abu-dhabi' after the replace logic in fetch_cinemas_direct.
                    theaters = fetch_cinemas_direct(c_key if c_key else c_name)
                    
                    print(f"city : {c_name}, total thaters: {len(theaters)}, theaters list:")
                    for idx, t in enumerate(theaters, 1):
                        print(f"{idx}- {t.get('theater_name')}")
                        
                    for t in theaters:
                        tid = t.get("theater_id")
                        if tid:
                            action = db_operations.upsert_theater(
                                theater_id=tid, 
                                city_id=int(c_id), 
                                name=t.get("theater_name"), 
                                lat=t.get("lat"), 
                                lon=t.get("lon"), 
                                address=t.get("address")
                            )
                            t['db_action'] = action
                    return (c_name, theaters, c_id)
                except Exception as ex:
                    print(f"Error syncing region {c_name}: {ex}")
                    return None
            
            all_processed_theaters = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(process_region_sync, r) for r in regions]
                for future in as_completed(futures):
                    res = future.result()
                    if res:
                        all_processed_theaters.append(res)
            
            # Print final summary table
            print("\n" + "="*120)
            print("FINAL SUMMARY: ALL THEATERS PROCESSED")
            print("="*120)
            print(f"{'S.No':<6} | {'DB_ACTION':<17} | {'City':<25} | {'Theater Name'}")
            print("-" * 120)
            
            sno = 1
            all_processed_theaters.sort(key=lambda x: x[0])  # Sort by city name
            for city_name, theaters_list, c_id in all_processed_theaters:
                theaters_list.sort(key=lambda x: x.get('theater_name', '')) # Sort by theater name
                for t in theaters_list:
                    t_name = t.get('theater_name', 'Unknown')
                    db_action = t.get('db_action', 'UNKNOWN')
                    print(f"{sno:<6} | {db_action:<17} | {city_name:<25} | {t_name}")
                    sno += 1
            print("="*120 + "\n")
            
            # Print City-wise count table
            print("\n" + "="*70)
            print("CITY-WISE THEATER COUNT")
            print("="*70)
            print(f"{'City ID':<10} | {'City':<25} | {'Count':<10}")
            print("-" * 70)
            
            total_theaters = 0
            for city_name, theaters_list, c_id in all_processed_theaters:
                count = len(theaters_list)
                total_theaters += count
                print(f"{c_id:<10} | {city_name:<25} | {count:<10}")
            print("-" * 70)
            print(f"{'':<10} | {'TOTAL':<25} | {total_theaters:<10}")
            print("="*70 + "\n")
                    
        except Exception as e:
            print(f"Error in overall sync job setup: {e}")
            
    background_tasks.add_task(sync_job)
    
    msg = "Master data sync for locations and theaters initiated in the background."
    if sync_req and sync_req.region:
        msg = f"Master data sync for region '{sync_req.region}' initiated in the background."
        
    return {"message": msg}

# --- Analytics APIs ---

@app.get("/api/v1/analytics/movies/{movie_id}/summary")
def get_movie_summary(movie_id: str, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT l.state_name, l.city_name, 
               count(s.show_id) as no_of_shows,
               sum(m.net_collection) as sum_total_collection,
               ROUND(CAST(sum(m.net_collection) / 10000000.0 AS NUMERIC), 3) || ' CR' as sum_total_collection_in_cr,
               sum(m.capacity) as sum_total_seats,
               sum(m.occupancy) as sum_total_occupied,
               ROUND(CAST(sum(CAST(m.occupancy AS FLOAT)) * 100.0 / NULLIF(sum(m.capacity), 0) AS NUMERIC), 2) as occpency_avg_percentile
        FROM shows s
        JOIN theaters t ON s.theater_id = t.theater_id
        JOIN locations l ON t.city_id = l.city_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE s.movie_id = %s
    '''
    params = [movie_id]
    if date:
        query += ' AND s.show_date = %s'
        params.append(date)
    query += ' GROUP BY l.state_name, l.city_name'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    state_summary = {}
    for row in rows:
        state = row['state_name']
        if state not in state_summary:
            state_summary[state] = {
                "cities": [],
                "no_of_shows": 0,
                "sum_total_collection": 0,
                "sum_total_seats": 0,
                "sum_total_occupied": 0
            }
            
        # Add to cities list
        state_summary[state]["cities"].append({
            "city_name": row['city_name'],
            "no_of_shows": row['no_of_shows'],
            "collection": row['sum_total_collection'],
            "seats": row['sum_total_seats'],
            "occupied": row['sum_total_occupied'],
            "occpency_percentile": row['occpency_avg_percentile']
        })
        
        # Accumulate state totals
        state_summary[state]["no_of_shows"] += row['no_of_shows']
        state_summary[state]["sum_total_collection"] += row['sum_total_collection']
        state_summary[state]["sum_total_seats"] += row['sum_total_seats']
        state_summary[state]["sum_total_occupied"] += row['sum_total_occupied']
        
    # Calculate state-level formatted fields
    for state, data in state_summary.items():
        data["sum_total_collection_in_cr"] = f"{round(float(data['sum_total_collection'] or 0) / 10000000.0, 3)} CR"
        
        if data["sum_total_seats"] > 0:
            data["occpency_avg_percentile"] = round((data["sum_total_occupied"] * 100.0) / data["sum_total_seats"], 2)
        else:
            data["occpency_avg_percentile"] = 0.0
            
    return state_summary

@app.get("/api/v1/analytics/movies/{movie_id}/theaters")
def get_movie_theaters(movie_id: str, city_id: int, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT t.theater_id, t.name as theater_name, count(s.show_id) as total_shows,
               sum(m.net_collection) as total_collection,
               sum(m.capacity) as total_capacity, sum(m.occupancy) as total_occupancy
        FROM shows s
        JOIN theaters t ON s.theater_id = t.theater_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE s.movie_id = %s AND t.city_id = %s
    '''
    params = [movie_id, city_id]
    if date:
        query += ' AND s.show_date = %s'
        params.append(date)
    query += ' GROUP BY t.theater_id, t.name'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    theater_list = [dict(row) for row in rows]
    
    summary = {
        "total_theater_count": len(theater_list),
        "total_Show_count": sum(t.get('total_shows', 0) for t in theater_list),
        "sum_total_collection": sum(t.get('total_collection', 0) or 0 for t in theater_list),
        "sum_total_collection_in_cr": f"{round(float(sum(t.get('total_collection', 0) or 0 for t in theater_list)) / 10000000.0, 3)} CR",
        "total_capacity": sum(t.get('total_capacity', 0) for t in theater_list),
        "total_occupancy": sum(t.get('total_occupancy', 0) for t in theater_list),
        "total_occupancy_percentile": 0.0,
        "theaters": theater_list
    }
    
    if summary["total_capacity"] > 0:
        summary["total_occupancy_percentile"] = round((summary["total_occupancy"] * 100.0) / summary["total_capacity"], 2)
        
    return summary

@app.get("/api/v1/analytics/movies/{movie_id}/shows")
def get_movie_shows(movie_id: str, theater_id: str, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT t.name as theater_name, mov.title as movie_name, s.show_id, s.screen_name, s.show_time, s.show_date, s.is_finalized,
               m.capacity, m.occupancy, m.net_collection, m.timestamp as last_updated, m.metric_id
        FROM shows s
        JOIN theaters t ON s.theater_id = t.theater_id
        JOIN movies mov ON s.movie_id = mov.movie_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE s.movie_id = %s AND s.theater_id = %s
    '''
    params = [movie_id, theater_id]
    if date:
        query += ' AND s.show_date = %s'
        params.append(date)
    query += ' ORDER BY s.show_time ASC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # Fetch price breakdown for all these metrics
    metric_ids = [r['metric_id'] for r in rows if r['metric_id']]
    prices_map = {}
    if metric_ids:
        chunk_size = 50
        for i in range(0, len(metric_ids), chunk_size):
            chunk = metric_ids[i:i + chunk_size]
            placeholders = ','.join('%s' for _ in chunk)
            cursor.execute(f"SELECT metric_id, ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id IN ({placeholders})", chunk)
            for p_row in cursor.fetchall():
                mid = p_row['metric_id']
                if mid not in prices_map:
                    prices_map[mid] = []
                prices_map[mid].append({
                    "price": float(p_row['ticket_price']) if p_row['ticket_price'] else 0.0,
                    "capacity": p_row['capacity'],
                    "occupancy": p_row['occupancy']
                })
            
    conn.close()
    
    shows = []
    theater_name = ""
    movie_name_val = ""
    for row in rows:
        d = dict(row)
        theater_name = d.pop('theater_name', "")
        movie_name_val = d.pop('movie_name', "")
        
        show_time_str = d.get('show_time')
        if show_time_str and show_time_str != "Unknown":
            try:
                # District provides show_time in UTC
                st = datetime.datetime.strptime(show_time_str, "%Y-%m-%dT%H:%M")
                st_ist = st + datetime.timedelta(hours=5, minutes=30)
                d['show_time_ist'] = st_ist.strftime("%I:%M %p")
            except Exception:
                d['show_time_ist'] = show_time_str
        else:
            d['show_time_ist'] = show_time_str
            
        metric_id = d.pop('metric_id', None)
        d['price_capacity_breakdown'] = prices_map.get(metric_id, [])
            
        shows.append(d)
        
    return {
        "theater_name": theater_name,
        "movie_name": movie_name_val,
        "shows_count": len(shows),
        "shows": shows
    }

@app.get("/api/v1/analytics/theaters/{theater_id}/summary")
def get_theater_summary(theater_id: str, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT t.name as theater_name, mov.title as movie_name, s.show_id, s.screen_name, s.show_time, s.show_date, s.is_finalized,
               m.capacity, m.occupancy, m.net_collection as total_collection, m.timestamp as last_updated, m.metric_id
        FROM shows s
        JOIN movies mov ON s.movie_id = mov.movie_id
        JOIN theaters t ON s.theater_id = t.theater_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE s.theater_id = %s
    '''
    params = [theater_id]
    if date:
        query += ' AND s.show_date = %s'
        params.append(date)
    query += ' ORDER BY s.show_time ASC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # Fetch price breakdown for all these metrics
    metric_ids = [r['metric_id'] for r in rows if r['metric_id']]
    prices_map = {}
    if metric_ids:
        chunk_size = 50
        for i in range(0, len(metric_ids), chunk_size):
            chunk = metric_ids[i:i + chunk_size]
            placeholders = ','.join('%s' for _ in chunk)
            cursor.execute(f"SELECT metric_id, ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id IN ({placeholders})", chunk)
            for p_row in cursor.fetchall():
                mid = p_row['metric_id']
                if mid not in prices_map:
                    prices_map[mid] = []
                prices_map[mid].append({
                    "price": float(p_row['ticket_price']) if p_row['ticket_price'] else 0.0,
                    "capacity": p_row['capacity'],
                    "occupancy": p_row['occupancy']
                })
            
    conn.close()
    
    shows = []
    theater_name = ""
    for row in rows:
        d = dict(row)
        theater_name = d.pop('theater_name', "")
        
        show_time_str = d.get('show_time')
        if show_time_str and show_time_str != "Unknown":
            try:
                # District provides show_time in UTC
                st = datetime.datetime.strptime(show_time_str, "%Y-%m-%dT%H:%M")
                st_ist = st + datetime.timedelta(hours=5, minutes=30)
                d['show_time_ist'] = st_ist.strftime("%I:%M %p")
            except Exception:
                d['show_time_ist'] = show_time_str
        else:
            d['show_time_ist'] = show_time_str
            
        metric_id = d.pop('metric_id', None)
        d['price_capacity_breakdown'] = prices_map.get(metric_id, [])
            
        shows.append(d)
        
    return {
        "theater_name": theater_name,
        "shows": shows
    }

@app.get("/api/v1/analytics/theaters/{theater_id}/shows")
def get_theater_shows(theater_id: str, screen_name: str, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT s.show_id, mov.title as movie_name, s.show_time, s.show_date, s.is_finalized,
               m.capacity, m.occupancy, m.net_collection, m.timestamp as last_updated
        FROM shows s
        JOIN movies mov ON s.movie_id = mov.movie_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE s.theater_id = %s AND s.screen_name = %s
    '''
    params = [theater_id, screen_name]
    if date:
        query += ' AND s.show_date = %s'
        params.append(date)
    query += ' ORDER BY s.show_time ASC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

@app.get("/api/v1/analytics/shows/{show_id}/prices")
def get_show_price_breakdown(show_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get latest metric snapshot for this show
    cursor.execute('SELECT metric_id FROM show_metrics WHERE show_id = %s ORDER BY timestamp DESC LIMIT 1', (show_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Show not found or no metrics available")
        
    metric_id = row['metric_id']
    
    # Fetch price breakdown for this metric
    cursor.execute('SELECT ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id = %s ORDER BY ticket_price DESC', (metric_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]

@app.get("/api/v1/analytics/day-wise-breakdown-by-tollybo-movie-id")
def get_day_wise_breakdown_by_tollybo_movie_id(tollybo_movie_id: int, date: str):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT l.state_name, l.city_name, t.theater_id, t.name as theater_name,
               s.show_id, s.screen_name, s.show_date, s.show_time, s.is_finalized,
               m.capacity, m.occupancy, m.net_collection, m.timestamp as last_updated, m.metric_id,
               mov.movie_id, mov.title as movie_name
        FROM shows s
        JOIN movies mov ON s.movie_id = mov.movie_id
        JOIN theaters t ON s.theater_id = t.theater_id
        JOIN locations l ON t.city_id = l.city_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE mov.tollybo_movie_id = %s AND s.show_date = %s
    '''
    
    cursor.execute(query, (tollybo_movie_id, date))
    rows = cursor.fetchall()
    
    if not rows:
        conn.close()
        raise HTTPException(status_code=404, detail="No data found")
        
    metric_ids = [dict(r).get('metric_id') for r in rows if dict(r).get('metric_id')]
    prices_map = {}
    if metric_ids:
        chunk_size = 50
        for i in range(0, len(metric_ids), chunk_size):
            chunk = metric_ids[i:i + chunk_size]
            placeholders = ','.join('%s' for _ in chunk)
            cursor.execute(f"SELECT metric_id, ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id IN ({placeholders})", chunk)
            for p_row in cursor.fetchall():
                p_dict = dict(p_row)
                mid = p_dict['metric_id']
                if mid not in prices_map:
                    prices_map[mid] = []
                prices_map[mid].append({
                    "price": float(p_dict['ticket_price']) if p_dict['ticket_price'] else 0.0,
                    "capacity": p_dict['capacity'],
                    "occupancy": p_dict['occupancy']
                })
            
    conn.close()
    
    first_row = dict(rows[0])
    movie_id = first_row['movie_id']
    movie_name = first_row['movie_name']
    
    result = {
        "tollybo_movie_id": tollybo_movie_id,
        "movie_id": movie_id,
        "movie_name": movie_name,
        "date": date,
        "total_collection": 0,
        "total_theaters_count": 0,
        "total_show_count": 0,
        "occupancy_percentage": 0.0,
        "total_capacity": 0,
        "total_occupancy": 0,
        "regions": []
    }
    
    states_dict = {}
    for r in rows:
        row = dict(r)
        state = row['state_name']
        city = row['city_name']
        theater_id = row['theater_id']
        theater_name = row['theater_name']
        
        # State Level
        if state not in states_dict:
            states_dict[state] = {
                "state": state,
                "total_collection": 0,
                "total_theaters_count": 0,
                "total_show_count": 0,
                "total_capacity": 0,
                "total_occupancy": 0,
                "occupancy_percentage": 0.0,
                "cities_dict": {},
                "cities": []
            }
        
        # City Level
        if city not in states_dict[state]["cities_dict"]:
            states_dict[state]["cities_dict"][city] = {
                "city": city,
                "total_collection": 0,
                "total_theaters_count": 0,
                "total_show_count": 0,
                "total_capacity": 0,
                "total_occupancy": 0,
                "occupancy_percentage": 0.0,
                "theaters_dict": {},
                "theaters": []
            }
            
        # Theater Level
        if theater_id not in states_dict[state]["cities_dict"][city]["theaters_dict"]:
            states_dict[state]["cities_dict"][city]["theaters_dict"][theater_id] = {
                "theater_id": theater_id,
                "theater_name": theater_name,
                "total_collection": 0,
                "total_show_count": 0,
                "total_capacity": 0,
                "total_occupancy": 0,
                "occupancy_percentage": 0.0,
                "shows": []
            }
            # Increment theater counts
            states_dict[state]["total_theaters_count"] += 1
            states_dict[state]["cities_dict"][city]["total_theaters_count"] += 1
            result["total_theaters_count"] += 1
            
        # Show Level
        show_time_str = row['show_time']
        show_time_ist = show_time_str
        if show_time_str and show_time_str != "Unknown":
            try:
                st = datetime.datetime.strptime(show_time_str, "%Y-%m-%dT%H:%M")
                st_ist = st + datetime.timedelta(hours=5, minutes=30)
                show_time_ist = st_ist.strftime("%I:%M %p")
            except Exception:
                pass
                
        show_data = {
            "show_id": row['show_id'],
            "screen_name": row['screen_name'],
            "show_date": row['show_date'],
            "show_time": row['show_time'],
            "show_time_ist": show_time_ist,
            "capacity": row['capacity'],
            "occupancy": row['occupancy'],
            "total_collection": row['net_collection'],
            "is_finalized": bool(row['is_finalized']),
            "last_updated": row['last_updated'],
            "price_capacity_breakdown": prices_map.get(row['metric_id'], [])
        }
        
        # Add show
        states_dict[state]["cities_dict"][city]["theaters_dict"][theater_id]["shows"].append(show_data)
        
        # Aggregate totals
        collection = row['net_collection'] or 0
        capacity = row['capacity'] or 0
        occupancy = row['occupancy'] or 0
        
        # Theater aggregation
        states_dict[state]["cities_dict"][city]["theaters_dict"][theater_id]["total_collection"] += collection
        states_dict[state]["cities_dict"][city]["theaters_dict"][theater_id]["total_show_count"] += 1
        states_dict[state]["cities_dict"][city]["theaters_dict"][theater_id]["total_capacity"] += capacity
        states_dict[state]["cities_dict"][city]["theaters_dict"][theater_id]["total_occupancy"] += occupancy
        
        # City aggregation
        states_dict[state]["cities_dict"][city]["total_collection"] += collection
        states_dict[state]["cities_dict"][city]["total_show_count"] += 1
        states_dict[state]["cities_dict"][city]["total_capacity"] += capacity
        states_dict[state]["cities_dict"][city]["total_occupancy"] += occupancy
        
        # State aggregation
        states_dict[state]["total_collection"] += collection
        states_dict[state]["total_show_count"] += 1
        states_dict[state]["total_capacity"] += capacity
        states_dict[state]["total_occupancy"] += occupancy
        
        # Global aggregation
        result["total_collection"] += collection
        result["total_show_count"] += 1
        result["total_capacity"] += capacity
        result["total_occupancy"] += occupancy
        
    # Calculate percentages and flatten dicts
    if result["total_capacity"] > 0:
        result["occupancy_percentage"] = round((result["total_occupancy"] * 100.0) / result["total_capacity"], 2)
        
    for state, s_data in states_dict.items():
        if s_data["total_capacity"] > 0:
            s_data["occupancy_percentage"] = round((s_data["total_occupancy"] * 100.0) / s_data["total_capacity"], 2)
            
        for city, c_data in s_data["cities_dict"].items():
            if c_data["total_capacity"] > 0:
                c_data["occupancy_percentage"] = round((c_data["total_occupancy"] * 100.0) / c_data["total_capacity"], 2)
                
            for t_id, t_data in c_data["theaters_dict"].items():
                if t_data["total_capacity"] > 0:
                    t_data["occupancy_percentage"] = round((t_data["total_occupancy"] * 100.0) / t_data["total_capacity"], 2)
                
                t_data.pop("total_capacity", None)
                t_data.pop("total_occupancy", None)
                c_data["theaters"].append(t_data)
                
            c_data.pop("theaters_dict", None)
            c_data.pop("total_capacity", None)
            c_data.pop("total_occupancy", None)
            
            c_data["theaters"].sort(key=lambda x: x["total_collection"], reverse=True)
            s_data["cities"].append(c_data)
            
        s_data.pop("cities_dict", None)
        s_data.pop("total_capacity", None)
        s_data.pop("total_occupancy", None)
        
        s_data["cities"].sort(key=lambda x: x["total_collection"], reverse=True)
        result["regions"].append(s_data)
        
    result.pop("total_capacity", None)
    result.pop("total_occupancy", None)
    
    result["regions"].sort(key=lambda x: x["total_collection"], reverse=True)
    
    return result

@app.get("/api/v1/analytics/dates-history-tollybo-movie-id")
def get_dates_history_tollybo_movie_id(tollybo_movie_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT DISTINCT s.show_date
        FROM shows s
        JOIN movies mov ON s.movie_id = mov.movie_id
        WHERE mov.tollybo_movie_id = %s
        ORDER BY s.show_date ASC
    '''
    
    cursor.execute(query, (tollybo_movie_id,))
    rows = cursor.fetchall()
    conn.close()
    
    dates = [dict(r).get('show_date') for r in rows if dict(r).get('show_date')]
    return dates

class TheatersListRequest(BaseModel):
    state_name: Optional[str] = None
    city_id: Optional[int] = None
    theater_id: Optional[str] = None

@app.post("/api/v1/analytics/theaters-list")
def get_theaters_list(req: TheatersListRequest):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT t.*, l.city_name, l.state_name
        FROM theaters t
        JOIN locations l ON t.city_id = l.city_id
        WHERE 1=1
    '''
    params = []
    
    if req.theater_id:
        query += " AND t.theater_id = %s"
        params.append(req.theater_id)
    if req.city_id:
        query += " AND t.city_id = %s"
        params.append(req.city_id)
    if req.state_name:
        query += " AND l.state_name = %s"
        params.append(req.state_name)
        
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]

@app.get("/api/v1/analytics/regions-list")
def get_regions_list():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT state_name FROM locations WHERE state_name IS NOT NULL ORDER BY state_name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r).get('state_name') for r in rows if dict(r).get('state_name')]

@app.get("/api/v1/analytics/citis-list")
def get_cities_list(state: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT city_id, city_name FROM locations WHERE state_name = %s ORDER BY city_name ASC", (state,))
    rows = cursor.fetchall()
    conn.close()
    return [{"city_id": dict(r).get('city_id'), "city_name": dict(r).get('city_name')} for r in rows]

@app.get("/api/v1/analytics/theater")
def get_theater_info(theater_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.*, l.city_name, l.state_name 
        FROM theaters t 
        JOIN locations l ON t.city_id = l.city_id 
        WHERE t.theater_id = %s
    ''', (theater_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Theater not found")
        
    return dict(row)

@app.get("/api/v1/analytics/dates-history-by-theater-id")
def get_dates_history_by_theater_id(theater_id: str = Query(..., alias="theater-id")):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT DISTINCT s.show_date
        FROM shows s
        WHERE s.theater_id = %s
        ORDER BY s.show_date ASC
    '''
    
    cursor.execute(query, (theater_id,))
    rows = cursor.fetchall()
    conn.close()
    
    dates = [dict(r).get('show_date') for r in rows if dict(r).get('show_date')]
    return dates

@app.get("/api/v1/analytics/day-wise-breakdown-by-theater-id")
def get_day_wise_breakdown_by_theater_id(theater_id: str = Query(..., alias="theater-id"), date: str = None):
    return get_theater_summary(theater_id, date)

@app.get("/api/v1/analytics/box-office/movies-list")
def get_box_office_movies_list():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT *
        FROM movies
        WHERE tollybo_movie_id IS NOT NULL
        ORDER BY movie_id DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
