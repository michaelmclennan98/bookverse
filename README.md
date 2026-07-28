# BookVerse

![BookVerse logo](assets/logo_full.png)

BookVerse is a Streamlit reading and book-discovery app with durable Supabase-backed profiles, live Google Books and Open Library search, manual personalised recommendations, bulk imports, reading journals, series tracking, shortlists and advanced statistics.

## Version 20 highlights

- Website-style top navigation on desktop and mobile
- Manual recommendation scans that never run merely because a page reruns
- The last completed recommendation set is saved separately for every profile
- Fast and Deep recommendation modes
- Parallel provider, seed, candidate-enrichment and bulk-import requests
- Persistent catalogue cache stored in the BookVerse SQLite database
- Recommendation feedback: interested, more like this, not interested, hide book or author, already read another edition, less romance, more intensity and lighter reads
- Mood Finder with genre, intensity, romance, pace, rating and length controls
- Bulk title and author matching, phone-camera ISBN barcode scanning, ISBN quick add and Goodreads or StoryGraph-style CSV import
- Reading sessions, journal entries, quotations, personal tags and content warnings
- Format, ownership, audiobook progress and reread tracking
- Series tracker with missing-number warnings and next-book guidance
- Shortlists with side-by-side book comparison
- Duplicate-edition detection with data-preserving edition merging
- Expanded reading statistics, favourite authors, genre ratings, monthly wrap-up, streaks, completion time, reading pace and yearly projection
- Cloud, cache and scan diagnostics
- JSON backup format v3, while restoring v1 and v2 backups remains supported

## Main navigation

- **Discover**: saved recommendations, Fast or Deep scans, Mood Finder and catalogue search
- **Library**: bulk import, series tracker, shortlists, duplicate manager and interactive bookcase
- **Stats**: goals, shelves, categories, monthly finishes, sessions, streaks and formats
- **Settings**: taste profile, PIN changes, cloud status, scan history and cache controls

## Streamlit Community Cloud secrets

Paste these in **Manage app → Settings → Secrets**:

```toml
GOOGLE_BOOKS_API_KEY = "your_google_books_api_key"
OPEN_LIBRARY_CONTACT = "you@example.com"
BOOKVERSE_HTTP_TIMEOUT = "10"
BOOKVERSE_DATA_DIR = "data"

SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_your_key"
SUPABASE_STORAGE_BUCKET = "bookverse-data"
SUPABASE_DATABASE_FILE = "bookverse.db"
```

Never commit the secret key to GitHub.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p data
streamlit run app.py
```

The local address is normally `http://localhost:8501`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

The supplied build contains tests for profiles, backups, recommendations, catalogue matching, navigation, persistent caching, journals, series, feedback and shortlists.

## Storage model

BookVerse continues to use SQLite for its application data so the existing app remains compatible. `CloudLibraryDatabase` restores the SQLite file from a private Supabase Storage bucket at startup and uploads consistent snapshots after changes. The persistent catalogue cache is stored inside the same database and therefore travels with the cloud snapshot after completed scans and library writes.

This design is appropriate for a private or lightly shared Streamlit app. A high-concurrency public service should eventually move the tables to hosted PostgreSQL and use full hosted authentication.
