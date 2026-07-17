# BookVerse

![BookVerse logo](assets/logo_full.png)

BookVerse is a Streamlit book-discovery app with live Google Books and Open Library search, Book DNA recommendations, profiles, shelves, ratings, reading progress, personalised picks, mobile controls, batch library actions, and an interactive bookcase.

## Main features

- Search by title, author, genre, ISBN, or natural-language description
- Similar-book recommendations using genre, audience, format, themes, tone, and content intensity
- Personalised recommendations learned from top books, saved books, shelves, and ratings
- PIN-separated local profiles
- Want to Read, Reading, Read, DNF, custom shelves, reviews, and progress
- Interactive bookcase with clickable spines
- Desktop and mobile navigation controls
- Google Books plus Open Library catalogue merging
- English-language recommendation filtering
- SQLite local storage, JSON backup, and CSV export

## Important deployment warning

BookVerse currently stores profiles and libraries in SQLite. This is reliable for local use. Streamlit Community Cloud can run the app, but its local filesystem is not intended as durable multi-user storage. Profiles and library changes may be lost after a restart, rebuild, sleep cycle, or redeployment.

Use the Community Cloud version as a demonstration or private test. Before a public launch, move data to hosted PostgreSQL or Supabase and replace local PINs with proper authentication.

## Quick local setup on macOS

```bash
cd ~/Downloads/bookverse_streamlit
chmod +x scripts/setup_mac.sh scripts/run_mac.sh
./scripts/setup_mac.sh
```

Open `.streamlit/secrets.toml` and enter:

```toml
GOOGLE_BOOKS_API_KEY = "your_google_books_api_key"
OPEN_LIBRARY_CONTACT = "you@example.com"
BOOKVERSE_HTTP_TIMEOUT = "15"
BOOKVERSE_DATA_DIR = "data"
```

Then run:

```bash
./scripts/run_mac.sh
```

The normal local address is `http://localhost:8501`.

## Manual local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p .streamlit data
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
streamlit run app.py
```

## GitHub preparation

This package is already prepared with:

- `.gitignore` excluding API keys, secrets, databases, virtual environments, and backups
- `.env.example` and `.streamlit/secrets.example.toml`
- `requirements.txt` in the repository root
- GitHub Actions tests under `.github/workflows/tests.yml`
- `LICENSE`, `SECURITY.md`, `DEPLOYMENT.md`, and a complete upload/deployment guide
- No embedded Google Books API key

Read [GITHUB_AND_STREAMLIT_GUIDE.md](GITHUB_AND_STREAMLIT_GUIDE.md) before uploading.

## Tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

GitHub Actions also runs the tests automatically for pushes and pull requests.

## Repository structure

```text
bookverse_streamlit/
├── app.py
├── bookverse/
│   ├── api_clients.py
│   ├── cache.py
│   ├── config.py
│   ├── database.py
│   ├── language_utils.py
│   ├── models.py
│   ├── personalization.py
│   ├── recommender.py
│   ├── smart_search.py
│   └── views.py
├── assets/
├── data/.gitkeep
├── tests/
├── scripts/
├── .github/workflows/tests.yml
├── .streamlit/config.toml
├── .streamlit/secrets.example.toml
├── requirements.txt
├── requirements-dev.txt
├── DEPLOYMENT.md
├── SECURITY.md
└── GITHUB_AND_STREAMLIT_GUIDE.md
```

## Secrets

The application checks settings in this order:

1. Environment variables
2. Streamlit secrets
3. Safe default values

Never commit `.streamlit/secrets.toml` or a real `.env` file.

## Licence

MIT. See [LICENSE](LICENSE).
