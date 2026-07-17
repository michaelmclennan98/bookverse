# Deploy BookVerse to Streamlit Community Cloud

## Before deployment

1. Confirm `GOOGLE_BOOKS_API_KEY` is not present in any tracked file.
2. Confirm `.streamlit/secrets.toml` is ignored by Git.
3. Run `pytest -q` locally.
4. Push the repository to GitHub.

## Community Cloud settings

- Repository: your BookVerse GitHub repository
- Branch: `main`
- Main file path: `app.py`
- Python: choose 3.11 or 3.12
- App URL: choose an available `streamlit.app` subdomain

## Secrets to paste into Community Cloud

```toml
GOOGLE_BOOKS_API_KEY = "your_new_google_books_key"
OPEN_LIBRARY_CONTACT = "your-email@example.com"
BOOKVERSE_HTTP_TIMEOUT = "15"
BOOKVERSE_DATA_DIR = "data"
```

## Important data limitation

The deployed app can write to SQLite while its container is running, but local files may be reset when the app restarts, sleeps, rebuilds, or is redeployed. This means profiles and libraries are not guaranteed to persist on Community Cloud.

For a public or long-term deployment, migrate profile and library storage to hosted PostgreSQL or Supabase before inviting users.
