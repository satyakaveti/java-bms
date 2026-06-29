from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uuid
import uvicorn
from typing import Dict, Any

try:
    from district_scraper import run_district_scraping_job, fetch_regions_district, get_movies_by_region_district
except ImportError:
    run_district_scraping_job = None
    fetch_regions_district = None
    get_movies_by_region_district = None

app = FastAPI(title="District Ticketing Analyzer")

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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
