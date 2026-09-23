# -*- coding: utf-8 -*-
"""Configuracion y constantes. Todo lo ajustable vive aca."""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOOLS = RAIZ / "tools"
FFMPEG = str(TOOLS / "ffmpeg.exe")
FFPROBE = str(TOOLS / "ffprobe.exe")
FUENTES = RAIZ / "assets" / "fonts"
IMPACTO = RAIZ / "assets" / "impacto.wav"      # golpe en el corte del cold open
STICKERS = RAIZ / "stickers"                   # biblioteca de memes (png + mp3)
TRABAJO = RAIZ / "trabajo"
SALIDA = RAIZ / "salida"
WEB = RAIZ / "web"

for d in (TRABAJO, SALIDA):
    d.mkdir(exist_ok=True)

# ---------------------------------------------------------------- video
ANCHO, ALTO = 1080, 1920
FPS = 60

# La camara se muestra COMPLETA (sin zoom): 1080x608 es el 16:9 escalado,
# y da justo ~1/3 de la altura. El gameplay se queda con los 2/3 de abajo.
CAM_ALTO = 608
GAME_ALTO = ALTO - CAM_ALTO                       # 1312

# Para llenar 1080x1312 desde un 16:9 hay que recortar a lo ancho.
GAME_CROP_ANCHO = 890                              # de 1920; conserva mira, hotbar e inventario
GAME_CROP_X = (1920 - GAME_CROP_ANCHO) // 2

# Correccion de imagen: las grabaciones vienen oscuras
EQ_CAMARA = "eq=brightness=0.07:contrast=1.14:saturation=1.20"
EQ_GAMEPLAY = "eq=brightness=0.04:contrast=1.08:saturation=1.10"

# Calidad de exportacion. NVENC no sirve en esta maquina (pide driver 610+),
# y libx264 da mejor calidad por bit igual.
X264_CRF = 16
X264_PRESET = "slow"

# ---------------------------------------------------------------- audio
# No hay ruido que sacar (SNR medido: 56 dB). Esto solo realza la voz
# sobre el audio del juego y empareja el nivel.
CADENA_AUDIO = (
    "highpass=f=75,"
    "equalizer=f=180:t=q:w=1.0:g=2.0,"        # cuerpo
    "equalizer=f=400:t=q:w=1.2:g=-2.0,"       # saca el 'barro'
    "equalizer=f=3000:t=q:w=1.0:g=3.0,"       # presencia / inteligibilidad
    "equalizer=f=7500:t=q:w=1.5:g=1.5,"       # aire
    "acompressor=threshold=-20dB:ratio=3:attack=15:release=180:makeup=2,"
    "alimiter=limit=0.97,"
    "loudnorm=I=-14:TP=-1.0:LRA=9"            # -14 LUFS: el estandar de TikTok/Reels/Shorts
)

