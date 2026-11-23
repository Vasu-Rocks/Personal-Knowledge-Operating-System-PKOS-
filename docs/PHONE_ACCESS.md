# Using PKOS from your phone

PKOS can be used from a phone's browser while it runs on your laptop - nothing to install on the phone. Your
documents, chats, memories and the AI stay on the laptop; the phone only shows the screens. (How it works and why:
[08_PHONE_ACCESS_PLAN.md](08_PHONE_ACCESS_PLAN.md).)

## What you need

- PKOS 0.7.0 or later running on the laptop.
- The phone and the laptop on the **same network**. Easiest: the laptop's own hotspot, so no router is needed:
  **Windows Settings > Network & internet > Mobile hotspot > On**, then join that Wi-Fi on the phone (its name and
  password are shown there). The same home Wi-Fi works too, and so does the phone's hotspot with the laptop joined.
- Bluetooth: a phone browser cannot open a website over plain Bluetooth. Bluetooth tethering (a "Bluetooth network")
  works like a slow Wi-Fi; the hotspot is the better choice.

## First time: pair the phone (once per phone)

1. On the laptop, open PKOS > **Settings > Phone access** and tick **Let paired phones on this network use PKOS**.
   - Windows may ask whether PKOS may communicate on networks. Allow it; for the laptop's hotspot also tick
     **Public networks** (Windows usually treats a hotspot as public).
2. Click **Pair a phone**. A QR code and a 6-digit code appear, valid for 5 minutes and for one phone.
   - Laptop on more than one network? Pick the one the phone is on under the QR code ("Mobile hotspot", "Wi-Fi").
3. On the phone, scan the QR code with the camera app and open the link.
   - Or type the address shown under "Address to open on a paired phone" (for example `https://192.168.137.1:47100`)
     into the browser and enter the 6 digits.
4. The browser warns **"Your connection is not private"** (Chrome) or **"This connection is not private"** (Safari).
   That is expected here: PKOS encrypts the connection with its own certificate, which no public authority has
   signed. Choose **Advanced > Proceed** (Chrome) or **Show Details > visit this website** (Safari).
   If you want to be sure it is your laptop: tap the warning's certificate details; its fingerprint starts with the
   code shown on the laptop next to "The certificate's code starts with".
5. The laptop shows **"Paired: Android phone · Chrome"** (or similar). Log in on the phone with your PKOS account, or
   create one there; the account and everything in it live on the laptop.

Tip: in the phone browser's menu choose **Add to Home screen** for a PKOS icon that opens full-screen.

## Every day

- Make sure PKOS is running on the laptop and **Phone access** is on, and that the phone is on the same network.
- Open the bookmark or home-screen icon. The address stays the same as long as the laptop's address does (the
  Mobile hotspot's is always `192.168.137.1`).
- The phone has three tabs at the bottom: **Chat**, **Sources** (the passages behind an answer) and **Library**
  (documents and chats). The arrow left of the question box asks by voice or from a photo of notes.
- Keep the laptop awake and plugged in; if it sleeps, the phone shows that PKOS on the laptop cannot be reached.

## What a phone can and cannot do

| On a phone | Only on the laptop |
|---|---|
| Ask questions, chats, voice and photo questions | Choosing the AI model, API keys, downloading models |
| Upload and delete documents | Backups, restore, importing another PKOS |
| Memories and memory settings, the knowledge map | Phone access itself (pairing, removing phones) |

## Safety

- **Off until you switch it on**; switching it off or closing PKOS disconnects phones at once.
- **Only paired phones get in.** Another device on the same Wi-Fi sees only the pairing page. A pairing code works
  once, for 5 minutes, and stops after 5 wrong tries; 10 wrong codes from one device block it for 10 minutes.
- **Remove a phone** you lost or no longer use: Settings > Phone access > Paired phones > Remove. It is disconnected
  immediately and has to pair again.
- 5 wrong passwords from one phone make that phone wait 10 minutes.
- Everything between phone and laptop is encrypted; on a shared Wi-Fi (college, café) others cannot read it.

## If something does not work

| Problem | What to do |
|---|---|
| The phone cannot open the address (it loads forever) | Same network? Windows Firewall: Windows Security > Firewall & network protection > Allow an app through firewall > PKOS: tick Private and Public. |
| "Another program is using the port for phone access" | Something else uses port 47100: close it or restart the laptop. |
| The certificate warning came back | The laptop joined another network, or PKOS renewed its certificate (yearly): accept it once more. |
| "This device is not paired" | The phone was removed, or the browser's cookies were cleared: pair it again. |
| Voice: "Voice needs the secure (https) address" | Open the `https://` address, not `http://`. |
| Voice: microphone blocked | Allow the microphone for the PKOS address in the browser's site settings (the icon left of the address). |
| iPhone photo: "HEIC photos cannot be read" | Use "Take a photo of notes", or Settings > Camera > Formats > Most Compatible. |

## Checklist for a first try with your phone

Tick these off the first time; they are the parts that could not be tested without a real phone.

- [ ] Laptop: Mobile hotspot on; phone joined it.
- [ ] Laptop: Phone access switched on; Windows asked about the firewall and you allowed it (Public ticked).
- [ ] Phone: the QR code opened the PKOS address; the "not private" warning appeared once and you proceeded.
- [ ] Laptop: "Paired: <your phone>" appeared.
- [ ] Phone: logged in; a question was answered, the answer streamed in word by word.
- [ ] Phone: tapping a citation ("Chunk 1") opened the Sources tab at that passage.
- [ ] Phone: "Take a photo of notes" opened the back camera, and the photo's text came into the question box.
- [ ] Phone: "Ask by voice" asked for the microphone, recorded, and the words came into the question box.
- [ ] Phone: Library > upload a PDF or a photo; it appears on the laptop too.
- [ ] Phone: Add to Home screen; the icon opens PKOS full-screen.
- [ ] Laptop: Remove the phone; the phone shows the pairing page on its next tap. Pair it again if you keep using it.

If one of them fails, note which one and what the phone showed (a screenshot helps), and the laptop's
Settings > This computer > Copy diagnostics.
