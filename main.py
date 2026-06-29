from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uuid
import uvicorn
from typing import Dict, Any
from scraper import run_scraping_job, fetch_regions
try:
    from district_scraper import run_district_scraping_job, fetch_regions_district
except ImportError:
    run_district_scraping_job = None
    fetch_regions_district = None

app = FastAPI(title="BookMyShow Data Analyzer")

# In-memory global dictionary to store job statuses and results
# Format: { "job_id": { "status": "PROCESSING", "data": {}, "error": "" } }
jobs_db: Dict[str, Dict[str, Any]] = {}

class AnalysisRequest(BaseModel):
    movieName: str

class AnalysisResponse(BaseModel):
    jobId: str
    status: str
    message: str = None

@app.post("/api/v1/bms/analyze", response_model=AnalysisResponse, status_code=202)
async def analyze_movie(request: AnalysisRequest, background_tasks: BackgroundTasks):
    movie_name = request.movieName.strip()
    if not movie_name:
        raise HTTPException(status_code=400, detail="movieName is required")

    job_id = str(uuid.uuid4())
    jobs_db[job_id] = {
        "status": "PROCESSING",
        "data": None,
        "error": None
    }
    
    # Run the scraping logic in the background
    background_tasks.add_task(run_scraping_job, job_id, movie_name, jobs_db)
    
    return {
        "jobId": job_id,
        "status": "PROCESSING",
        "message": "Scraping job initiated. Check status using the jobId."
    }

@app.post("/api/v1/bms/analyze/{region_name}", response_model=AnalysisResponse, status_code=202)
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
    
    # Run the scraping logic in the background, targeting only the specified state/region
    background_tasks.add_task(run_scraping_job, job_id, movie_name, jobs_db, region_name)
    
    return {
        "jobId": job_id,
        "status": "PROCESSING",
        "message": f"Scraping job initiated for region {region_name}. Check status using the jobId."
    }

@app.get("/api/v1/bms/status/{jobId}")
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

@app.post("/api/v1/district/analyze", response_model=AnalysisResponse, status_code=202)
async def analyze_movie_district(request: AnalysisRequest, background_tasks: BackgroundTasks):
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
        background_tasks.add_task(run_district_scraping_job, job_id, movie_name, jobs_db)
    else:
        raise HTTPException(status_code=501, detail="District scraper not implemented yet")
        
    return {
        "jobId": job_id,
        "status": "PROCESSING",
        "message": "District scraping job initiated. Check status using the jobId."
    }

@app.post("/api/v1/district/analyze/{region_name}", response_model=AnalysisResponse, status_code=202)
async def analyze_movie_by_region_district(region_name: str, request: AnalysisRequest, background_tasks: BackgroundTasks):
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
        "message": f"District scraping job initiated for region {region_name}. Check status using the jobId."
    }

@app.get("/api/v1/district/status/{jobId}")
async def get_district_analysis_status(jobId: str):
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

@app.get("/api/v1/bms/regions")
def get_bms_regions():
    regions = fetch_regions()
    result = {}
    for r in regions:
        state = r.get("state_name") or "Unknown State"
        city = r.get("name") or "Unknown City"
        
        if state not in result:
            result[state] = {}
        
        result[state][city] = {
            "code": r.get("code"),
            "slug": r.get("slug"),
            "lat": r.get("lat"),
            "lon": r.get("lon")
        }
    return result

@app.get("/api/v1/bms/regions/{region}")
def get_bms_regions_by_name(region: str):
    regions = fetch_regions()
    result = {}
    for r in regions:
        state = r.get("state_name") or "Unknown State"
        city = r.get("name") or "Unknown City"
        
        if state.lower() == region.lower():
            if state not in result:
                result[state] = {}
            result[state][city] = {
                "code": r.get("code"),
                "slug": r.get("slug"),
                "lat": r.get("lat"),
                "lon": r.get("lon")
            }
    if not result:
        raise HTTPException(status_code=404, detail=f"Region/State '{region}' not found")
    return result

@app.get("/api/v1/district/regions")
def get_district_regions():
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
            "lat": r.get("city_lat"),
            "lon": r.get("city_long")
        }
    return result

@app.get("/api/v1/district/regions/{region}")
def get_district_regions_by_name(region: str):
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
                "lat": r.get("city_lat"),
                "lon": r.get("city_long")
            }
    if not result:
        raise HTTPException(status_code=404, detail=f"Region/State '{region}' not found")
    return result

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
