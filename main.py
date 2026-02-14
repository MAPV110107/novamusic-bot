import os
import asyncio
import logging
import time
import aiohttp
import random
from dotenv import load_dotenv

# Telegram
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramRetryAfter

# Música y Datos
from ytmusicapi import YTMusic
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from thefuzz import fuzz # Lógica Difusa
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TYER # Metadatos MP3
from aiohttp import web

# --- CONFIGURACIÓN ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
SPOTIPY_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")

# Pool de Instancias Cobalt (Rotación automática si una falla)
COBALT_INSTANCES = [
    "https://api.cobalt.tools/api/json",           # Oficial
    "https://cobalt.kwiatekmiki.pl/api/json",      # Europa
    "https://cobalt.154.53.56.155.host.sapwd.net/api/json", # USA Backup
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- INICIALIZACIÓN ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_ID, client_secret=SPOTIPY_SECRET))
ytmusic = YTMusic()

# --- CLASE DE RASTREO UX ---
class ProgressTracker:
    def __init__(self, message: types.Message):
        self.message = message
        self.last_update = 0
        self.text_base = "Procesando..."

    async def update(self, status):
        now = time.time()
        # Solo actualizamos si pasaron 2 segundos o si es un estado final
        if (now - self.last_update > 2) or "Finalizado" in status:
            try:
                await self.message.edit_text(
                    f"💿 <b>NovaMusic V2</b>\n{status}", 
                    parse_mode=ParseMode.HTML
                )
                self.last_update = now
            except: pass

# --- 1. EXTRACCIÓN PROFUNDA (SPOTIFY) ---
def obtener_metadatos_spotify(url):
    try:
        track = sp.track(url)
        
        # Metadatos básicos
        meta = {
            'title': track['name'],
            'artist': track['artists'][0]['name'], # Artista principal
            'artists': [a['name'] for a in track['artists']], # Todos los artistas
            'album': track['album']['name'],
            'year': track['album']['release_date'][:4], # Solo el año
            'duration_ms': track['duration_ms'],
            'duration_sec': track['duration_ms'] / 1000,
            'cover_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
            'track_number': str(track['track_number']),
            'isrc': track.get('external_ids', {}).get('isrc'), # Huella digital
            'query_optimized': f"{track['artists'][0]['name']} {track['name']} audio"
        }
        return meta
    except Exception as e:
        logging.error(f"Error Spotify Deep: {e}")
        return None

# --- 2. ALGORITMO SMART MATCH ---
def calcular_score(meta_spotify, resultado_yt):
    """
    Compara un resultado de búsqueda con los datos de Spotify 
    y asigna un puntaje de 0 a 100.
    """
    score = 0
    
    # A. Título (Fuzzy Match)
    # Usamos token_set_ratio para ignorar orden ("Artist - Song" vs "Song - Artist")
    ratio_titulo = fuzz.token_set_ratio(meta_spotify['title'], resultado_yt['title'])
    score += ratio_titulo * 0.5  # El título vale el 50%

    # B. Duración (El filtro más fuerte)
    # Parsear duración "3:45" a segundos
    dur_text = resultado_yt.get('duration', '0:00')
    try:
        parts = list(map(int, dur_text.split(':')))
        dur_yt_sec = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0]
    except: dur_yt_sec = 0

    diff = abs(meta_spotify['duration_sec'] - dur_yt_sec)

    if diff <= 2: score += 40    # Casi exacto (+40%)
    elif diff <= 5: score += 20  # Aceptable (+20%)
    elif diff > 20: score -= 100 # DESCARTAR (Diferencia > 20s es otra versión)

    # C. Penalizaciones (Live, Remix, Karaoke)
    titulo_yt_lower = resultado_yt['title'].lower()
    titulo_spot_lower = meta_spotify['title'].lower()
    
    palabras_prohibidas = ["live", "vivo", "concert", "remix", "karaoke", "instrumental", "cover"]
    
    for palabra in palabras_prohibidas:
        # Si la palabra está en YT pero NO en Spotify -> Penalizar
        if palabra in titulo_yt_lower and palabra not in titulo_spot_lower:
            score -= 50

    return score, dur_yt_sec

def buscar_mejor_candidato(meta):
    try:
        logging.info(f"🔎 Buscando: {meta['query_optimized']}")
        
        # 1. Buscar Canciones (Filtro 'songs' es más puro)
        results = ytmusic.search(meta['query_optimized'], filter="songs")
        
        # 2. Si no hay canciones, buscar Videos (Filtro 'videos')
        if not results:
            results = ytmusic.search(meta['query_optimized'], filter="videos")
        
        if not results: return None

        best_candidate = None
        highest_score = 0

        for item in results[:5]: # Analizar Top 5
            video_id = item.get('videoId')
            if not video_id: continue

            score, dur = calcular_score(meta, item)
            logging.info(f"   Candidato: {item['title']} | Score: {score} | Dur: {dur}s")

            if score > highest_score:
                highest_score = score
                best_candidate = video_id

        # Umbral de calidad: Solo aceptamos si el score es > 60
        if highest_score > 60:
            return best_candidate
        return None

    except Exception as e:
        logging.error(f"Error Búsqueda: {e}")
        return None

