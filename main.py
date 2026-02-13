import os
import asyncio
import logging
import time
import subprocess
import aiohttp
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, URLInputFile
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramRetryAfter

from ytmusicapi import YTMusic
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from aiohttp import web

# --- CONFIGURACIÓN ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
SPOTIPY_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

# Instancia principal de Cobalt (puedes cambiarla si se cae)
COBALT_API_URL = "https://api.cobalt.tools/api/json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Inicialización
bot = Bot(token=TOKEN)
dp = Dispatcher()
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_ID, client_secret=SPOTIPY_SECRET))
ytmusic = YTMusic()

# --- UX ---
class ProgressTracker:
    def __init__(self, message: types.Message):
        self.message = message
        self.filename = "Procesando..."

    async def update(self, status):
        try:
            await self.message.edit_text(
                f"💿 <b>{self.filename}</b>\n{status}...", 
                parse_mode=ParseMode.HTML
            )
        except: pass

# --- CORE ---
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
        # Buscamos en YT Music (API Segura)
        results = ytmusic.search(query, filter="songs")
        if not results: results = ytmusic.search(query, filter="videos")
        
        if not results: return None

        best_id = None
        min_diff = float('inf')

        for item in results[:5]:
            video_id = item.get('videoId')
            if not video_id: continue
            
            # Parsear duración
            duration_text = item.get('duration', '0:00')
            try:
                parts = list(map(int, duration_text.split(':')))
                duration_seconds = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0]
            except: duration_seconds = 0
            
            diff = abs(duration_seconds - duration_target)
            if diff < min_diff:
                min_diff = diff
                best_id = video_id

        if min_diff < 15 and best_id: return best_id
        return results[0]['videoId'] if results else None

    except Exception as e:
        logging.error(f"Error Search API: {e}")
        return None

async def descargar_con_cobalt(info, tracker):
    tracker.filename = f"{info['artist']} - {info['title']}"
    nombre_limpio = "".join([c for c in tracker.filename if c.isalnum() or c in (' ', '-', '_', '.')]).strip() + ".mp3"
    
    # 1. Obtener ID de YouTube
    await tracker.update("🔍 Buscando en YouTube Music")
    video_id = await asyncio.to_thread(buscar_video_id, info['query'], info['duration'])
    
    if not video_id:
        return None, "No se encontró el video."
    
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # 2. Solicitar enlace a Cobalt
    await tracker.update("☁️ Solicitando audio a Cobalt")
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "NovaBot/1.0"
    }
    
    payload = {
        "url": video_url,
        "aFormat": "mp3",
        "isAudioOnly": True,
    }

    async with aiohttp.ClientSession() as session:
        try:
            # Paso A: Obtener URL de descarga
            async with session.post(COBALT_API_URL, json=payload, headers=headers) as resp:
                data = await resp.json()
                
                if 'url' not in data:
                    logging.error(f"Cobalt Error: {data}")
                    return None, "Cobalt no pudo procesar el link."
                
                download_url = data['url']

            # Paso B: Descargar el archivo al servidor de Render
            await tracker.update("⬇️ Descargando al servidor")
            async with session.get(download_url) as resp_file:
                if resp_file.status == 200:
                    with open(nombre_limpio, 'wb') as f:
                        while True:
                            chunk = await resp_file.content.read(1024*1024) # 1MB chunks
                            if not chunk: break
                            f.write(chunk)
                    return nombre_limpio, None
                else:
                    return None, f"Error descargando archivo: {resp_file.status}"

        except Exception as e:
            logging.error(f"Error Fatal Cobalt: {e}")
            return None, str(e)

# --- HANDLERS ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("👋 <b>NovaBot: Cobalt Engine</b>\nSistema de descarga tercerizado (Anti-Ban).", parse_mode=ParseMode.HTML)

@dp.message(F.text.contains("spotify.com"))
async def handle_spotify(message: types.Message):
    status_msg = await message.answer("✨ <b>Iniciando...</b>", parse_mode=ParseMode.HTML)
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    info = await asyncio.to_thread(obtener_info_spotify, message.text)
    if not info:
        await status_msg.edit_text("❌ Error enlace Spotify.", parse_mode=ParseMode.HTML)
        return

    tracker = ProgressTracker(status_msg)
    
    # Flujo Cobalt
    archivo, error = await descargar_con_cobalt(info, tracker)

    if archivo and os.path.exists(archivo):
        await status_msg.edit_text("⬆️ <b>Subiendo a Telegram...</b>", parse_mode=ParseMode.HTML)
        await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)
        try:
            audio_file = FSInputFile(archivo)
            thumb_path = archivo.replace(".mp3", ".jpg")
            # Intentamos bajar la portada de Spotify
            if info['cover']:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(info['cover']) as r:
                        if r.status == 200:
                            with open(thumb_path, 'wb') as f: f.write(await r.read())
            
            thumb = FSInputFile(thumb_path) if os.path.exists(thumb_path) else None
            caption = f"🎵 <b>{info['title']}</b>\n👤 {info['artist']}\n💿 {info['album']}"
            
            await message.answer_audio(audio_file, caption=caption, title=info['title'], performer=info['artist'], thumbnail=thumb, parse_mode=ParseMode.HTML)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Error subida: {e}")
        finally:
            if os.path.exists(archivo): os.remove(archivo)
            if os.path.exists(thumb_path): os.remove(thumb_path)
    else:
        await status_msg.edit_text(f"❌ Error: {error}")

# --- SERVER ---
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
    print("🚀 Bot NovaMusic (Cobalt Edition) Iniciado...")
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())