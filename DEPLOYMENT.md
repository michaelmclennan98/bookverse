# Deploy BookVerse to Streamlit Community Cloud

## 1. Upload the repository

Push the complete folder to GitHub. Set the Streamlit main file to `app.py`.

## 2. Create private Supabase storage

Create a private bucket named `bookverse-data`. BookVerse stores a consistent SQLite snapshot named `bookverse.db` in that bucket.

## 3. Add Streamlit secrets

```toml
GOOGLE_BOOKS_API_KEY = "your_google_books_key"
OPEN_LIBRARY_CONTACT = "your-email@example.com"
BOOKVERSE_HTTP_TIMEOUT = "10"
BOOKVERSE_DATA_DIR = "data"

SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_your_key"
SUPABASE_STORAGE_BUCKET = "bookverse-data"
SUPABASE_DATABASE_FILE = "bookverse.db"
```

Use the Supabase secret key, not the publishable browser key. Never put either secret in a tracked file.

## 4. Test persistence

1. Create or unlock a profile.
2. Add a book.
3. Confirm `bookverse.db` appears in the Supabase bucket.
4. Reboot the Streamlit app.
5. Confirm the profile and book remain available.

## 5. Performance behaviour

Recommendation scans are manual. Fast mode is the default and uses fewer starting books and requests. Deep mode searches more widely. Successful results are saved per profile and remain visible until the reader explicitly scans again.