# --- 3. DESCARGA RESILIENTE (COBALT CLUSTER) ---
async def descargar_audio(video_id, tracker):
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    filename = f"temp_{video_id}.mp3"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "NovaBot/V2"
    }

    payload = {
        "url": video_url,
        "downloadMode": "audio",
        "audioFormat": "mp3",
        "audioBitrate": "320"
    }

    async with aiohttp.ClientSession() as session:
        # Intentar con cada instancia del pool
        for instance in COBALT_INSTANCES:
            try:
                await tracker.update(f"☁️ Conectando a Nodo: {instance.split('/')[2]}...")
                
                async with session.post(instance, json=payload, headers=headers, timeout=15) as resp:
                    if resp.status != 200: continue # Probar siguiente nodo
                    
                    data = await resp.json()
                    dl_url = data.get('url')
                    
                    if not dl_url: continue # Probar siguiente nodo

                    # Descargar archivo
                    await tracker.update("⬇️ Descargando audio...")
                    async with session.get(dl_url) as file_resp:
                        if file_resp.status == 200:
                            with open(filename, 'wb') as f:
                                while True:
                                    chunk = await file_resp.content.read(1024*1024)
                                    if not chunk: break
                                    f.write(chunk)
                            return filename # ÉXITO
            except Exception as e:
                logging.error(f"Fallo nodo {instance}: {e}")
                continue # Siguiente
    
    return None

# --- 4. POST-PROCESAMIENTO (TAGGING) ---
async def etiquetar_mp3(filepath, meta):
    try:
        # Descargar carátula
        thumb_data = None
        if meta['cover_url']:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(meta['cover_url']) as r:
                    if r.status == 200: thumb_data = await r.read()

        # Abrir MP3
        audio = ID3(filepath)
        
        # Insertar Tags
        audio.add(TIT2(encoding=3, text=meta['title']))
        audio.add(TPE1(encoding=3, text=meta['artist']))
        audio.add(TALB(encoding=3, text=meta['album']))
        audio.add(TYER(encoding=3, text=meta['year']))
        
        # Insertar Carátula
        if thumb_data:
            audio.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3, # Portada frontal
                desc=u'Cover',
                data=thumb_data
            ))
        
        audio.save()
        return thumb_data # Retornamos la imagen para Telegram
    except Exception as e:
        logging.error(f"Error Tagging: {e}")
        return None

# --- HANDLERS TELEGRAM ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "🎧 <b>NovaMusic V2</b>\n"
        "Sistema de Búsqueda Inteligente.\n"
        "Envíame un enlace de Spotify.", 
        parse_mode=ParseMode.HTML
    )

@dp.message(F.text.contains("spotify.com"))
async def handle_spotify(message: types.Message):
    status_msg = await message.answer("🔍 <b>Analizando Spotify...</b>", parse_mode=ParseMode.HTML)
    tracker = ProgressTracker(status_msg)
    
    # 1. Metadatos
    meta = await asyncio.to_thread(obtener_metadatos_spotify, message.text)
    if not meta:
        await status_msg.edit_text("❌ Error leyendo Spotify.")
        return

    # 2. Búsqueda Inteligente
    await tracker.update(f"🔎 Buscando '{meta['title']}'...")
    video_id = await asyncio.to_thread(buscar_mejor_candidato, meta)
    
    if not video_id:
        await status_msg.edit_text("❌ No encontré una coincidencia exacta de audio.")
        return

    # 3. Descarga
    file_path = await descargar_audio(video_id, tracker)
    if not file_path:
        await status_msg.edit_text("❌ Error descargando el audio (Servidores ocupados).")
        return

    # 4. Tagging
    await tracker.update("🏷️ Aplicando Metadatos HD...")
    thumb_data = await etiquetar_mp3(file_path, meta)

    # 5. Subida
    await tracker.update("⬆️ Subiendo a Telegram...")
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_VOICE)

    try:
        audio_input = FSInputFile(file_path)
        
        # Guardar thumb temporal
        thumb_path = f"thumb_{video_id}.jpg"
        if thumb_data:
            with open(thumb_path, "wb") as f: f.write(thumb_data)
        
        thumb_input = FSInputFile(thumb_path) if thumb_data else None

        await message.answer_audio(
            audio_input,
            caption=f"🎵 <b>{meta['title']}</b>\n👤 {meta['artist']}\n💿 {meta['album']} ({meta['year']})",
            title=meta['title'],
            performer=meta['artist'],
            thumbnail=thumb_input,
            parse_mode=ParseMode.HTML
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Error enviando archivo: {e}")
    finally:
        # Limpieza
        if os.path.exists(file_path): os.remove(file_path)
        if os.path.exists(thumb_path): os.remove(thumb_path)

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
    print("🚀 NovaMusic V2 (Deep Search) Iniciado...")
    await start_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())