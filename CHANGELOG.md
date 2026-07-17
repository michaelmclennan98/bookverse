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
