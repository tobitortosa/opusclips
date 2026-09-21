# opusclips

Convierte un stream de horas en clips verticales listos para TikTok, Reels y Shorts.
Todo corre en la máquina local; lo único que sale a internet es el texto de la transcripción.

**La documentación completa está en [LEEME.md](LEEME.md)** — qué hace cada paso, cuánto
tarda, cuánto cuesta y por qué cada decisión está tomada así.

## Qué hay en este repo

Está la **lógica**, no el material. Los streams, los clips generados y los intermedios
quedan fuera a propósito (ver `.gitignore`).

```
app.py              servidor local (FastAPI) y API
core/
  config.py         todo lo ajustable: layout, calidad, umbrales, modelos
  ff.py             ffmpeg y ffprobe
  sync.py           desfase entre pantalla y cámara
  audio.py          detección de voz y densidad de habla
  asr.py            transcripción (faster-whisper large-v3)
  reparar.py        arregla timestamps rotos de Whisper
  momentos.py       elección de los mejores momentos (Claude Sonnet 5)
  gancho.py         cold open y cartel de cada clip (Claude Opus 5)
  silencios.py      corte de pausas y mapa de tiempos
  zoom.py           vaivén de zoom continuo
  subtitulos.py     karaoke y cartel en formato ASS
  render.py         composición y exportación
  pipeline.py       orquestación de todo
web/                la interfaz
scripts/            utilidades (genera el golpe de audio del cold open)
tests/              tests del mapa de tiempos, la reparación y el gancho
```

## Para dejarlo andando en otra máquina

Cuatro cosas quedan fuera del repo y hay que reponerlas:

1. **`tools/ffmpeg.exe` y `tools/ffprobe.exe`** — pesan 164 MB cada uno y GitHub no
   acepta archivos de más de 100 MB. Se bajan de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
   (build *full*) y van en `tools/`.

2. **El `.env` con la API key.** Copiá `.env.ejemplo` a `.env` y poné la tuya:

   ```
   CLIPS_API_KEY=sk-ant-...
   ```

   Se lee **sólo de ahí**, nunca de una variable del sistema, así que no puede usar
   otra cuenta por accidente.

3. **El entorno de Python:**

   ```
   python -m venv .venv --system-site-packages
   .venv\Scripts\pip install -r requirements.txt
   ```

   Necesita una GPU NVIDIA con `torch` instalado en el sistema (la transcripción y el
   detector de voz corren ahí).

4. **Los modelos** (Whisper large-v3 y silero-vad) se bajan solos la primera vez.

Después, doble clic en `INICIAR.bat`.

## Tests

```
.venv\Scripts\python.exe tests\test_tiempos.py
```
