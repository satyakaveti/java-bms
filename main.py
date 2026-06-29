from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uuid
import uvicorn
from typing import Dict, Any, Optional, List
import asyncio
import datetime
import traceback
from database import get_connection
import db_operations

try:
    from district_scraper import run_district_scraping_job, fetch_regions_district, get_movies_by_region_district, fetch_cinemas_direct
except ImportError:
    run_district_scraping_job = None
    fetch_regions_district = None
    get_movies_by_region_district = None
    get_movies_by_region_district = None

app = FastAPI(title="District Ticketing Analyzer")

@app.on_event("startup")
async def startup_event():
    import database
    database.init_db()
    
    # Start the periodic background scheduler (Disabled per user request)
    # asyncio.create_task(run_scheduler())

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
        
    for t in theaters:
        t["city_name"] = city_name
        
    return theaters

class SyncRequest(BaseModel):
    region: Optional[str] = None

class FullRunRequest(BaseModel):
    regions: List[str]
    language: str
    movieName: Optional[str] = None

@app.post("/api/v1/district/full-run", status_code=202)
def full_run_sync(req: FullRunRequest, background_tasks: BackgroundTasks):
    if not fetch_regions_district:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    def full_run_job():
        try:
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
                    # This will scrape and save to movies, shows, show_metrics, show_metric_prices
                    jobs_db[job_id] = {"status": "PROCESSING", "data": None, "error": None}
                    run_district_scraping_job(job_id, movie_name, jobs_db, target_state=state)
                    
            print("[Full Run] Completed successfully.")
        except Exception as e:
            print(f"[Full Run] Error: {e}")
            traceback.print_exc()
            
    background_tasks.add_task(full_run_job)
    return {"message": f"Full run for {req.language} movies in {len(req.regions)} regions initiated in the background."}

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
                
            for r in regions:
                c_id = r.get("city_id")
                if not c_id: continue
                c_name = r.get("city_name")
                s_name = r.get("state_name", "Unknown State")
                c_key = r.get("city_key")
                
                db_operations.upsert_location(int(c_id), c_name, s_name, c_key)
                
                theaters = fetch_cinemas_direct(c_name)
                for t in theaters:
                    tid = t.get("theater_id")
                    if tid:
                        db_operations.upsert_theater(
                            theater_id=tid, 
                            city_id=int(c_id), 
                            name=t.get("theater_name"), 
                            lat=t.get("lat"), 
                            lon=t.get("lon"), 
                            address=t.get("address")
                        )
        except Exception as e:
            print(f"Error in sync job: {e}")
            
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
               ROUND(sum(m.net_collection) / 10000000.0, 3) || ' CR' as sum_total_collection_in_cr,
               sum(m.capacity) as sum_total_seats,
               sum(m.occupancy) as sum_total_occupied,
               ROUND(sum(CAST(m.occupancy AS FLOAT)) * 100.0 / NULLIF(sum(m.capacity), 0), 2) as occpency_avg_percentile
        FROM shows s
        JOIN theaters t ON s.theater_id = t.theater_id
        JOIN locations l ON t.city_id = l.city_id
        JOIN (
            SELECT show_id, MAX(metric_id) as latest_metric_id
            FROM show_metrics
            GROUP BY show_id
        ) latest ON s.show_id = latest.show_id
        JOIN show_metrics m ON latest.latest_metric_id = m.metric_id
        WHERE s.movie_id = ?
    '''
    params = [movie_id]
    if date:
        query += ' AND s.show_date = ?'
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
        data["sum_total_collection_in_cr"] = f"{round(data['sum_total_collection'] / 10000000.0, 3)} CR"
        
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
        WHERE s.movie_id = ? AND t.city_id = ?
    '''
    params = [movie_id, city_id]
    if date:
        query += ' AND s.show_date = ?'
        params.append(date)
    query += ' GROUP BY t.theater_id, t.name'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    theater_list = [dict(row) for row in rows]
    
    summary = {
        "total_theater_count": len(theater_list),
        "total_Show_count": sum(t.get('total_shows', 0) for t in theater_list),
        "sum_total_collection": sum(t.get('total_collection', 0) for t in theater_list),
        "sum_total_collection_in_cr": f"{round(sum(t.get('total_collection', 0) for t in theater_list) / 10000000.0, 3)} CR",
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
        WHERE s.movie_id = ? AND s.theater_id = ?
    '''
    params = [movie_id, theater_id]
    if date:
        query += ' AND s.show_date = ?'
        params.append(date)
    query += ' ORDER BY s.show_time ASC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # Fetch price breakdown for all these metrics
    metric_ids = [r['metric_id'] for r in rows if r['metric_id']]
    prices_map = {}
    if metric_ids:
        placeholders = ','.join('?' for _ in metric_ids)
        cursor.execute(f"SELECT metric_id, ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id IN ({placeholders})", metric_ids)
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
        WHERE s.theater_id = ?
    '''
    params = [theater_id]
    if date:
        query += ' AND s.show_date = ?'
        params.append(date)
    query += ' ORDER BY s.show_time ASC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    # Fetch price breakdown for all these metrics
    metric_ids = [r['metric_id'] for r in rows if r['metric_id']]
    prices_map = {}
    if metric_ids:
        placeholders = ','.join('?' for _ in metric_ids)
        cursor.execute(f"SELECT metric_id, ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id IN ({placeholders})", metric_ids)
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
        WHERE s.theater_id = ? AND s.screen_name = ?
    '''
    params = [theater_id, screen_name]
    if date:
        query += ' AND s.show_date = ?'
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
    cursor.execute('SELECT metric_id FROM show_metrics WHERE show_id = ? ORDER BY timestamp DESC LIMIT 1', (show_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Show not found or no metrics available")
        
    metric_id = row['metric_id']
    
    # Fetch price breakdown for this metric
    cursor.execute('SELECT ticket_price, capacity, occupancy FROM show_metric_prices WHERE metric_id = ? ORDER BY ticket_price DESC', (metric_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(r) for r in rows]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
