# Xera Company Backend [1.60 - 1.75, Steam + Quest]

Open source, Nakama-free revival backend for **Animal Company 1.60 - 1.75**

Just a little gift to the community because people like to copy my stuff, so I would rather just let everyone use it 🤷‍♂️

This is months of reverse-engineering work, given away for free. If you use it, **please star the repo**, that's all I ask!

Star it here: https://github.com/Xera-Games-LLC/Xera-Company-Backend

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Overview](#overview)
- [1. Get the target APK](#1-get-the-target-apk)
- [2. Unpack the APK](#2-unpack-the-apk)
- [3. Patch the server URL](#3-patch-the-server-url)
- [4. Patch the Meta App ID](#4-patch-the-meta-app-id)
- [5. Change the package name](#5-change-the-package-name)
- [6. Repack and sign the APK](#6-repack-and-sign-the-apk)
- [7. Host the backend on PythonAnywhere](#7-host-the-backend-on-pythonanywhere)
- [8. Configure your server settings](#8-configure-your-server-settings)
- [9. Set up your Photon custom auth server](#9-set-up-your-photon-custom-auth-server)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Purpose |
|---|---|
| [PythonAnywhere account](https://www.pythonanywhere.com/) | Hosts the backend |
| [HxD](https://mh-nexus.de/en/hxd/) (or another hex editor) | Patches the APK's binary strings |
| A 16 digit Meta App ID | Meta stopped issuing new ones, so you'll need an older app that already has one |
| APKToolGUI (or similar) | Decompiles / re-signs the APK |
| [QuestAppVersionSwitcher](https://github.com/ComputerElite/QuestAppVersionSwitcher) | Grabs the specific APK version you need |

---

## Overview

**TL;DR:**
1. Use QuestAppVersionSwitcher to get the target APK version
2. Unpack it with APKToolGUI (or similar)
3. Patch the server URL
4. Patch the App ID
5. Change the package name
6. Repack and sign the APK
7. Host the backend on PythonAnywhere
8. Set up the Photon custom auth server

Each step is explained in detail below.

---

## 1. Get the target APK

Use **QuestAppVersionSwitcher** to download the Animal Company APK version you want (1.60 - 1.75 are supported by this backend).

## 2. Unpack the APK

Open the APK in **APKToolGUI** (or your decompiler of choice) and unpack it so you can access and edit the raw asset files.

## 3. Patch the server URL

Open `assets/bin/Data/84ed4c5cf729c4b48880f9fdc0cbd072` in HxD and find this string:

```
https://animalcompany.us-east1.nakamacloud.io:443
```

Replace it with your own PythonAnywhere URL, padded with slashes so the byte length matches exactly:

```
https://your-name.pythonanywhere.com/////////////
```

> Important: the replacement string must be the exact same length as the original. The trailing slashes are just padding, they don't affect requests to your backend. If the length doesn't match, the client will fail to read the string correctly.

## 4. Patch the Meta App ID

Open `assets/bin/Data/bd67a80c08d994c8eb6ebcb4e1e67891` in HxD and find:

```
7190422614401072
```

Replace it with your own **16 digit** Meta App ID.

## 5. Change the package name

Update the app's package name (e.g. in `AndroidManifest.xml` via APKToolGUI) so it doesn't collide with the original installed app on your headset.

## 6. Repack and sign the APK

Repack the modified files back into an APK and sign it with APKToolGUI (or `apksigner`/`jarsigner`), then sideload it onto your Quest.

---

## 7. Host the backend on PythonAnywhere

1. **Create an account** at [pythonanywhere.com](https://www.pythonanywhere.com/).
2. **Go to your web apps page:** Navigate to `https://www.pythonanywhere.com/user/YOURUSERNAME/webapps` (replace `YOURUSERNAME` with your PythonAnywhere username).
3. **Delete your old webapp** (if you have one) to avoid conflicts.
4. **Add a new webapp:**
   - Click **"Add a new web app"**
   - Select **Flask** as the framework
   - Choose **Python 3.12** as the version
5. **Set the application path:** When prompted for the path, enter:
   ```
   /home/YOURUSERNAME/XeraCompany/backend.py
   ```
   Replace `YOURUSERNAME` with your actual PythonAnywhere username.
6. **Add the backend code:**
   - Go to the **Files** tab
   - Navigate to the path you set above (`/home/YOURUSERNAME/XeraCompany/`)
   - Open `backend.py` and paste the contents of `backend.py` from this repo
   - Add all the gamedata files and JSON files from the backend folder
7. **Update all paths in the code:** Open `backend.py` and change any hardcoded paths to use your PythonAnywhere username instead of the default placeholders.
8. **Reload the server:** Click the green **Reload** button on the Web tab to restart your app.
9. Your backend is now live at `https://your-name.pythonanywhere.com`, the URL you patched into the APK back in [Step 3](#3-patch-the-server-url).

> Note: on the free tier, PythonAnywhere apps go to sleep after a period of inactivity. Consider a paid tier (or your own VPS) if you want a server that's always on for other players.

---

## 8. Configure your server settings

Before going live, open `backend.py` inside `/Backend` and review the **SERVER CONFIG** section near the top. That's where you set things like your dev username, banned users/IPs, your dev IP, your Discord webhook, your Meta access token, your Photon App IDs, and starting currency amounts. Just edit the values directly in the file and save, no separate config file needed.

---

## 9. Set up your Photon custom auth server

Photon can call out to your backend to validate every player before letting them into a room. This backend already ships with an auth endpoint that auto-accepts any valid request, so you just need to point Photon at it.

1. Log into the [Photon Dashboard](https://dashboard.photonengine.com/) and open your app (the same App ID you set in `PHOTON_APP_ID`).
2. Go to your app's **Custom Authentication** settings.
3. Enable **Custom Authentication** and set the **Auth URL** to:
   ```
   https://your-name.pythonanywhere.com/v2/auth/photon
   ```
4. Save the settings.

That's it. This endpoint (`/v2/auth/photon` in `backend.py`) always returns a successful, authenticated response, so any client that reaches it gets waved into your Photon rooms. If you want tighter control (banning specific users, checking tokens, etc.) you can edit that endpoint in `backend.py` to add your own checks before it returns success.

---

## Troubleshooting

- **App won't connect / times out:** double check the patched URL string in Step 3 is the exact same byte length as the original, and that your PythonAnywhere web app is actually running (check the **Web** tab for errors, and the **Error log**).
- **Meta attestation fails:** make sure `META_ACCESS_TOKEN` in `backend.py` is set correctly and your App ID is a valid 16 digit ID from an older app.
- **Can't join Photon rooms:** confirm the Custom Authentication URL in the Photon dashboard is set exactly as shown in Step 9, and that your PythonAnywhere app is awake and reachable.
- **500 errors on PythonAnywhere:** check the **Error log** on the Web tab, most issues are missing dependencies or a typo in the WSGI file path.

---

If this backend is powering your copy, please star the repo:
https://github.com/Xera-Games-LLC/Xera-Company-Backend