# ---------------------------------------------------------------- subtitulos
ESTILOS_SUB = {
    "anton": dict(nombre="Anton", familia="Anton", ttf="Anton-Regular.ttf",
                  size=100, outline=8, shadow=2),
    "montserrat": dict(nombre="Montserrat ExtraBold", familia="Montserrat ExtraBold",
                       ttf="Montserrat-ExtraBold.ttf", size=88, outline=7, shadow=2),
    "poppins": dict(nombre="Poppins ExtraBold", familia="Poppins ExtraBold",
                    ttf="Poppins-ExtraBold.ttf", size=86, outline=7, shadow=2),
}
ESTILO_SUB_DEFECTO = "anton"
COLOR_ACTIVO = "&H76E600&"      # #00E676 en formato ASS (&HBBGGRR&)
COLOR_BASE = "&HFFFFFF&"
SUB_MARGEN = 80
# posicion vertical: centrado en la zona del gameplay, fuera de la UI de TikTok
SUB_MARGEN_V = ALTO - (CAM_ALTO + GAME_ALTO // 2) - 60

# ---------------------------------------------------------------- deteccion
ASR_MODELO = "large-v3"
ASR_BATCH = 16
ASR_PROMPT = ("Stream de Minecraft en espanol argentino. Servidor Sobrinos de Pepe. "
              "Jerga: boludo, che, posta, capo, re, dale, joya, quilombo, mira, nada, "
              "gede, flaco, tiltear, netherite, diamante, enderman, creeper, spawn, "
              "loot, pvp, farmear, craftear, tp, base, cofre, mina.")

# Se piden clips un poco mas largos de lo que van a quedar: el corte de
# tiempos muertos los comprime bastante (en modo frenetico, hasta un 70%).
CLIP_MIN, CLIP_MAX = 18.0, 75.0
# El usuario fue explicito: prefiere un clip de 10 s frenetico antes que uno de
# 30 s con silencios. Este piso es solo para que no salga un clip inservible de
# 3 segundos; salvo eso, el corte NO se afloja por duracion.
DURACION_MINIMA_FINAL = 6.0
DENSIDAD_MINIMA = 0.62          # % de habla que debe tener una ventana para ser candidata
SEPARACION_MINIMA = 45.0        # segundos entre dos clips, para que no salgan del mismo momento

# Gate de rechazo por % de habla. OJO con subirlo: los clips de REACCION tienen
# mas silencio justamente porque esta reaccionando, y son los mejores para
# gancho. Con el gate en 0,70 se cayeron 3 de los 8 candidatos de un stream,
# entre ellos "El warden nos hizo mierda" (59%) y "Me hizo verga el warden"
# (69%). Ademas el modo "sin respiro" saca ese silencio igual, asi que el gate
# estaba peleando contra el cortador de silencios.
DENSIDAD_CLIP = 0.45

MODELO_LLM = "claude-sonnet-5"

# EFFORT es LA palanca. Sonnet 5 razona por defecto y a effort="high" razona
# "casi siempre": con la transcripcion entera se comio 16.000 y despues 32.000
# tokens pensando, sin emitir una sola linea de respuesta. En "medium" razona lo
# justo. No bajar a "low": en tareas de juicio comparativo como esta hay riesgo
# de que piense de menos, y elegir bien los clips es lo que mas importa.
EFFORT_LLM = "medium"

# Se manda el stream ENTERO en una sola llamada mientras entre: asi el modelo
# compara todos los momentos entre si (ranking global). Partir en bloques impone
# una cuota fija por tramo, que es una suposicion falsa -un stream puede tener
# 15 momentos buenos en la primera hora y 2 en la ultima-.
MAX_PALABRAS_UNA_LLAMADA = 26000
MAX_TOKENS_LLM = 14000           # techo: el JSON de 21 clips son ~4k + razonamiento

# Plan B automatico, solo si la llamada unica se queda sin presupuesto:
MINUTOS_POR_BLOQUE = 35
SOLAPE_BLOQUE = 90.0             # segundos, para no perder un clip en el borde
MAX_TOKENS_BLOQUE = 14000
MAX_TOKENS_RANKEO = 14000

# ---------------------------------------------------------------- el gancho
# El cold open es LA decision que define si el clip se ve o no, y es una sola
# llamada chica por stream (los clips ya elegidos, no la transcripcion entera).
# Por eso aca no se ahorra: Opus 5 con razonamiento alto. Son centavos por
# stream y es lo que mas impacto tiene en el resultado.
MODELO_GANCHO = "claude-opus-5"
EFFORT_GANCHO = "xhigh"
MAX_TOKENS_GANCHO = 32000        # con streaming no hay riesgo de timeout

# Cartel del cold open: 3-6 palabras grandes arriba, sobre la zona de la camara.
# Existe porque el canal visual del cold open esta VACIO -se midio: en los 8
# momentos de mayor energia del stream la cara esta neutra, mirando al monitor,
# en un cuarto oscuro-. Si la imagen no gancha, el gancho hay que escribirlo.
# Es lo PRIMERO que se ve del clip, asi que aca no se ahorra en legibilidad:
# texto blanco sobre una PLACA opaca, con una sombra dura verde detras. El
# borde-contorno no alcanzaba -sobre un gameplay claro el texto blanco con
# contorno oscuro se sigue mezclando con el fondo-; una placa opaca no se
# mezcla con nada, y es lo que usan todos los ganchos que funcionan.
#
# Fuente PROPIA, distinta de la de los subtitulos: si el cartel usa la misma
# tipografia que el karaoke se lee como "un subtitulo mas grande" en vez de como
# un cartel. Montserrat Black es geometrica y pesada, y sobre placa rinde mejor
# que la condensada.
CARTEL_FUENTE = "Montserrat Black"
CARTEL_TTF = "Montserrat-Black.ttf"
CARTEL_ALTO_FUENTE = 1.219       # (ascender - descender) / upem, medido del TTF
CARTEL_SIZE = 104
CARTEL_PAD = 22                  # respiro de la placa alrededor del texto
CARTEL_SOMBRA = 9                # cuanto se corre la sombra dura
# Placa BLANCA con texto casi negro, y no al reves. Probado sobre los dos
# extremos del material: una cueva a oscuras y una pared de arenisca al sol. La
# placa negra se empasta con la cueva y depende de la sombra para separarse; la
# blanca revienta sobre la cueva y sobre la pared clara sigue separada. Tambien
# se probo la placa verde de la marca: llama mas pero se lee mas barata, y
# choca con el verde de la palabra activa del karaoke.
CARTEL_TEXTO = "&H00101010"      # casi negro
CARTEL_PLACA = "&H00F2F2F2"      # blanco (no puro: el 255 flota con la compresion)
CARTEL_SOMBRA_COLOR = "&H0076E600"   # el verde de la marca (#00E676) en BBGGRR

# Va JUSTO DEBAJO de la camara, no arriba de todo: probado arriba, cuando esta
# sentado derecho la cara le queda en el tercio de arriba y el cartel se la tapa.
# Debajo de la camara siempre cae sobre gameplay, y a un tercio de la altura
# total sigue estando donde la gente mira primero.
CARTEL_MARGEN_V = CAM_ALTO + 40
CARTEL_MAX_LINEAS = 2

# La entrada, en tres tiempos: el texto se descubre de izquierda a derecha, la
# sombra verde cae despues, y recien ahi queda quieto hasta el corte. Son tres
# golpes de atencion en el medio segundo que decide si te quedas mirando.
CARTEL_WIPE = 0.16               # el barrido de entrada
CARTEL_SOMBRA_EN = (0.16, 0.30)  # cuando cae la sombra dura

# Golpe de audio en el corte del cold open al clip. Sin el, el corte es mudo y
# se pierde la mitad del efecto de "avance de pelicula".
IMPACTO_VOLUMEN = 0.38
IMPACTO_ADELANTO = 0.05          # cae 50 ms antes del corte, para que pegue justo

# ---------------------------------------------------------------- los memes
# Que meme va, en que segundo y con que sonido es una decision CULTURAL: el
# perro resignado significa "estamos en el horno", no "perro". Eso no sale de
# ningun detector, asi que lo decide Claude leyendo el clip ya montado, y con
# el catalogo de fichas de memes.py como contexto. Es una llamada por stream y
# lo que se juega es que el clip sea gracioso o quede barato: va Opus.
MODELO_MEMES = "claude-opus-5"
EFFORT_MEMES = "high"
MAX_TOKENS_MEMES = 32000         # en extremo pueden salir ~90 memes de golpe

# Volumen de los sonidos de meme. Se mezclan ANTES de la cadena de audio (como
# el golpe del cold open) para que el loudnorm los mida y el clip siga a -14
# LUFS; el precio es que el compresor tambien los ve, y por eso no van a 1.0.
MEMES_VOLUMEN = 0.36

# ---------------------------------------------------------------- entorno
# OJO: la key de esta app es SIEMPRE la del .env de este proyecto, y se pasa
# explicita al cliente. Usa un nombre propio (CLIPS_API_KEY) para que no pueda
# tomar por accidente una ANTHROPIC_API_KEY de otra cuenta que este en el sistema.
VAR_KEY = "CLIPS_API_KEY"


def leer_env():
    """Lee el .env de la raiz sin dependencias externas. Devuelve un dict."""
    f = RAIZ / ".env"
    if not f.exists():
        return {}
    vals = {}
    for linea in f.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def api_key():
    """La API key de la cuenta del stream. Solo del .env, nunca del entorno."""
    return (leer_env().get(VAR_KEY) or "").strip()


def key_visible():
    """Identificador seguro para mostrar en la UI y confirmar que cuenta se usa."""
    k = api_key()
    if not k:
        return None
    return f"{k[:11]}...{k[-4:]}" if len(k) > 18 else "(key corta)"


def dlls_cuda():
    """CTranslate2 en Windows necesita cudnn/cublas: reusa las que ya trae torch."""
    try:
        import torch
        d = Path(torch.__file__).parent / "lib"
        if d.exists():
            os.add_dll_directory(str(d))
    except Exception:
        pass
