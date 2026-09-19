# ActionPilot Chrome Recorder

1. Start the FastAPI backend at `http://127.0.0.1:8000`.
2. Run `npm install` and `npm run build` in this directory.
3. Open `chrome://extensions`.
4. Enable Developer mode.
5. Choose **Load unpacked** and select the `extension` directory.
6. Open ActionPilot and start a teaching session, or use the extension popup to start one.

The recorder sends only normalized browser actions to the local API. Password-like fields and values are skipped. Cookies, headers, credentials, and browser storage are never read.
