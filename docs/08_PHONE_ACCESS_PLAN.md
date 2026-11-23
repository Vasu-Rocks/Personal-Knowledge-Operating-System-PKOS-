# 08 - Phone access: use PKOS from a phone through the laptop

Status: planned 2026-11-23 (decisions in section 9). Built step by step, P1 to P5, one step per turn.

## 1. Goal

While PKOS runs on a laptop, a phone on the same network (the laptop's Mobile Hotspot, the phone's hotspot, or the
same Wi-Fi) opens PKOS in its browser - nothing to install - logs in and uses it: questions, chats, memories,
documents, photos and voice notes. **Everything stays on the laptop**: the documents, the database, the AI model and
every answer. The phone only shows the screens.

Rules that hold in every step:
1. **Off by default.** Nothing is reachable from the network until the user switches "Phone access" on in the laptop
   app; switching it off (or quitting PKOS) closes the door at once.
2. **Only paired phones get in** (decision P-Q1). A phone pairs once by scanning a QR code (or typing a 6-digit code)
   shown on the laptop; then it logs in as usual. A device that is not paired never even sees the login page. Paired
   phones are listed on the laptop and can be removed.
3. **The backend never listens on the network.** It stays on 127.0.0.1 exactly as today. The only door is a small
   phone server in the desktop app that checks the pairing and forwards allowed requests.
4. **Encrypted on the network** (decision P-Q2): the phone server uses https with a certificate PKOS makes itself, so
   nobody on the same Wi-Fi can read questions, answers or passwords, and the phone's microphone works.
5. **Laptop-only settings stay laptop-only** (decision P-Q4): the AI model and API keys, downloading or deleting
   models, backups, import and the data folder cannot be changed from a phone.

About Bluetooth: a phone browser cannot open a website over plain Bluetooth. Bluetooth *tethering* (PAN) creates a
small network between the two, and phone access works over it like over Wi-Fi, only slower. The recommended way is the
laptop's Mobile Hotspot (Windows Settings > Network > Mobile hotspot): no router needed, and the laptop's address on it
(usually 192.168.137.1) stays the same.

## 2. Current state

- Electron starts Postgres, Ollama and the backend, all on 127.0.0.1 with ports chosen at first start
  (`desktop/src/services.js`); the window loads the built web UI through the `app://` protocol (`desktop/src/main.js`).
- The web UI talks to `window.pkos.apiBase` (desktop) or `VITE_API_BASE_URL` (web) (`frontend/src/api.js`).
- Login: `POST /login` (no limit on failed attempts), `POST /register` open, JWT in `localStorage`.
- The screens are a three-pane desktop layout (documents | chat | X-Ray) with drag handles; nothing adapts to a
  phone-sized screen.
- Voice notes use `getUserMedia` + `MediaRecorder` (needs https off-localhost); photos use a file input.

## 3. How it works

```
 phone browser ──https──▶ phone server (Electron main, 0.0.0.0:47100)
                            │ 1. paired device?  no → pairing page only
                            │ 2. path allowed?   no → 403 "only on the laptop"
                            │ 3. static web UI, or forward /api/v1/* (streams SSE)
                            ▼
                          backend 127.0.0.1:<port>  (unchanged) ──▶ Postgres, Ollama (127.0.0.1)
```

- **Phone server** (`desktop/src/phone.js`): Node `https` server on all network interfaces, fixed port 47100 (so a
  bookmark keeps working), serving `frontend/dist` and forwarding `/api/v1/*` to the backend without buffering (answers
  stream token by token). Started and stopped by the switch; the choice is remembered.
- **Certificate**: made once by the bundled backend (`pkos-api --make-cert`, with the `cryptography` package it
  already ships; no new download) - a key and a self-signed certificate for the laptop's current network addresses,
  kept in the data folder; renewed when the addresses change. The phone shows a one-time "not private / not trusted"
  warning per address, which the user accepts. Optional: install the PKOS certificate on the phone once to never see
  the warning (documented, not required).
