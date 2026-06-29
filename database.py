import sqlite3
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'collections.db')

def get_connection():
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
        language TEXT
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
