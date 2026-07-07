import datetime
from database import get_connection
import requests
import urllib.parse

def upsert_movie(movie_id, title, language, tollybo_movie_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT tollybo_movie_id FROM movies WHERE movie_id = %s", (movie_id,))
    existing = cursor.fetchone()
    
    t_id = None
    if existing:
        try:
            t_id = existing["tollybo_movie_id"]
        except (KeyError, IndexError, TypeError):
            t_id = existing[0] if isinstance(existing, tuple) else None
    
    if not existing or not t_id:
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
                
                if "id" in resp_json:
                    tollybo_movie_id = resp_json.get("id")
                    print(f"[Tollybo API] Successfully extracted ID {tollybo_movie_id} for '{title}'")
                else:
                    data = resp_json.get("data", [])
                    if data and len(data) > 0:
                        tollybo_movie_id = data[0].get("id")
                        print(f"[Tollybo API] Successfully extracted ID {tollybo_movie_id} for '{title}'")
                    else:
                        print(f"[Tollybo API] Warning: Could not find 'id' or 'data' array for '{title}'")
            else:
                print(f"[Tollybo API] Error response: {resp.text}")
                
        except Exception as e:
            print(f"[Tollybo API] Exception fetching tollybo_movie_id for {title}: {e}")

    cursor.execute('''
    INSERT INTO movies (movie_id, title, language, tollybo_movie_id)
    VALUES (%s, %s, %s, %s)
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
    VALUES (%s, %s, %s, %s)
    ON CONFLICT(city_id) DO UPDATE SET
        city_name = excluded.city_name,
        state_name = excluded.state_name,
        city_key = excluded.city_key
    WHERE locations.city_name != excluded.city_name 
       OR locations.state_name != excluded.state_name
       OR COALESCE(locations.city_key, '') != COALESCE(excluded.city_key, '')
    ''', (city_id, city_name, state_name, city_key))
    conn.commit()
    conn.close()

def upsert_theater(theater_id, city_id, name, lat=None, lon=None, address=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT 1 FROM theaters WHERE theater_id = %s", (theater_id,))
    existed = cursor.fetchone() is not None
    
    cursor.execute('''
    INSERT INTO theaters (theater_id, city_id, name, lat, lon, address)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT(theater_id) DO UPDATE SET
        city_id = CASE 
            WHEN excluded.city_id < 100 AND theaters.city_id > 100 THEN excluded.city_id 
            ELSE theaters.city_id 
        END,
        name = excluded.name,
        lat = excluded.lat,
        lon = excluded.lon,
        address = excluded.address
    WHERE theaters.name != excluded.name 
       OR (excluded.city_id < 100 AND theaters.city_id > 100)
       OR COALESCE(theaters.lat, 0) != COALESCE(excluded.lat, 0)
       OR COALESCE(theaters.lon, 0) != COALESCE(excluded.lon, 0)
       OR COALESCE(theaters.address, '') != COALESCE(excluded.address, '')
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
    
    cursor.execute('''
    INSERT INTO shows (show_id, theater_id, movie_id, screen_name, show_time, show_date, is_finalized)
    VALUES (%s, %s, %s, %s, %s, %s, FALSE)
    ON CONFLICT(show_id) DO UPDATE SET
        theater_id = excluded.theater_id,
        movie_id = excluded.movie_id,
        screen_name = excluded.screen_name,
        show_time = excluded.show_time,
        show_date = excluded.show_date
    ''', (show_id, theater_id, movie_id, screen_name, show_time, show_date))
    
    # Fetch all metrics for this show
    cursor.execute('''
    SELECT metric_id, capacity, occupancy, net_collection 
    FROM show_metrics 
    WHERE show_id = %s 
    ORDER BY metric_id DESC
    ''', (show_id,))
    metrics = cursor.fetchall()
    
    now_utc = datetime.datetime.utcnow().isoformat()
    
    if metrics:
        latest = metrics[0]
        metric_id = latest['metric_id']
        
        old_cap = latest['capacity']
        old_occ = latest['occupancy']
        old_net = float(latest['net_collection']) if latest['net_collection'] is not None else 0.0
        new_net = float(net_collection) if net_collection is not None else 0.0
        
        changed = not (old_cap == capacity and old_occ == occupancy and abs(old_net - new_net) < 0.01)
        
        if changed:
            cursor.execute('''
            UPDATE show_metrics 
            SET timestamp = %s, capacity = %s, occupancy = %s, net_collection = %s
            WHERE metric_id = %s
            ''', (now_utc, capacity, occupancy, net_collection, metric_id))
            
            cursor.execute('DELETE FROM show_metric_prices WHERE metric_id = %s', (metric_id,))
            if price_breakdown:
                price_records = []
                for price, stats in price_breakdown.items():
                    price_records.append((metric_id, price, stats['capacity'], stats['occupancy']))
                if price_records:
                    cursor.executemany('''
                    INSERT INTO show_metric_prices (metric_id, ticket_price, capacity, occupancy)
                    VALUES (%s, %s, %s, %s)
                    ''', price_records)
                
        # Clean up historical duplicates to save space!
        if len(metrics) > 1:
            old_metric_ids = [m['metric_id'] for m in metrics[1:]]
            placeholders = ','.join(['%s'] * len(old_metric_ids))
            cursor.execute(f'DELETE FROM show_metric_prices WHERE metric_id IN ({placeholders})', old_metric_ids)
            cursor.execute(f'DELETE FROM show_metrics WHERE metric_id IN ({placeholders})', old_metric_ids)
            
    else:
        cursor.execute('''
        INSERT INTO show_metrics (show_id, timestamp, capacity, occupancy, net_collection)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING metric_id
        ''', (show_id, now_utc, capacity, occupancy, net_collection))
        metric_id = cursor.fetchone()['metric_id']
        
        if price_breakdown:
            price_records = []
            for price, stats in price_breakdown.items():
                price_records.append((metric_id, price, stats['capacity'], stats['occupancy']))
            if price_records:
                cursor.executemany('''
                INSERT INTO show_metric_prices (metric_id, ticket_price, capacity, occupancy)
                VALUES (%s, %s, %s, %s)
                ''', price_records)
    
    conn.commit()
    conn.close()

def finalize_past_or_missing_shows(current_active_show_ids):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT show_id, show_time FROM shows WHERE is_finalized = FALSE')
    unfinalized = cursor.fetchall()
    
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    
    shows_to_finalize = []
    for row in unfinalized:
        s_id = row['show_id']
        s_time_str = row['show_time']
        
        should_finalize = False
        
        if current_active_show_ids is not None and s_id not in current_active_show_ids:
            should_finalize = True
        else:
            try:
                # Need to handle potential datetime objects returned by psycopg2
                if isinstance(s_time_str, datetime.datetime):
                    st = s_time_str
                else:
                    st = datetime.datetime.fromisoformat(str(s_time_str))
                if st < now:
                    should_finalize = True
            except:
                pass
                
        if should_finalize:
            shows_to_finalize.append((s_id,))
            
    if shows_to_finalize:
        cursor.executemany('UPDATE shows SET is_finalized = TRUE WHERE show_id = %s', shows_to_finalize)
        conn.commit()
        
    conn.close()
    return len(shows_to_finalize)

def finalize_end_of_day(target_date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE shows SET is_finalized = TRUE WHERE show_date = %s', (target_date,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count