- **Pairing**: the laptop shows the address, a QR code (address + one-time code) and the same code as 6 digits. The
  code is valid for 5 minutes and one phone. A paired phone gets a random device key (256 bits) in a cookie
  (`HttpOnly`, `Secure`, `SameSite=Strict`); the laptop stores only its hash, with a name ("Android phone, Chrome"),
  the pairing time and the last time it was used. Remove = the key stops working at once.
- **Allowed from a phone** (allow-list in the phone server): login, sign-up (decision P-Q3), profile, documents
  (list, upload, delete), query, chats, memories and memory settings, voice and photo notes, the knowledge map and
  graph reads, reading the AI status. Everything else is refused with "This can only be changed on the laptop".
- **Login safety**: after 5 failed logins from one device within 10 minutes, that device waits 10 minutes; pairing
  codes: 5 wrong tries end the code. Logged in the desktop log (no passwords).
- **Phone layout**: below 768 px wide the screens become one column: a top bar (chat title, AI status, menu), tabs
  **Chat / Sources / Library** (Library = documents and chats), the question box at the bottom, the X-Ray panel as the
  Sources tab, touch-sized buttons. The same build serves laptop and phone; the phone is detected by screen width,
  and laptop-only parts of Settings are hidden when not running inside the desktop app.
- **Firewall**: the first time phone access is switched on, Windows asks whether PKOS may accept connections; the app
  explains this before it happens. Hotspot networks are usually "Public" in Windows, so both boxes may be needed; the
  app says so and the docs show how to change it later.

## 4. Data model

Nothing new in Postgres. In the desktop config (`config.json`, the existing sealed config):
`phoneAccess: { enabled, port, devices: [{ id, name, keyHash, pairedAt, lastSeenAt }] }`; the certificate and key in
`<data>/phone/` (key file readable by the user only).

## 5. Changes by area

- **Desktop** (`desktop/src`): new `phone.js` (server, forwarding, allow-list, pairing, device keys, rate limits),
  `main.js` (start/stop, IPC for the switch, devices, pairing codes), `preload.js` (the new IPC), tests in
  `desktop/test/phone.test.js` (forwarding incl. streaming, refused paths, pairing, device removal, rate limits).
- **Backend**: `desktop_entry.py --make-cert <dir> <ip,...>` (certificate); no API changes. A request through the
  phone server carries `X-PKOS-Via: phone` (set by the phone server, never trusted from outside) for the logs.
- **Frontend**: `api.js` (same-origin API base when served to a phone), a phone layout in `Dashboard.jsx` / `VaultView.jsx`
  (tabs below 768 px), `SettingsView.jsx` (Phone access section on the laptop: switch, address, QR code, 6-digit code,
  paired phones; laptop-only sections hidden on a phone), `MediaInput.jsx` (camera on phones:
  `capture="environment"`), a small web app manifest so "Add to Home screen" gives a PKOS icon.
- **Packaging**: the certificate command in the backend build; no new runtime; docs.

## 6. Work plan, step by step (one step per turn)

| Step | Work | Done when |
|---|---|---|
| P1 | Phone server: switch (off by default), https with PKOS's own certificate, web UI + API forwarding (streaming), backend still loopback-only, allow-list of paths | Desktop tests; from the laptop's own network address in a browser: the UI loads, login and a streamed answer work, refused paths say why |
| P2 | Pairing and safety: QR code + 6-digit code, device keys, paired-phones list with Remove, login and code rate limits | Tests (unpaired = pairing page only, removed phone locked out, limits); the QR library is added only after you approve that download |
| P3 | Phone layout: one column, Chat / Sources / Library tabs, touch sizes, laptop-only settings hidden | Component tests at 375 px; checked in the browser pane in phone size |
| P4 | Phone media and home-screen icon: camera photos, voice notes over https, web app manifest | Tests; voice and photo notes checked from the phone-sized browser over https |
| P5 | Docs (user guide with hotspot steps and the certificate warning explained), version 0.7.0, packaged app check | Packaged app: phone access from another device on the hotspot; your own check with your phone using a short checklist |

