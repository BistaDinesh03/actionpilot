# ActionPilot extension

Manifest V3 recorder for ActionPilot.

1. Start the FastAPI backend at `http://127.0.0.1:8000`.
2. Run `npm install` and `npm run build` in this directory.
3. Open `brave://extensions` (or `chrome://extensions`).
4. Enable **Developer mode**.
5. Choose **Load unpacked** and select this `extension` folder.
6. Pin **ActionPilot** to the toolbar.

Use the popup to start and stop teaching, or start from the ActionPilot app's
**Teach** page. If the popup shows **Ready to teach**, the extension is
connected.

The recorder sends only normalized browser actions to the local API.
Password-like fields and values are skipped. Cookies, headers, credentials,
and browser storage are never read.
