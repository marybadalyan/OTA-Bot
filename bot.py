import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

HTTP_PORT = 8080


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def start_file_server():
    os.chdir(os.path.dirname(__file__))
    server = HTTPServer(("0.0.0.0", HTTP_PORT), SimpleHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

TOKEN = "8719578177:AAHmo-pOzGVEx5-nKAmos6OfeLJCJaxAJyI"
CSV_FILE = os.path.join(os.path.dirname(__file__), "spotify_playlists.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "playlists")
BITRATE = "128K"
IMG_W = 128
IMG_H = 48


# ── helpers ──────────────────────────────────────────────────────────────────

def safe_name(artist, song):
    name = f"{artist} - {song}"
    return "".join(c if c not in r'\/:*?"<>|' else "_" for c in name)


def youtube_search(artist, song):
    result = subprocess.run(
        ["yt-dlp", "--no-download", "--print", "webpage_url", f"ytsearch1:{artist} {song}"],
        capture_output=True, text=True,
    )
    url = result.stdout.strip()
    return url if url.startswith("https://") else None


def fetch_track(url, dest_mp3, dest_jpg):
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([
            "yt-dlp", "-x", "--audio-format", "mp3", "--audio-quality", BITRATE,
            "--postprocessor-args", "ffmpeg:-ar 44100",
            "--write-thumbnail", "--convert-thumbnails", "jpg",
            "-o", os.path.join(tmp, "track.%(ext)s"),
            url,
        ], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr else "yt-dlp failed")

        shutil.copy(os.path.join(tmp, "track.mp3"), dest_mp3)

        thumb = os.path.join(tmp, "track.jpg")
        if not os.path.exists(thumb):
            thumb = os.path.join(tmp, "track.webp")

        r = subprocess.run([
            "ffmpeg", "-y", "-i", thumb,
            "-vf", f"scale={IMG_W}:{IMG_H}:force_original_aspect_ratio=decrease",
            dest_jpg,
        ], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr else "ffmpeg failed")


def read_csv():
    rows = []
    if not os.path.exists(CSV_FILE):
        return rows
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def write_csv(rows):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Playlist", "Artist", "Song"])
        writer.writeheader()
        writer.writerows(rows)


def load_tracks(folder):
    tracks_file = os.path.join(folder, "tracks.csv")
    if not os.path.exists(tracks_file):
        return []
    with open(tracks_file, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_tracks(folder, rows):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "tracks.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Artist", "Song", "YouTube URL"])
        writer.writeheader()
        writer.writerows(rows)


def update_mapping(folder):
    tracks = load_tracks(folder)
    mapping = [
        {"mp3": safe_name(r["Artist"], r["Song"]) + ".mp3",
         "jpg": safe_name(r["Artist"], r["Song"]) + ".jpg",
         "artist": r["Artist"], "song": r["Song"]}
        for r in tracks if r.get("YouTube URL", "").startswith("https://")
    ]
    with open(os.path.join(folder, "mapping.json"), "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)


def search_and_download(playlist, artist, song):
    """Search YouTube, download mp3+jpg, update tracks.csv and mapping.json. Returns url or raises."""
    folder = os.path.join(OUTPUT_DIR, playlist)
    os.makedirs(folder, exist_ok=True)

    url = youtube_search(artist, song)
    if not url:
        raise RuntimeError("No YouTube result found")

    name = safe_name(artist, song)
    fetch_track(url, os.path.join(folder, name + ".mp3"), os.path.join(folder, name + ".jpg"))

    # update tracks.csv
    tracks = load_tracks(folder)
    key = (artist, song)
    existing_keys = {(r["Artist"], r["Song"]) for r in tracks}
    if key not in existing_keys:
        tracks.append({"Artist": artist, "Song": song, "YouTube URL": url})
    else:
        for r in tracks:
            if (r["Artist"], r["Song"]) == key:
                r["YouTube URL"] = url
    save_tracks(folder, tracks)
    update_mapping(folder)
    return url


# ── commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "OTA Music Bot\n\n"
        "/add <playlist> | <artist> | <song> — add & download a track\n"
        "/sync — re-scan entire CSV and download new tracks\n"
        "/sync <playlist> — sync one playlist only\n"
        "/list — show all playlists\n"
        "/list <playlist> — show tracks in a playlist\n"
        "/status — show all playlists and track counts"
    )


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = " ".join(ctx.args).strip()
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 3:
        await update.message.reply_text("Usage: /add <playlist> | <artist> | <song>")
        return

    playlist, artist, song = parts
    await update.message.reply_text(f"Searching YouTube for {artist} - {song}...")

    # add to master CSV if not already there
    rows = read_csv()
    if not any(r["Playlist"] == playlist and r["Artist"] == artist and r["Song"] == song for r in rows):
        rows.append({"Playlist": playlist, "Artist": artist, "Song": song})
        write_csv(rows)

    try:
        url = search_and_download(playlist, artist, song)
        await update.message.reply_text(f"Done!\n{artist} - {song}\n{url}")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    playlist_arg = " ".join(ctx.args).strip() or "."
    here = os.path.dirname(os.path.abspath(__file__))

    async def run_step(label, script, *args):
        await update.message.reply_text(f"Step {label}...")
        result = subprocess.run(
            [sys.executable, os.path.join(here, script), *args],
            capture_output=True, text=True, cwd=here,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise RuntimeError(output or f"{script} failed")
        return output

    try:
        out = await run_step("1/3: Spotify export", "spotify_exporter.py", playlist_arg)
        await update.message.reply_text(out[-3000:] if out else "Export done.")

        out = await run_step("2/3: YouTube search", "1_search.py", playlist_arg)
        await update.message.reply_text(out[-3000:] if out else "Search done.")

        out = await run_step("3/3: Download", "2_download.py", playlist_arg)
        await update.message.reply_text(out[-3000:] if out else "Download done.")

        await update.message.reply_text("Sync complete.")
    except Exception as e:
        await update.message.reply_text(f"Sync failed: {e}")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    playlist = " ".join(ctx.args).strip()

    # /list — show all playlists
    if not playlist or playlist == ".":
        if not os.path.isdir(OUTPUT_DIR):
            await update.message.reply_text("No playlists found.")
            return
        playlists = sorted(os.listdir(OUTPUT_DIR))
        if not playlists:
            await update.message.reply_text("No playlists found.")
            return
        lines = [f"• {p}" for p in playlists]
        await update.message.reply_text("*Playlists:*\n" + "\n".join(lines), parse_mode="Markdown")
        return

    # /list AM — show tracks in a specific playlist
    folder = os.path.join(OUTPUT_DIR, playlist)
    tracks = load_tracks(folder)
    if not tracks:
        await update.message.reply_text(f"No tracks found for playlist '{playlist}'")
        return

    lines = [f"{i+1}. {r['Artist']} - {r['Song']}" for i, r in enumerate(tracks)]
    await update.message.reply_text(f"*{playlist}*\n" + "\n".join(lines), parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not os.path.isdir(OUTPUT_DIR):
        await update.message.reply_text("No playlists found.")
        return

    lines = []
    for playlist in sorted(os.listdir(OUTPUT_DIR)):
        folder = os.path.join(OUTPUT_DIR, playlist)
        tracks = load_tracks(folder)
        downloaded = sum(
            1 for r in tracks
            if os.path.exists(os.path.join(folder, safe_name(r["Artist"], r["Song"]) + ".mp3"))
        )
        lines.append(f"{playlist}: {downloaded}/{len(tracks)} tracks")

    await update.message.reply_text("\n".join(lines) if lines else "No playlists found.")


# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    start_file_server()
    ip = get_local_ip()
    print(f"File server running → http://{ip}:{HTTP_PORT}/playlists/")
    print(f"ESP32 base URL:       http://{ip}:{HTTP_PORT}/playlists/<playlist>/")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("status", cmd_status))
    print("Bot running...")
    app.run_polling()