What I cannot do myself: hold your phone. Steps P1-P4 are checked from this laptop (its network address, phone-sized
browser); P5 ends with a short checklist for you to try on your phone.

### Step P1 results (2026-11-23, dev app)

Built: `desktop/src/phone.js` (https server on port 47100, web UI with a `pkos-api` same-origin marker, API forwarding
without buffering, allow-list, adapter list without virtual/VPN adapters, certificate renewal), `core/phone_cert.py` +
`desktop_entry.py --make-cert` (EC P-256, 397 days, the laptop's addresses), the switch in Settings > Phone access
(addresses with Copy, the certificate code to compare, the "not private" warning and the Windows Firewall prompt
explained), `frontend/src/api.js` (same address when served to a phone). Tests: 13 desktop (allow-list, addresses,
certificate renewal, static files and path escapes, forwarding and headers, streaming, refused paths, phone going away,
engine down, switching off mid-answer), 5 backend, 3 frontend.

In the dev app: switching on took 0.4 s including the certificate. From this laptop through its Mobile Hotspot address
(192.168.137.1) and its Wi-Fi address, trusting only PKOS's certificate (not skipping the check): the page, sign-up,
login, a streamed answer, and "This can only be changed on the laptop" for AI settings and import. The backend stayed
unreachable on the Wi-Fi address. A phone-sized browser (390 x 844) logged in through the real login screen and got an
answer; the chat screen is the laptop layout squeezed (P3). Switched off, the address no longer answers and the choice
is remembered. Not yet tested: a real phone through Windows Firewall (P5). **Not to be released before P2**: until
pairing exists, anyone on the same network can reach the login page while the switch is on.

### Step P2 results (2026-11-23, dev app)

Built: `desktop/src/pairing.js` (6-digit one-time codes, 5 minutes, one phone, 5 tries; per-address block after 10
wrong codes in 10 minutes; device keys of 256 bits in an `HttpOnly; Secure; SameSite=Strict` cookie, only their SHA-256
kept in `config.json` with name, pairing time and last use; per-phone block after 5 wrong passwords in 10 minutes; the
pairing page), the phone server's gate (an unpaired device gets the pairing page, its API calls 401 and nothing reaches
the backend; `?pair=<code>` from the QR code or the typed code pairs; Remove closes the phone's open connections),
Settings > Phone access (Pair a phone: QR code via `qrcode-generator` 2.0.4 (MIT, no dependencies; approved
2026-11-23), the code as "975 676", a countdown, the network the QR code points at, Cancel; "Paired: <phone>"; paired
phones with last use and Remove). Tests: 5 pairing rules + 5 server-level (49 desktop in all), 5 frontend.

In the dev app with a phone-sized browser through the hotspot address: the pairing page only; a wrong code answered
"That code is not right. 4 tries left."; the QR code's link paired it, then login and an answer; reopened later it was
still paired; the laptop showed "Paired: Android phone · Chrome"; after Remove on the laptop the phone was back to the
pairing page. Found and fixed: the countdown started from when Settings was opened (showed 5:27 for a 5-minute code).

### Step P3 results (2026-11-23, dev app, phone-sized browser 390 x 844)

Built: below 768 px (`lib/useIsPhone.js`) the three panels stay mounted and one is shown at a time, chosen with a
bottom tab bar Chat / Sources (n) / Library; opening or starting a chat in Library shows Chat, tapping a citation shows
Sources with the passage highlighted; a shorter header and a compact AI badge (model name only); 16 px inputs (phones
zoom into smaller ones); dialogs fill the screen; text fields get their own line; the Library tab refreshes the
document list when opened; `100dvh` so the browser's address bar does not hide the question box. On a phone (served by
the phone server) Settings shows the AI model read-only ("llama3.2 · on the laptop") without Save or "Run setup
again", and the AI setup wizard never opens. Tests: 4 layout + 2 phone-settings (82 frontend in all).

Found and fixed on the way, both also affecting the laptop:
- **Citations were plain links.** react-markdown 10 drops links with unknown schemes, so `citation://` links lost
  their target and "[Chunk 1]" showed as an underlined link, not the clickable badge. Now `citation://` is let through
  (`urlTransform`), every other URL keeps the safe default.
