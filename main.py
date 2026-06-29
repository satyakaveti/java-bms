from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uuid
import uvicorn
from typing import Dict, Any
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

# --- Analytics APIs ---

@app.get("/api/v1/analytics/movies/{movie_id}/summary")
def get_movie_summary(movie_id: str, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT l.state_name, l.city_name, sum(m.net_collection) as total_collection
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
    
    return [dict(row) for row in rows]

@app.get("/api/v1/analytics/theaters/{theater_id}/summary")
def get_theater_summary(theater_id: str, date: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    query = '''
        SELECT mov.title as movie_name, s.screen_name, sum(m.net_collection) as total_collection
        FROM shows s
        JOIN movies mov ON s.movie_id = mov.movie_id
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
    query += ' GROUP BY s.movie_id, s.screen_name'
    
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
