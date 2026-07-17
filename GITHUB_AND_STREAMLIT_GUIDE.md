# BookVerse: Complete GitHub and Streamlit Community Cloud Guide

This guide starts from the prepared `bookverse_streamlit` folder and covers local testing, secure GitHub upload, Streamlit Community Cloud deployment, updates, troubleshooting, and the current SQLite limitation.

## 1. What has already been prepared

The GitHub-ready package includes:

- The complete BookVerse application
- Logo and icon assets
- A root-level `app.py`
- A root-level `requirements.txt`
- A safe `.gitignore`
- No API key embedded in Python files
- Example secrets files only
- Automated tests
- A GitHub Actions test workflow
- MIT licence
- Security and deployment notes
- macOS setup and run scripts

Do not upload an older BookVerse ZIP that contains your API key. Use only this GitHub-ready package.

## 2. Rotate the exposed Google Books API key first

The previous key appeared in chat and in earlier local builds. Treat it as exposed.

1. Open Google Cloud Console.
2. Select the project containing the Books API.
3. Open APIs & Services, then Credentials.
4. Delete or disable the old API key.
5. Create a replacement key.
6. Restrict the replacement key to the Books API.
7. Keep the new key private.

Do not type the replacement key into `bookverse/config.py`, README files, GitHub commits, screenshots, or public messages.

## 3. Unzip the prepared package

On your Mac, download the GitHub-ready ZIP and place it in Downloads.

```bash
cd ~/Downloads
unzip -o bookverse_streamlit_github_deployment_ready.zip
cd bookverse_streamlit
```

Confirm the main files exist:

```bash
ls
```

You should see `app.py`, `bookverse`, `assets`, `requirements.txt`, `README.md`, and other project files.

## 4. Add local secrets safely

Create the private secrets file from the example:

```bash
mkdir -p .streamlit
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
open .streamlit/secrets.toml
```

Replace the example values:

```toml
GOOGLE_BOOKS_API_KEY = "PASTE_YOUR_NEW_KEY_HERE"
OPEN_LIBRARY_CONTACT = "your-email@example.com"
BOOKVERSE_HTTP_TIMEOUT = "15"
BOOKVERSE_DATA_DIR = "data"
```

Save the file. `.streamlit/secrets.toml` is excluded by `.gitignore`, so Git should not upload it.

## 5. Test the prepared app locally

### Easiest method

```bash
chmod +x scripts/setup_mac.sh scripts/run_mac.sh
./scripts/setup_mac.sh
./scripts/run_mac.sh
```

