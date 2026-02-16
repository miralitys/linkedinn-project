# MyVOICE Chrome Extension

This is a separate Chrome Extension project that saves LinkedIn posts into your MyVOICE backend.

## What is included

- `manifest.json` (MV3)
- Popup UI to:
  - detect current LinkedIn post URL
  - load contacts from `/people`
  - extract post data directly from LinkedIn tab DOM
  - save post via `/posts`
- Options page to configure backend URL
- Context menu on LinkedIn (`Save to MyVOICE`)

## Backend endpoints used

- `GET /people`
- `POST /posts`
- `GET /login` (for session auth helper)

## Load extension in Chrome

1. Open `chrome://extensions`
2. Enable `Developer mode`
3. Click `Load unpacked`
4. Select this folder:
   - `/Users/ramisyaparov/Linked inn project/chrome-extension-myvoice`

## First setup

1. Open extension options and set backend URL (default: `http://127.0.0.1:8000`)
2. Click `Open Login` and sign in to MyVOICE
3. Open a LinkedIn post
4. Open extension popup and click `Parse and Save`

## Notes

- The extension expects your MyVOICE backend to be running and accessible from Chrome.
- If popup shows `401`, you are not logged in to backend for the configured URL.
- LinkedIn URL must be a post URL (`/feed/update/...` or `/posts/...`).
