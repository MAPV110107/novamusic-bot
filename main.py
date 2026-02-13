import os
import asyncio
import logging
import time
import re
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
# Leemos el contenido de las cookies de la variable de entorno
COOKIES_CONTENT = os.getenv("COOKIES_CONTENT")

# CREACIÓN DEL ARCHIVO DE COOKIES EN TIEMPO DE EJECUCIÓN
COOKIE_FILE_PATH = "cookies.txt"
if COOKIES_CONTENT:
    # Si existe la variable, creamos el archivo físico para que yt-dlp lo lea
    with open(COOKIE_FILE_PATH, "w") as f:
        f.write(COOKIES_CONTENT)
    print("🍪 Cookies cargadas exitosamente desde variable de entorno.")
else:
    print("⚠️ ADVERTENCIA: No se encontraron cookies. YouTube podría bloquear la descarga.")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)

bot = Bot(token=TOKEN)
dp = Dispatcher()

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIPY_ID, client_secret=SPOTIPY_SECRET
))

# --- CLASE DE UTILIDAD UX ---
class ProgressTracker:
    def __init__(self, message: types.Message):
        self.message = message
        self.last_update = 0
        self.filename = "Desconocido"

    async def update(self, current, total, status="⬇️ Descargando"):
        now = time.time()
        if (now - self.last_update > 3) or (current == total):
            percentage = (current / total) * 100 if total > 0 else 0
            filled_length = int(10 * current // total) if total > 0 else 0
            bar = '█' * filled_length + '░' * (10 - filled_length)
            text = (f"💿 <b>Procesando:</b> {self.filename}\n{status}...\n<code>[{bar}] {percentage:.0f}%</code>")
            try:
                await self.message.edit_text(text, parse_mode=ParseMode.HTML)
                self.last_update = now
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception: pass

# --- FUNCIONES CORE ---
def obtener_info_spotify(url):
    try:
        results = sp.track(url)
        track = results['name']
        artist = results['artists'][0]['name']
        album = results['album']['name']
        duration = results['duration_ms'] / 1000
        cover = results['album']['images'][0]['url']
        query = f"{artist} - {track} Audio"
        return {'query': query, 'title': track, 'artist': artist, 'album': album, 'duration': duration, 'cover': cover}
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
    
    # OPCIONES BASE (Incluyen cookies si existen)
    base_opts = {
        'quiet': True,
        'noplaylist': True,
        'ignoreerrors': True,
    }
    # SI HAY COOKIES, LAS USAMOS
    if os.path.exists(COOKIE_FILE_PATH):
        base_opts['cookiefile'] = COOKIE_FILE_PATH

    # 1. BÚSQUEDA
    ydl_opts_search = {**base_opts, 'format': 'bestaudio/best'}

    try:
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            res = ydl.extract_info(f"ytsearch15:{info['query']}", download=False)
        
        if not res or 'entries' not in res: return None

        # 2. SELECCIÓN
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

        # 3. DESCARGA
        ydl_opts_dl = {
            **base_opts, # Heredamos cookies
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
    await message.answer("👋 <b>Hola Nova</b>\nSoy tu bot de música Hi-Fi Cloud.\nEnvíame un link de Spotify.", parse_mode=ParseMode.HTML)

@dp.message(F.text.contains("spotify.com"))
async def handle_spotify(message: types.Message):
    status_msg = await message.answer("🔍 <b>Analizando...</b>", parse_mode=ParseMode.HTML)
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
        await status_msg.edit_text("❌ No se pudo descargar (Posible bloqueo de YouTube o sin coincidencia).")

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
    print("🚀 Bot NovaMusic Cloud Iniciado...")
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())