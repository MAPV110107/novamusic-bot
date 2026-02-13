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
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from aiohttp import web

# --- CONFIGURACIÓN ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
SPOTIPY_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)

# --- ESPERAR A QUE TOR ARRANQUE ---
print("🧅 Esperando a que la red Tor se estabilice (10s)...")
time.sleep(10)
print("🧅 Red Tor lista.")

bot = Bot(token=TOKEN)
dp = Dispatcher()
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_ID, client_secret=SPOTIPY_SECRET))

# --- UX ---
class ProgressTracker:
    def __init__(self, message: types.Message):
        self.message = message
        self.last_update = 0
        self.filename = "Procesando..."

    async def update(self, current, total, status="⬇️ Descargando"):
        now = time.time()
        if (now - self.last_update > 5) or (current == total): # Aumenté a 5s porque Tor es lento
            percentage = (current / total) * 100 if total > 0 else 0
            filled = int(10 * current // total) if total > 0 else 0
            bar = '█' * filled + '░' * (10 - filled)
            text = (f"💿 <b>{self.filename}</b>\n{status} (vía Tor 🧅)...\n<code>[{bar}] {percentage:.0f}%</code>")
            try:
                await self.message.edit_text(text, parse_mode=ParseMode.HTML)
                self.last_update = now
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception: pass 

# --- CORE ---
def obtener_info_spotify(url):
    try:
        results = sp.track(url)
        track = results['name']
        artist = results['artists'][0]['name']
        album = results['album']['name']
        duration = results['duration_ms'] / 1000
        cover = results['album']['images'][0]['url']
        return {'query': f"{artist} - {track} Audio", 'title': track, 'artist': artist, 'album': album, 'duration': duration, 'cover': cover}
    except Exception as e:
        logging.error(f"Error Spotify: {e}")
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
    
    # --- CONFIGURACIÓN TOR (EL BÚNKER) ---
    base_opts = {
        'quiet': True,
        'noplaylist': True,
        'ignoreerrors': True,
        'socket_timeout': 60, # Tor es lento, damos más tiempo
        # ENRUTAMOS TODO POR TOR
        'proxy': 'socks5://127.0.0.1:9050',
        'extractor_args': {
            'youtube': {
                'player_client': ['android'] # Android se lleva bien con proxys
            }
        }
    }

    print("🧅 Iniciando descarga a través del Túnel Tor...")

    ydl_opts_search = {**base_opts, 'format': 'bestaudio/best'}

    try:
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            res = ydl.extract_info(f"ytsearch15:{info['query']}", download=False)
        
        if not res or 'entries' not in res: return None

        best_cand = None
        best_score = -999
        prohibidas = ["cover", "karaoke", "remix", "live", "vivo", "speed", "reverb"]
        
        for vid in res['entries']:
            if not vid: continue
            score = 0
            diff = abs(vid.get('duration', 0) - info['duration'])
            if diff <= 5: score += 100
            elif diff <= 20: score += 60
            else: score -= 50
            upl = vid.get('uploader', '').lower().replace(" ","")
            art = info['artist'].lower().replace(" ","")
            if art in upl or "topic" in upl: score += 40
            vid_title = vid.get('title', '').lower()
            orig_title = info['title'].lower()
            for p in prohibidas:
                if p in vid_title and p not in orig_title: score -= 150
            if score > best_score:
                best_score = score
                best_cand = vid

        if not best_cand or best_score < 50: return None

        ydl_opts_dl = {
            **base_opts,
            'format': 'bestaudio/best',
            'outtmpl': f'{nombre_limpio}.%(ext)s',
            'progress_hooks': [lambda d: progress_hook_wrapper(d, tracker, loop)],
            'postprocessors': [
                {'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '320'},
                {'key': 'EmbedThumbnail'},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
            ],
            'writethumbnail': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
            ydl.download([best_cand['webpage_url']])
            
        return f"{nombre_limpio}.mp3"

    except Exception as e:
        logging.error(f"Error descarga: {e}")
        return None

# --- HANDLERS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("👋 <b>NovaBot: Tor Edition 🧅</b>\nTráfico encriptado y rotación de IP activa.", parse_mode=ParseMode.HTML)

@dp.message(F.text.contains("spotify.com"))
async def handle_spotify(message: types.Message):
    status_msg = await message.answer("🔍 <b>Conectando a la red Tor...</b>", parse_mode=ParseMode.HTML)
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
        await status_msg.edit_text("❌ Error: Incluso Tor falló. Render IP muy restringida.")

# --- SERVER ---
async def health_check(request): return web.Response(text="Bot NovaMusic Alive!")
async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    print("🚀 Bot NovaMusic (Tor Edition) Iniciado...")
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())