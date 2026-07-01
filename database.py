import psycopg2
import psycopg2.extras
import os
import urllib.parse
from dotenv import load_dotenv

# Load environment variables from .env file immediately and override any stale terminal exports
load_dotenv(override=True)

DB_MODE = os.environ.get("DB_MODE", "LOCAL").upper()

def get_connection():
    db_url = os.environ.get("DATABASE_URL")
        
    if not db_url:
        raise ValueError(f"DATABASE_URL for {DB_MODE} environment variable is not set.")
        
    parsed = urllib.parse.urlparse(db_url)
    qs = urllib.parse.parse_qs(parsed.query)
    schema = qs.get('schema', ['public'])[0]
    
    # Remove the query string so psycopg2 doesn't complain about invalid DSN parameter "schema"
    clean_db_url = urllib.parse.urlunparse(parsed._replace(query=""))
    
    # Connect with the schema in the search path
    conn = psycopg2.connect(clean_db_url, cursor_factory=psycopg2.extras.RealDictCursor, options=f"-c search_path={schema}")
    conn.autocommit = False
    return conn

def init_db():
    db_url = os.environ.get("DATABASE_URL")
        
    if not db_url:
        raise ValueError(f"DATABASE_URL environment variable is not set.")
        
    parsed = urllib.parse.urlparse(db_url)
    qs = urllib.parse.parse_qs(parsed.query)
    schema = qs.get('schema', ['public'])[0]
    
    # Remove the query string so psycopg2 doesn't complain about invalid DSN parameter "schema"
    clean_db_url = urllib.parse.urlunparse(parsed._replace(query=""))
    
    # Connect without strict search path to create schema
    conn = psycopg2.connect(clean_db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = True
    cursor = conn.cursor()
    
    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
    cursor.execute(f"SET search_path TO {schema};")
    
    # Create movies table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS movies (
        movie_id TEXT PRIMARY KEY,
        title TEXT,
        language TEXT,
        tollybo_movie_id INTEGER UNIQUE
    )
    ''')
    
    # Create locations table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS locations (
        city_id INTEGER PRIMARY KEY,
        city_name TEXT,
        state_name TEXT,
        city_key TEXT
    )
    ''')
    
    # Create theaters table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS theaters (
        theater_id TEXT PRIMARY KEY,
        city_id INTEGER,
        name TEXT,
        lat REAL,
        lon REAL,
        address TEXT,
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
        show_time TIMESTAMP,
        show_date DATE,
        is_finalized BOOLEAN DEFAULT FALSE,
        FOREIGN KEY (theater_id) REFERENCES theaters (theater_id),
        FOREIGN KEY (movie_id) REFERENCES movies (movie_id)
    )
    ''')
    
    # Create show_metrics table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS show_metrics (
        metric_id SERIAL PRIMARY KEY,
        show_id TEXT,
        timestamp TIMESTAMP,
        capacity INTEGER,
        occupancy INTEGER,
        net_collection DECIMAL(10,2),
        FOREIGN KEY (show_id) REFERENCES shows (show_id)
    )
    ''')
    
    # Create show_metric_prices table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS show_metric_prices (
        id SERIAL PRIMARY KEY,
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
    
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
