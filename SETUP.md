# How to Run LinkSift — Beginner's Guide

This guide assumes you've never used a terminal before. Follow it step by step.

---

## What you need installed first

You need **two** programs on your computer. Check if you have them — if not, install them.

### 1. Python 3.10 or newer

**Mac:**
- Open the **Terminal** app (press `Cmd + Space`, type "Terminal", press Enter)
- Type this and press Enter:
  ```
  python3 --version
  ```
- If you see `Python 3.10.x` or higher, you're good. If not, install it from <https://www.python.org/downloads/>

**Windows:**
- Press the **Windows key**, type "cmd", press Enter (this opens Command Prompt)
- Type this and press Enter:
  ```
  python --version
  ```
- If you see `Python 3.10.x` or higher, you're good. If not, install from <https://www.python.org/downloads/>
- **IMPORTANT:** during install, check the box that says **"Add Python to PATH"**

### 2. Node.js (any LTS version)

The Claude Agent SDK is built on top of Claude Code, which is a Node.js program. So you need Node.

- Go to <https://nodejs.org/> and download the **LTS** version
- Run the installer, accept defaults

Verify by typing in your terminal:
```
node --version
```
You should see something like `v20.x.x`.

### 3. An Anthropic API key

- Go to <https://console.anthropic.com/settings/keys>
- Sign up or log in
- Click **"Create Key"**
- Copy the key — it starts with `sk-ant-...`
- **Don't share it with anyone.** Keep it somewhere safe (a note on your computer is fine).

---

## Start the app

### On Mac/Linux:

1. Open **Finder**, go to the `linksift-agent` folder
2. Open **Terminal**
3. Type `cd ` (with a space after `cd`), then **drag the `linksift-agent` folder** into the Terminal window. It'll auto-fill the path. Press Enter.
4. Type this and press Enter:
   ```
   bash start.sh
   ```
5. The script will set everything up. The first time it'll ask for your API key — paste it and press Enter.
6. After ~30 seconds, your browser should open to `http://localhost:8000`. If not, open that URL yourself.

### On Windows:

1. Open the `linksift-agent` folder in File Explorer
2. **Double-click `start.bat`**
3. A black Command Prompt window will open. The first time it'll ask for your API key — paste it and press Enter.
4. After ~30 seconds, your browser should open to `http://localhost:8000`. If not, open that URL yourself.

**Leave the terminal/Command Prompt window open** while you use the app. Closing it stops the server.

---

## When you're done

- Go back to the terminal window
- Press `Ctrl + C` (yes, even on Mac — it's Control, not Command)
- The server stops. You can close the terminal.

To run it again later, just repeat the start steps. It remembers your API key in a hidden `.env` file.

---

## Troubleshooting

### "Failed to fetch" in the browser

You're probably opening the HTML file directly. **Don't double-click `index.html`.** The browser address bar must say `http://localhost:8000`, **not** `file:///...`.

### "python: command not found" or "python3: command not found"

Python isn't installed, or it isn't in your PATH. Reinstall from python.org and make sure to check "Add to PATH" on Windows.

### "Port 8000 is already in use"

Something else is using port 8000. Find what:

**Mac/Linux:**
```
lsof -i :8000
```
Kill that process, or change the port in `start.sh` (last line, change `8000` to `8001` and use `http://localhost:8001` in the browser).

**Windows:**
```
netstat -ano | findstr :8000
```

### "ANTHROPIC_API_KEY not set on the server"

Edit the file called `.env` in the `linksift-agent` folder (it might be hidden — show hidden files in your file manager). It should contain a single line:
```
ANTHROPIC_API_KEY=sk-ant-your-actual-key-here
```
If the file doesn't exist, create it. Then restart the server.

### "CLINotFoundError" or "Claude Code CLI not found"

Node.js isn't installed or isn't in your PATH. Install from <https://nodejs.org/> and restart your terminal.

### The browser opens but the page is blank

Check the terminal where you ran `start.sh` / `start.bat` — it'll show error messages there. The most common is a missing dependency. Try:
```
cd backend
pip install -r requirements.txt
```

### Nothing else works

Send me a screenshot of:
1. The terminal window after running the start script
2. The browser DevTools (press `F12`) → Network tab → click the failed `/api/analyze` request

I'll be able to pinpoint it from there.
