import os
import asyncio
import logging
import time
import subprocess
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramRetryAfter

import yt_dlp
from ytmusicapi import YTMusic
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from aiohttp import web

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
SPOTIPY_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
COOKIES_CONTENT = os.getenv("COOKIES_CONTENT")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)

COOKIE_FILE_PATH = "cookies.txt"
if COOKIES_CONTENT:
    with open(COOKIE_FILE_PATH, "w") as f:
        f.write(COOKIES_CONTENT)

try:
    node_v = subprocess.check_output(["node", "-v"]).decode("utf-8").strip()
    logging.info(f"Node.js: {node_v}")
except:
    logging.warning("Node.js not found")

bot = Bot(token=TOKEN)
dp = Dispatcher()
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_ID, client_secret=SPOTIPY_SECRET))
ytmusic = YTMusic()

class ProgressTracker:
    def __init__(self, message: types.Message):
        self.message = message
        self.last_update = 0
        self.filename = "Procesando..."

    async def update(self, current, total, status="⬇️ Descargando"):
        now = time.time()
        if (now - self.last_update > 4) or (current == total):
            percentage = (current / total) * 100 if total > 0 else 0
            filled = int(10 * current // total) if total > 0 else 0
            bar = '█' * filled + '░' * (10 - filled)
            text = (f"💿 <b>{self.filename}</b>\n{status}...\n<code>[{bar}] {percentage:.0f}%</code>")
            try:
                await self.message.edit_text(text, parse_mode=ParseMode.HTML)
                self.last_update = now
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception: pass 

def obtener_info_spotify(url):
    try:
        results = sp.track(url)
        track = results['name']
        artist = results['artists'][0]['name']
        album = results['album']['name']
        duration = results['duration_ms'] / 1000
        cover = results['album']['images'][0]['url']
        return {'query': f"{artist} {track}", 'title': track, 'artist': artist, 'album': album, 'duration': duration, 'cover': cover}
    except Exception as e:
        logging.error(f"Error Spotify: {e}")
        return None

def buscar_video_id(query, duration_target):
    try:
        results = ytmusic.search(query, filter="songs")
        if not results:
            results = ytmusic.search(query, filter="videos")
        
        if not results: return None

        best_id = None
        min_diff = float('inf')

        for item in results[:5]:
            video_id = item.get('videoId')
            if not video_id: continue

            duration_text = item.get('duration', '0:00')
            try:
                parts = list(map(int, duration_text.split(':')))
                duration_seconds = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0]
            except:
                duration_seconds = 0
            
            diff = abs(duration_seconds - duration_target)

            if diff < min_diff:
                min_diff = diff
                best_id = video_id

        if min_diff < 15 and best_id:
            return best_id
        
        return results[0]['videoId'] if results else None

    except Exception as e:
        logging.error(f"Error API: {e}")
        return None

def progress_hook_wrapper(d, tracker_coro, loop):
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        downloaded = d.get('downloaded_bytes', 0)
        if total > 0:
            asyncio.run_coroutine_threadsafe(tracker_coro.update(downloaded, total, "⬇️ Descargando"), loop)
    elif d['status'] == 'finished':
        asyncio.run_coroutine_threadsafe(tracker_coro.update(1, 1, "⚙️ Convirtiendo"), loop)

def descargar_con_ux(info, tracker, loop):
    tracker.filename = f"{info['artist']} - {info['title']}"
    nombre_limpio = "".join([c for c in tracker.filename if c.isalnum() or c in (' ', '-', '_', '.')]).strip()
    
    video_id = buscar_video_id(info['query'], info['duration'])
    
    if not video_id:
        return None
    
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'format': 'bestaudio/best',
        'outtmpl': f'{nombre_limpio}.%(ext)s',
        'cookiefile': COOKIE_FILE_PATH if os.path.exists(COOKIE_FILE_PATH) else None,
        'progress_hooks': [lambda d: progress_hook_wrapper(d, tracker, loop)],
        'postprocessors': [
            {'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '320'},
            {'key': 'EmbedThumbnail'},
            {'key': 'FFmpegMetadata', 'add_metadata': True},
        ],
        'writethumbnail': True,
        'extractor_args': {'youtube': {'player_client': ['android']}} 
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return f"{nombre_limpio}.mp3"
    except Exception as e:
        logging.error(f"Error descarga: {e}")
        return None

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("👋 <b>NovaBot</b>\nListo para descargar.", parse_mode=ParseMode.HTML)

@dp.message(F.text.contains("spotify.com"))
async def handle_spotify(message: types.Message):
    status_msg = await message.answer("🔍 <b>Buscando...</b>", parse_mode=ParseMode.HTML)
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    info = await asyncio.to_thread(obtener_info_spotify, message.text)
    if not info:
        await status_msg.edit_text("❌ Error enlace.", parse_mode=ParseMode.HTML)
        return

    tracker = ProgressTracker(status_msg)
    loop = asyncio.get_running_loop()
    archivo = await asyncio.to_thread(descargar_con_ux, info, tracker, loop)

    if archivo and os.path.exists(archivo):
        await status_msg.edit_text("⬆️ <b>Subiendo...</b>", parse_mode=ParseMode.HTML)
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)
        try:
            audio_file = FSInputFile(archivo)
            thumb_path = archivo.replace(".mp3", ".jpg")
            thumb = FSInputFile(thumb_path) if os.path.exists(thumb_path) else None
            caption = f"🎵 <b>{info['title']}</b>\n👤 {info['artist']}\n💿 {info['album']}"
            await message.answer_audio(audio_file, caption=caption, title=info['title'], performer=info['artist'], thumbnail=thumb, parse_mode=ParseMode.HTML)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Error: {e}")
        finally:
            if os.path.exists(archivo): os.remove(archivo)
            for f in os.listdir():
                if f.startswith(info['artist']) and (f.endswith(".jpg") or f.endswith(".webp")):
                    try: os.remove(f)
                    except: pass
    else:
        await status_msg.edit_text("❌ Error en descarga.")

async def health_check(request): return web.Response(text="Bot Alive")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    print("🚀 Bot Iniciado")
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())