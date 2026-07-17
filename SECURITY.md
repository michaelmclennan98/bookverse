# Security

## API keys

Never commit API keys, passwords, PINs, `.env`, or `.streamlit/secrets.toml`.
Use Streamlit Community Cloud's Secrets settings for deployed apps.

If a key has ever appeared in a public repository, screenshot, message, log, or committed file, revoke it and create a new restricted key in Google Cloud.

## Profile PINs

BookVerse profile PINs are intended as a lightweight local separation mechanism, not production-grade authentication. Do not treat them as secure internet authentication.

## Public deployment warning

The current app uses SQLite. This is suitable for local use and a private demonstration, but Streamlit Community Cloud's local filesystem is not a durable multi-user database. For a public product, replace SQLite with hosted PostgreSQL or another managed database and add proper authentication.