- **A tap on a citation did nothing.** The Markdown link renderer was a new function on every render, so react-markdown
  remounted the badge when hovering changed the highlight; a phone tap (hover and click at once) hit the removed badge.
  The renderer is now one stable component (`components/chats/CitationLink.jsx`) that reads its state from a context.

In the phone-sized browser through the hotspot address: logged in, the page exactly as wide as the screen (374 px, no
sideways scrolling), an answer with a "Chunk 1" badge, tapping it opened Sources with the passage, Library listed the
document, Settings fit the screen with the AI model read-only and no Save. The laptop layout was unchanged.

### Step P4 results (2026-11-23, dev app, phone-sized browser)

Built: the ⌄ menu on a phone offers "Take a photo of notes" (`capture="environment"`: straight to the back camera),
"Choose a photo of notes" (gallery) and "Ask by voice"; a camera photo without a file extension is named by its type;
HEIC photos get an explanation instead of a failure on the laptop; voice says why it is unavailable (not https, or a
browser that cannot record) instead of failing, and a blocked microphone points at the browser's site settings, not
Windows; "tap the square to stop". Home screen: `manifest.webmanifest` (standalone, PKOS colours), 192/512 px icons
and an Apple touch icon made from the desktop icon, theme and Apple meta tags, safe-area padding below an iPhone's
status bar. The phone server serves the manifest and icons without pairing (browsers fetch them without cookies; they
hold nothing private), a missing one answers 404 rather than the app, and only hashed `/assets/` files are cached for
a year. Tests: 5 frontend (82 -> 87), 1 desktop (50).

Through the phone server with PKOS's certificate accepted: the page is a secure context (so the microphone is
allowed); recording through the real menu with a fake microphone (a tone) was sent and answered "No speech was heard";
a spoken question made with Windows text-to-speech came back as "Who visits the Glacier station every Tuesday?"; a
photo of notes given to the camera input with no extension filled the question box ("My e exam is on 14 February
Revise paging and deadlocks" - the OCR slip is the model's); the manifest (PKOS, standalone, 2 icons) and the icon
loaded without cookies. Not checkable here: a real phone camera and microphone, and the "Add to Home screen" prompt
itself (P5 checklist). Chrome does not install a full app (service worker) for a site whose certificate it does not
trust, so "Add to Home screen" makes a shortcut that opens PKOS full-screen; that is all PKOS needs (it never works
offline: the laptop does the work).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Someone on a shared Wi-Fi reaches PKOS | Off by default; pairing required before the login page; https; rate limits; remove devices |
| Windows Firewall blocks the phone | The app explains the Windows prompt first; docs show how to allow PKOS later |
| The certificate warning confuses users | One-time per address, explained on the laptop screen next to the QR code; optional trusted install |
| The laptop's address changes (other Wi-Fi) | Shown fresh each time; certificate renewed; Mobile Hotspot keeps 192.168.137.1 |
| The laptop sleeps, phone loses PKOS | The phone shows "PKOS on the laptop is not reachable"; docs: keep the lid open / plugged in |
| A phone changes laptop settings | Allow-list in the phone server, not only hidden buttons |
| Long answers on a slow network | Answers stream as today; uploads show progress; size limits as on the laptop |

## 8. Out of scope (for now)

Access over the internet (outside the shared network), several laptops syncing, a native phone app, offline use on
the phone, push notifications.

## 9. Decisions (2026-11-23)

| # | Question | Decision |
|---|---|---|
| P-Q1 | How does a phone get in? | QR code (or 6-digit code) pairing once, then login; unpaired devices see only the pairing page |
| P-Q2 | Voice notes on the phone? | Yes: https with PKOS's own certificate (one-time warning on the phone) |
| P-Q3 | Who can log in from a phone? | Existing accounts, and sign-up is allowed on a paired phone (the new account's data is on the laptop) |
| P-Q4 | What can be changed from a phone? | Everyday use only; AI model, API keys, models, backups, import and data folder stay laptop-only |
