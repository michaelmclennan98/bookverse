# BookVerse v21.1

- Fixed recommendation refreshes returning no usable matches after the v21 request-budget changes.
- Added seven-day per-seed candidate pools so repeat scans rerank saved catalogue data instead of repeating provider calls.
- Increased the Google-first scan budget while reducing wasteful author-wide and duplicate catalogue searches.
- Stopped one transient Google timeout or 5xx response from placing every recommendation worker into a global cooldown.
- Refilters every saved recommendation set against the current hard rules before it is displayed.
- Automatically hides legacy recommendations with missing descriptions, excluded work types, wrong languages or other rule violations.
- Preserves the last valid set when providers are unavailable without showing duplicated or contradictory provider warnings.
- Added stronger Book DNA evidence checks to reject broad keyword-only matches while retaining genuine adjacent recommendations.
- Preserved manual scans, profile-specific saved results, Supabase data, v21 settings and all existing features.

# BookVerse v21

- Added profile-specific hard recommendation rules for language, audience, descriptions, ratings, length, publication years, series status and excluded book types.
- Added a diversity control with author and primary-genre caps so scans can be tightly focused or deliberately varied.
- Added strict shared request budgets: Fast mode allows up to 10 Google Books and 3 Open Library requests; Deep allows up to 18 and 7.
- Added transparent scan reports showing duration, request usage, candidates checked, already-saved removals, hard-rule rejections, feedback exclusions and weak-match removals.
- Added visible Book DNA and a points-based match breakdown on every personalised recommendation card.
- Expanded negative learning with wrong genre, too old, too long, too short, too much romance, not dark enough and too extreme feedback.
- Added a Recommendation Memory manager to remove one feedback record or clear all saved recommendation feedback.
- Added Choose My Next Book, which narrows the saved recommendation set to three finalists without running another catalogue scan.
- Added a Library Health tab with missing-metadata counts and safe one-book metadata repair that preserves library state.
- Preserved manual refresh, profile isolation, the existing Supabase database, bulk imports, top navigation, bookcase and all v20.1 safeguards.

# BookVerse v20.1

- Prevents Open Library request bursts with a shared cooldown and rate limiter.
- Uses Google Books first and Open Library only as a controlled fallback.
- Removes repeated provider-error URLs from the interface.
- Rejects weak niche matches such as textbooks and grammar manuals.
- Ranks the strongest evidence first and lowers unnecessary enrichment calls.
- Keeps manual refresh and per-profile saved recommendation sets unchanged.

# BookVerse v20

- Added manual Fast and Deep recommendation scans. Discover no longer starts a scan automatically.
- Saved each profile’s last completed recommendation set in cloud-backed user settings.
- Parallelised catalogue providers, recommendation seed scans, candidate enrichment and bulk matching.
- Added a persistent SQLite catalogue cache with expiry and diagnostics.
- Added detailed recommendation feedback including positive signals, rejected books, hidden authors, already-read editions, romance reduction, intensity and lighter-read preferences.
- Added Mood Finder, CSV imports, ISBN quick add and phone-camera ISBN barcode scanning.
- Added reading sessions, journals, quotations, personal tags, content warnings and audiobook progress.
- Added format, ownership, reread and series tracking.
- Added series progress, missing-volume warnings, shortlists, comparisons and data-preserving duplicate-edition merging.
- Expanded reading statistics with favourite authors, genre ratings, monthly wrap-up, session time, reading pace, streaks, DNF rate, completion speed and yearly projection.
- Added cloud, cache and scan diagnostics.
- Added backup format v3 while retaining v1 and v2 restore support.
- Preserved the existing top navigation, bookcase, profiles, Supabase sync and catalogue workflows.

# BookVerse v19.5

- Moved the phone-control toggle and panel lower down the mobile screen so they no longer sit against or underneath the browser/Streamlit top controls.
- Kept the control sticky with iPhone safe-area spacing, so it remains reachable while scrolling.
- Added a rounded mobile control surface instead of attaching it directly to the top edge.

# BookVerse v19.4

- Added persistent **Show phone controls** fallback controls based on the working Frog dashboard pattern.
- Added staged page navigation: choose a page, then press **Go**; dropdown changes alone never navigate.
- Added a mobile profile selector with a secure Lock / switch profile option.
- Mobile navigation uses Streamlit session state rather than URL links, so the unlocked profile is preserved.
- Hidden the inaccessible desktop sidebar on narrow phone screens.
- Increased touch targets for buttons, checkboxes, inputs and selectors.
- Made the 15-book live shelf horizontally swipeable on phones.
- Made book-detail dialogs use the available phone width.
- Added iPhone safe-area padding.

# BookVerse v19.3

- Fixed personalised recommendation checkbox keys so bulk actions detect every selected book.
- Added an always-visible selected-book action bar with Want to Read, Mark as Read and Clear Selection.
- Changed the live bookcase to display up to 15 books on each shelf page.
- Added Previous 15 / Next 15 controls and a page counter for every shelf.
- Increased the main app width so 15 vertical book spines remain usable.

# BookVerse v19.1

- Restored visible descriptions directly on search and recommendation cards.
- Long descriptions show a useful preview immediately, with the complete synopsis available below it.
- View full details now hydrates the exact title and author from Google Books and Open Library before opening.
- A temporary catalogue error falls back to the current record instead of making the details button fail.
- Existing manual recommendation refresh, batch library actions, profiles and live bookcase remain unchanged.

# BookVerse v19

- Personalised recommendations rebuild only when Refresh from my library is clicked.
- Saving or rating books marks the current set as stale without freezing the page.
- Added multi-select recommendations with batch Want to Read and Read actions.
- Added a separate Next recommendation batch control.
- Rebuilt bookcase spine CSS so saved books are visible and readable.
- Library details now enrich sparse Read records from Google Books and Open Library.