### Manual method

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` if the browser does not open automatically.

Check these items before uploading:

- BookVerse opens without an exception.
- Google Books shows as enabled.
- Search returns books.
- Profiles can be created and unlocked.
- Want to Read and Read actions work.
- The library bookcase opens book details.
- Mobile controls appear correctly on a phone-sized display.

Stop the app with Control + C in Terminal.

## 6. Run the automated tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Do not upload until the tests pass.

## 7. Check that no secrets will be uploaded

Run:

```bash
git status --ignored
```

After Git is initialised, `.streamlit/secrets.toml`, `.env`, `.venv`, and `data/bookverse.db` should appear as ignored rather than tracked.

You can also check the folder for the old API-key prefix:

```bash
grep -R "AIza" . --exclude-dir=.git --exclude=secrets.toml
```

The command should not find a real key in tracked files. It may find harmless example wording only if you added it yourself.

## 8. Create the GitHub repository

Use a simple repository name such as:

```text
bookverse-streamlit
```

On GitHub:

1. Sign in.
2. Click the plus button in the top-right.
3. Choose New repository.
4. Enter `bookverse-streamlit`.
5. Add a description such as `Personalised book discovery and recommendation app built with Streamlit`.
6. Choose Private while testing. You can make it public later.
7. Do not initialise it with a README, licence, or `.gitignore`, because those are already included.
8. Click Create repository.

Keep the GitHub quick-setup page open.

## 9. Upload using Terminal - recommended

From the project folder:

```bash
cd ~/Downloads/bookverse_streamlit
git init
git branch -M main
git add .
git status
git commit -m "Prepare BookVerse for GitHub and Streamlit deployment"
```

Add your own repository URL. Replace `YOUR_GITHUB_USERNAME`:

```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/bookverse-streamlit.git
git push -u origin main
```

GitHub may ask you to sign in through the browser or use a personal access token. Normal GitHub account passwords are not used for Git HTTPS authentication.

Refresh the repository page and confirm the files are visible.

## 10. Upload using GitHub Desktop - alternative

1. Install and sign in to GitHub Desktop.
2. Open File, then Add Local Repository.
3. Select `~/Downloads/bookverse_streamlit`.
4. If prompted, create a repository for the folder.
5. Review the changed files.
6. Enter a summary such as `Prepare BookVerse for deployment`.
7. Click Commit to main.
8. Click Publish repository.
9. Choose the repository name and privacy setting.
10. Click Publish Repository.

## 11. Upload using the GitHub website - least suitable

You can create an empty repository and use Add file, then Upload files. Drag the contents of `bookverse_streamlit` into the page and commit them.

This method is less reliable for hidden files and large folder structures. Terminal or GitHub Desktop is recommended.

## 12. Connect GitHub to Streamlit Community Cloud

1. Sign in to Streamlit Community Cloud using your GitHub account.
2. Authorise access to the repository when requested.
3. Open your Streamlit workspace.
4. Click Create app.
5. Select the BookVerse repository.
6. Select the `main` branch.
7. Set the main file path to:

```text
app.py
```

8. Choose an available app URL, such as `bookverse-jampin.streamlit.app`.
9. Open Advanced settings before deploying.

## 13. Configure Python and secrets

In Advanced settings:

- Select Python 3.11 or 3.12.
- Paste the following into Secrets, using your real replacement key and email:

```toml
GOOGLE_BOOKS_API_KEY = "YOUR_NEW_GOOGLE_BOOKS_KEY"
OPEN_LIBRARY_CONTACT = "your-email@example.com"
BOOKVERSE_HTTP_TIMEOUT = "15"
BOOKVERSE_DATA_DIR = "data"
```

Do not add quotation marks around the whole block. Paste it as TOML exactly as shown.

Click Save, then Deploy.

## 14. Watch the first deployment

Streamlit will:

1. Clone the GitHub repository.
2. Create a Linux Python environment.
3. Install packages from `requirements.txt`.
4. Load the secrets from Community Cloud.
5. Run `app.py`.

The first build can take several minutes. Use the deployment logs to inspect errors.

When successful, the app opens at your chosen `streamlit.app` address.

## 15. Test the deployed app

Check:

- The page loads on desktop and mobile.
- Google Books is enabled.
- Search works.
- Mobile controls are reachable.
- A profile can be created.
- Book details and recommendations open.
- The app does not display the API key in errors.

## 16. Critical SQLite limitation on Community Cloud

BookVerse currently stores data in:

```text
data/bookverse.db
```

That works reliably on your Mac. On Streamlit Community Cloud, local app storage is not a permanent hosted database. Data written while the app runs may disappear when the app restarts, sleeps, rebuilds, moves containers, or is redeployed.

Consequences:

- User profiles may disappear.
- PINs may disappear.
- Shelves and reading progress may disappear.
- Multiple users share the same app process and local database.
- Local PINs are not secure internet authentication.

The Community Cloud deployment is therefore suitable as a demonstration or private prototype, not yet as a dependable public multi-user service.

For production, the next upgrade should be:

1. Hosted PostgreSQL or Supabase for data.
2. Proper account authentication.
3. Per-user ownership enforced in the database.
4. Password reset and secure password hashing.
5. Database backups.

## 17. Update the live app later

After editing files locally:

```bash
cd ~/Downloads/bookverse_streamlit
git add .
git status
git commit -m "Describe the BookVerse update"
git push
```

Streamlit Community Cloud normally detects the new GitHub commit and rebuilds the app automatically.

Never commit `.streamlit/secrets.toml` or a database backup.

## 18. Change cloud secrets later

Open the deployed app, then Manage app or App settings. Open the Secrets section, edit the TOML values, save them, and reboot the app if required.

Use this process when rotating the Google Books key. Do not change the Python source code to rotate a secret.

## 19. Common deployment errors

### ModuleNotFoundError

A Python dependency is missing from `requirements.txt`.

Fix the file, commit, and push again.

### Google Books disabled

Check the Community Cloud Secrets section. Confirm the key name is exactly:

```text
GOOGLE_BOOKS_API_KEY
```

Confirm the Books API is enabled in the same Google Cloud project and the key is restricted to that API.

### App cannot find app.py

The main file path in Streamlit must be `app.py` because it is in the repository root.

### Database or profiles disappear

This is the expected SQLite persistence limitation on Community Cloud. Use hosted PostgreSQL or Supabase for permanent public storage.

### Deployment uses the wrong Python version

Python is chosen during deployment. To change it later, delete and redeploy the app with the correct version in Advanced settings.

### The repository is not visible to Streamlit

Reconnect GitHub permissions and allow Streamlit access to that repository or organisation.

### Build fails after dependency changes

Use only the root `requirements.txt` for production dependencies. Test locally with a fresh virtual environment before pushing.

## 20. Recommended final launch checklist

- New Google Books key created and old key revoked
- API key restricted to Books API
- No secrets in GitHub files or commit history
- Repository initially private
- Tests passing
- Local app tested from a fresh virtual environment
- Streamlit secrets configured
- Python 3.11 or 3.12 selected
- Deployed search tested
- Mobile controls tested
- SQLite limitations understood
- Public launch postponed until hosted database and real authentication are added

## Official reference pages

- Streamlit Community Cloud deployment: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- Streamlit deployment form: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Streamlit dependencies: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- Streamlit secrets: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- GitHub upload guide: https://docs.github.com/en/get-started/start-your-journey/uploading-a-project-to-github
- GitHub existing local project: https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
