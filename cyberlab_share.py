#!/usr/bin/env python3
"""
CyberLab Link & Text Share
A small, dependency-free local Wi-Fi receiver for Windows.

Run: python cyberlab_share.py
Open the displayed address on your Android phone while both devices are
on the same Wi-Fi network or the laptop is connected to the phone hotspot.
"""

import json
import queue
import secrets
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

PORT = 8765
MAX_MESSAGE_CHARS = 10000
PIN = "123"
incoming = queue.Queue()
messages = []

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#172033">
<title>CyberLab Share</title>
<style>
:root{color-scheme:light dark;font-family:system-ui,sans-serif}
body{max-width:620px;margin:36px auto;padding:0 18px;background:#101827;color:#eef2ff}
main{background:#1b2638;padding:24px;border-radius:16px}
h1{font-size:1.45rem;margin-top:0}
p{color:#c4cee0;line-height:1.5}
label{display:block;margin:16px 0 7px;font-weight:600}
input,textarea,button{box-sizing:border-box;width:100%;font:inherit;border-radius:9px;padding:12px}
input,textarea{border:1px solid #526078;background:#111a29;color:#fff}
textarea{min-height:150px;resize:vertical}
button{margin-top:16px;border:0;background:#79a8ff;color:#081326;font-weight:700}
#status{min-height:1.5em;margin-top:12px}
.small{font-size:.88rem;color:#aab8ce}
</style>
</head>
<body>
<main>
<h1>CyberLab Share</h1>
<p>Send a link or text to your laptop over your local Wi-Fi network.</p>
<form id="sendForm">
<label for="pin">PIN shown on your laptop</label>
<input id="pin" name="pin" maxlength="8" autocomplete="off" required>
<label for="message">Link or text</label>
<textarea id="message" name="message" maxlength="10000"
 placeholder="Paste a link or type some text…" required></textarea>
<button type="submit">Send to laptop</button>
</form>
<div id="status" role="status"></div>
<p class="small">Only send content you intend to transfer. This page does not upload anything to the internet.</p>
</main>
<script>
const form=document.getElementById('sendForm');
const statusBox=document.getElementById('status');
form.addEventListener('submit',async e=>{
  e.preventDefault();
  const message=document.getElementById('message').value.trim();
  if(!message){statusBox.textContent='Enter a link or some text first.';return;}
  statusBox.textContent='Sending…';
  try{
    const body=new URLSearchParams({
      pin:document.getElementById('pin').value.trim(),
      message
    });
    const response=await fetch('/send',{method:'POST',
      headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body});
    const result=await response.json();
    if(!response.ok) throw new Error(result.error||'Could not send.');
    statusBox.textContent='Sent to your laptop.';
    document.getElementById('message').value='';
  }catch(err){statusBox.textContent=err.message||'Connection failed.';}
});
</script>
</body>
</html>
"""

def get_lan_ip():
    """Find the local interface Windows would use for network traffic."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))  # UDP connect does not send a packet.
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

class ShareHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep routine HTTP requests out of the console.
        pass

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        data = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/send":
            self.send_json(404, {"error": "Not found."})
            return

        # Reject cross-origin browser submissions.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin:
            expected_suffix = "://" + host
            if not origin.endswith(expected_suffix):
                self.send_json(403, {"error": "Request origin rejected."})
                return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 30000:
            self.send_json(413, {"error": "Message is too large or empty."})
            return

        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        fields = parse_qs(raw, keep_blank_values=True)
        supplied_pin = fields.get("pin", [""])[0].strip()
        message = fields.get("message", [""])[0].strip()

        if not secrets.compare_digest(supplied_pin, PIN):
            self.send_json(403, {"error": "Incorrect PIN."})
            return
        if not message:
            self.send_json(400, {"error": "Message is empty."})
            return
        if len(message) > MAX_MESSAGE_CHARS:
            self.send_json(413, {"error": "Message is too long."})
            return

        incoming.put((datetime.now().strftime("%H:%M:%S"), message))
        self.send_json(200, {"ok": True})

def start_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), ShareHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

def main():
    root = tk.Tk()
    root.title("CyberLab Link & Text Share")
    root.geometry("720x540")
    root.minsize(560, 420)

    lan_ip = get_lan_ip()
    try:
        server = start_server()
    except OSError as exc:
        messagebox.showerror("Could not start receiver",
                             f"Port {PORT} may already be in use.\n\n{exc}")
        root.destroy()
        return

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="CyberLab Link & Text Share",
              font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(outer, text="On your Android phone, open this address while both devices are on the same Wi-Fi or hotspot:",
              wraplength=660).pack(anchor="w", pady=(12, 4))

    address_var = tk.StringVar(value=f"http://{lan_ip}:{PORT}")
    address_entry = ttk.Entry(outer, textvariable=address_var, font=("Segoe UI", 12))
    address_entry.pack(fill="x")
    address_entry.configure(state="readonly")

    ttk.Label(outer, text=f"PIN:  {PIN}",
              font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(8, 12))
    ttk.Label(outer, text="Incoming messages (select one, then copy):",
              font=("Segoe UI", 10, "bold")).pack(anchor="w")

    content = ttk.Frame(outer)
    content.pack(fill="both", expand=True, pady=(6, 8))
    listbox = tk.Listbox(content, height=8, activestyle="dotbox")
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar = ttk.Scrollbar(content, orient="vertical", command=listbox.yview)
    scrollbar.pack(side="right", fill="y")
    listbox.configure(yscrollcommand=scrollbar.set)

    preview = tk.Text(outer, height=5, wrap="word", state="disabled")
    preview.pack(fill="x", pady=(0, 8))

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x")
    copy_button = ttk.Button(buttons, text="Copy selected message")
    copy_button.pack(side="left")

    status_var = tk.StringVar(value="Waiting for a message…")
    ttk.Label(outer, textvariable=status_var).pack(anchor="w", pady=(10, 0))

    def show_selected(_event=None):
        selection = listbox.curselection()
        preview.configure(state="normal")
        preview.delete("1.0", "end")
        if selection:
            preview.insert("1.0", messages[selection[0]][1])
        preview.configure(state="disabled")

    def copy_selected():
        selection = listbox.curselection()
        if not selection:
            status_var.set("Select a message first.")
            return
        root.clipboard_clear()
        root.clipboard_append(messages[selection[0]][1])
        root.update()
        status_var.set("Message copied to clipboard.")

    listbox.bind("<<ListboxSelect>>", show_selected)
    copy_button.configure(command=copy_selected)

    def poll_messages():
        received = False
        while True:
            try:
                timestamp, message = incoming.get_nowait()
            except queue.Empty:
                break
            messages.append((timestamp, message))
            label = message.replace("\n", " ")
            if len(label) > 72:
                label = label[:69] + "..."
            listbox.insert("end", f"{timestamp}  |  {label}")
            received = True
        if received:
            listbox.selection_clear(0, "end")
            listbox.selection_set("end")
            listbox.see("end")
            show_selected()
            status_var.set(f"Received {len(messages)} message(s).")
        root.after(250, poll_messages)

    def close_app():
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_app)
    poll_messages()
    root.mainloop()

if __name__ == "__main__":
    main()
