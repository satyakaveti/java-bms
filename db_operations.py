import sqlite3
import datetime
from database import get_connection

import requests
import urllib.parse

def upsert_movie(movie_id, title, language, tollybo_movie_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if movie exists and if tollybo_movie_id is already populated
    cursor.execute("SELECT tollybo_movie_id FROM movies WHERE movie_id = ?", (movie_id,))
    existing = cursor.fetchone()
    
    # If not in DB, or if it is but tollybo_movie_id is null/empty
    if not existing or not existing[0]:
        try:
            year = datetime.datetime.now().year
            encoded_title = urllib.parse.quote(title)
            api_url = f"https://web-api.tollybo.com/api/movies?name={encoded_title}&year={year}"
            print(f"[Tollybo API] Making request: {api_url}")
            
            resp = requests.get(api_url, timeout=10)
            print(f"[Tollybo API] Response Status: {resp.status_code}")
            
            if resp.status_code == 200:
                resp_json = resp.json()
                print(f"[Tollybo API] Response Payload: {resp_json}")
                data = resp_json.get("data", [])
                if data and len(data) > 0:
                    tollybo_movie_id = data[0].get("id")
                    print(f"[Tollybo API] Successfully extracted ID {tollybo_movie_id} for '{title}'")
                else:
                    print(f"[Tollybo API] Warning: 'data' array is empty for '{title}'")
            else:
                print(f"[Tollybo API] Error response: {resp.text}")
                
        except Exception as e:
            print(f"[Tollybo API] Exception fetching tollybo_movie_id for {title}: {e}")

    cursor.execute('''
    INSERT INTO movies (movie_id, title, language, tollybo_movie_id)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(movie_id) DO UPDATE SET
        title = excluded.title,
        language = excluded.language,
        tollybo_movie_id = COALESCE(excluded.tollybo_movie_id, movies.tollybo_movie_id)
    ''', (movie_id, title, language, tollybo_movie_id))
    
    conn.commit()
    conn.close()

def upsert_location(city_id, city_name, state_name, city_key=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO locations (city_id, city_name, state_name, city_key)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(city_id) DO UPDATE SET
        city_name = excluded.city_name,
        state_name = excluded.state_name,
        city_key = excluded.city_key
    WHERE locations.city_name != excluded.city_name 
       OR locations.state_name != excluded.state_name
       OR IFNULL(locations.city_key, '') != IFNULL(excluded.city_key, '')
    ''', (city_id, city_name, state_name, city_key))
    conn.commit()
    conn.close()

def upsert_theater(theater_id, city_id, name, lat=None, lon=None, address=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if theater already exists to distinguish ADDED from UPDATED
    cursor.execute("SELECT 1 FROM theaters WHERE theater_id = ?", (theater_id,))
    existed = cursor.fetchone() is not None
    
    cursor.execute('''
    INSERT INTO theaters (theater_id, city_id, name, lat, lon, address)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(theater_id) DO UPDATE SET
        city_id = excluded.city_id,
        name = excluded.name,
        lat = excluded.lat,
        lon = excluded.lon,
        address = excluded.address
    WHERE theaters.name != excluded.name 
       OR theaters.city_id != excluded.city_id
       OR IFNULL(theaters.lat, 0) != IFNULL(excluded.lat, 0)
       OR IFNULL(theaters.lon, 0) != IFNULL(excluded.lon, 0)
       OR IFNULL(theaters.address, '') != IFNULL(excluded.address, '')
    ''', (theater_id, city_id, name, lat, lon, address))
    
    rowcount = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    if not existed:
        return "ADDED"
    elif rowcount > 0:
        return "UPDATED"
    else:
        return "ALREADY_EXISTED"

def upsert_show_and_record_metric(show_id, theater_id, movie_id, screen_name, show_time, show_date, capacity, occupancy, net_collection, price_breakdown=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    # Upsert the show (don't overwrite is_finalized if it already exists, just update static info)
    cursor.execute('''
    INSERT INTO shows (show_id, theater_id, movie_id, screen_name, show_time, show_date, is_finalized)
    VALUES (?, ?, ?, ?, ?, ?, 0)
    ON CONFLICT(show_id) DO UPDATE SET
        theater_id = excluded.theater_id,
        movie_id = excluded.movie_id,
        screen_name = excluded.screen_name,
        show_time = excluded.show_time,
        show_date = excluded.show_date
    ''', (show_id, theater_id, movie_id, screen_name, show_time, show_date))
    
    # Insert metric snapshot
    now_utc = datetime.datetime.utcnow().isoformat()
    cursor.execute('''
    INSERT INTO show_metrics (show_id, timestamp, capacity, occupancy, net_collection)
    VALUES (?, ?, ?, ?, ?)
    ''', (show_id, now_utc, capacity, occupancy, net_collection))
    
    metric_id = cursor.lastrowid
    
    if price_breakdown:
        price_records = []
        for price, stats in price_breakdown.items():
            price_records.append((metric_id, price, stats['capacity'], stats['occupancy']))
            
        cursor.executemany('''
        INSERT INTO show_metric_prices (metric_id, ticket_price, capacity, occupancy)
        VALUES (?, ?, ?, ?)
        ''', price_records)
    
    conn.commit()
    conn.close()

def finalize_past_or_missing_shows(current_active_show_ids):
    """
    Finds all non-finalized shows. If they are in the past OR not in current_active_show_ids,
    mark them as finalized.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get all currently non-finalized shows
    cursor.execute('SELECT show_id, show_time FROM shows WHERE is_finalized = 0')
    unfinalized = cursor.fetchall()
    
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    
    shows_to_finalize = []
    for row in unfinalized:
        s_id = row['show_id']
        s_time_str = row['show_time']
        
        should_finalize = False
        
        # If show is no longer returned by the scraper
        if current_active_show_ids is not None and s_id not in current_active_show_ids:
            should_finalize = True
        else:
            # Or if the show time is in the past
            try:
                st = datetime.datetime.fromisoformat(s_time_str)
                if st < now:
                    should_finalize = True
            except:
                pass
                
        if should_finalize:
            shows_to_finalize.append((s_id,))
            
    if shows_to_finalize:
        cursor.executemany('UPDATE shows SET is_finalized = 1 WHERE show_id = ?', shows_to_finalize)
        conn.commit()
        
    conn.close()
    return len(shows_to_finalize)

def finalize_end_of_day(target_date):
    """
    Force finalize all shows for a specific date (usually run at 11:30 PM).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE shows SET is_finalized = 1 WHERE show_date = ?', (target_date,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count
