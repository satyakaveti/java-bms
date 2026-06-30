import sqlite3
import os
import requests

import sys

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collections.db')

DB_MODE = "LOCAL"
if len(sys.argv) > 1 and sys.argv[1].upper() in ["LOCAL", "PROD"]:
    DB_MODE = sys.argv[1].upper()
else:
    DB_MODE = os.environ.get("DB_MODE", "LOCAL").upper()

class D1Cursor:
    def __init__(self, account_id, db_id, api_token):
        self.account_id = account_id
        self.db_id = db_id
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/d1/database/{self.db_id}/query"
        self._results = []
        self.rowcount = -1
        self.lastrowid = None
        
    def execute(self, query, params=None):
        if params is None:
            params = []
        payload = {
            "sql": query,
            "params": list(params)
        }
        res = requests.post(self.base_url, headers=self.headers, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        if data.get("success"):
            result = data["result"][0]
            if "results" in result:
                self._results = result["results"]
            else:
                self._results = []
            
            meta = result.get("meta", {})
            self.rowcount = meta.get("rows_written", meta.get("changes", -1))
            self.lastrowid = meta.get("last_row_id", None)
        else:
            raise Exception(f"D1 Error: {data.get('errors')}")
        return self
        
    def executemany(self, query, seq_of_params):
        if not seq_of_params:
            self.rowcount = 0
            return self
            
        payload = []
        for params in seq_of_params:
            payload.append({
                "sql": query,
                "params": list(params)
            })
            
        chunk_size = 50
        total_rows = 0
        for i in range(0, len(payload), chunk_size):
            chunk = payload[i:i + chunk_size]
            res = requests.post(self.base_url, headers=self.headers, json=chunk, timeout=30)
            res.raise_for_status()
            
            data = res.json()
            if not data.get("success"):
                raise Exception(f"D1 Error: {data.get('errors')}")
            for res_item in data.get("result", []):
                meta = res_item.get("meta", {})
                total_rows += meta.get("rows_written", meta.get("changes", 0))
                
        self.rowcount = total_rows
        return self

    def fetchall(self):
        return self._results
        
    def fetchone(self):
        if self._results:
            return self._results.pop(0)
        return None

class D1Connection:
    def __init__(self, account_id, db_id, api_token):
        self.account_id = account_id
        self.db_id = db_id
        self.api_token = api_token
        
    def cursor(self):
        return D1Cursor(self.account_id, self.db_id, self.api_token)
        
    def commit(self):
        pass
        
    def close(self):
        pass

def get_connection():
    if DB_MODE == "PROD":
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "3b6e853a302909cc7e6e38bf2010af9c")
        db_id = os.environ.get("CLOUDFLARE_D1_DATABASE_ID", "3ef29370-faeb-409f-b4ec-e0ddef604c6c")
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "cfut_1Dv1wyy0dOWHGTN3UkQ3SSfHyif0yO8AB0ZuvAE90b48d928")
        
        if not account_id or not api_token:
            raise ValueError("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN must be set for PROD mode.")
            
        return D1Connection(account_id, db_id, api_token)
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Create movies table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS movies (
        movie_id TEXT PRIMARY KEY,
        title TEXT,
        language TEXT,
        tollybo_movie_id INTEGER
    )
    ''')
    
    # Create locations table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS locations (
        city_id INTEGER PRIMARY KEY,
        city_name TEXT,
        state_name TEXT
    )
    ''')
    
    # Create theaters table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS theaters (
        theater_id TEXT PRIMARY KEY,
        city_id INTEGER,
        name TEXT,
        FOREIGN KEY (city_id) REFERENCES locations (city_id)
    )
    ''')
    
    # Create shows table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shows (
        show_id TEXT PRIMARY KEY,
        theater_id TEXT,
        movie_id TEXT,
        screen_name TEXT,
        show_time DATETIME,
        show_date DATE,
        is_finalized BOOLEAN DEFAULT 0,
        FOREIGN KEY (theater_id) REFERENCES theaters (theater_id),
        FOREIGN KEY (movie_id) REFERENCES movies (movie_id)
    )
    ''')
    
    # Create show_metrics table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS show_metrics (
        metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
        show_id TEXT,
        timestamp DATETIME,
        capacity INTEGER,
        occupancy INTEGER,
        net_collection DECIMAL(10,2),
        FOREIGN KEY (show_id) REFERENCES shows (show_id)
    )
    ''')
    
    # Create show_metric_prices table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS show_metric_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_id INTEGER,
        ticket_price DECIMAL(10,2),
        capacity INTEGER,
        occupancy INTEGER,
        FOREIGN KEY (metric_id) REFERENCES show_metrics (metric_id)
    )
    ''')
    
    # Indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_shows_date ON shows(show_date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_shows_theater ON shows(theater_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_shows_movie ON shows(movie_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_metrics_show ON show_metrics(show_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_metric_prices_metric ON show_metric_prices(metric_id)')
    
    cursor.execute("PRAGMA table_info(movies)")
    columns = [info['name'] for info in cursor.fetchall()]
    if 'tollybo_movie_id' not in columns:
        cursor.execute("ALTER TABLE movies ADD COLUMN tollybo_movie_id INTEGER")
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_movies_tollybo_movie_id ON movies(tollybo_movie_id)')
        

    cursor.execute("PRAGMA table_info(locations)")
    columns = [info['name'] for info in cursor.fetchall()]
    if 'city_key' not in columns:
        cursor.execute("ALTER TABLE locations ADD COLUMN city_key TEXT")
        
    cursor.execute("PRAGMA table_info(theaters)")
    columns = [info['name'] for info in cursor.fetchall()]
    if 'lat' not in columns:
        cursor.execute("ALTER TABLE theaters ADD COLUMN lat REAL")
        cursor.execute("ALTER TABLE theaters ADD COLUMN lon REAL")
        cursor.execute("ALTER TABLE theaters ADD COLUMN address TEXT")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
