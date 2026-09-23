# -*- coding: utf-8 -*-
"""Memes: stickers con sonido que aparecen sobre el gameplay y se van enseguida.

QUE HACE
--------
Mete en el clip los memes de la carpeta `stickers/`: aparecen de golpe sobre el
gameplay -nunca sobre la camara-, duran un segundo y pico, cambian de lugar cada
vez, y muchos traen su sonido. Es contenido extra sin material extra: mas cosas
que mirar por segundo, que es lo unico que sostiene un vertical.

QUIEN DECIDE QUE MEME VA Y DONDE
---------------------------------
Claude, leyendo el clip ya montado. No hay deteccion de nada: el chiste de un
meme es CULTURAL -el perro resignado significa "estamos en el horno", no
"perro"- y eso no sale de un clasificador, sale de entender lo que se dice.

Cada meme del catalogo de aca abajo tiene su ficha escrita: que se ve, que
significa hoy en TikTok y en que momento se usa. Esa ficha es la mitad del
trabajo: sin ella el modelo pone el gato de la risa en cualquier lado.

POR QUE SOBRE EL RELOJ DEL CLIP TERMINADO
------------------------------------------
El clip se arma cortando tiempos muertos y pegando un cold open adelante: un
segundo del stream original puede no existir en el clip, o aparecer dos veces.
Asi que el plan de memes se calcula DESPUES del montaje, sobre la transcripcion
ya remapeada. Si se calculara antes, un meme pensado para un remate caeria en
cualquier lado -o en un pedazo que se corto-.

POR QUE LOS STICKERS SE PREPARAN CON PIL Y NO EN FFMPEG
--------------------------------------------------------
Los 12 archivos son fotos rectangulares y OPACAS (medido: 0% de pixeles
transparentes en los 12). Pegar una foto rectangular sobre el gameplay se ve
como un error. Se les fabrica el look de sticker -esquinas redondeadas, marco
blanco, sombra y una inclinacion leve- una sola vez con PIL, y queda cacheado en
la carpeta de trabajo. Hacerlo por frame en ffmpeg costaria en cada render lo
mismo que aca cuesta una vez.
"""
import math
import random
import unicodedata
from pathlib import Path

from .config import (ALTO, ANCHO, CAM_ALTO, EFFORT_MEMES, MAX_TOKENS_MEMES,
                     MEMES_VOLUMEN, MODELO_MEMES, STICKERS, VAR_KEY, api_key)

# ---------------------------------------------------------------- niveles
# `cada` son los segundos entre meme y meme que se le PIDEN al modelo; el tope
# real es `maximo`. `separacion` es lo que se valida despues: dos memes mas
# juntos que eso se descartan.
#
# Los tres niveles se bajaron el 2026-09-21, despues de verlos andando: los tres
# estaban altos y no quedaba escalon para abajo. Ahora el defecto son DOS O TRES
# memes por clip, que es lo que pidio el usuario: pocos, grandes y bien puestos.
# Un meme que aparece cada dos segundos deja de ser un chiste y pasa a ser ruido.
NIVELES = {
    "apagado": None,
    "poco": dict(
        cada=22.0, maximo=2, separacion=6.0, repetir_tras=None,
        nota="Este stream va con MUY POCOS memes: como mucho uno o dos por clip, y "
             "solo en el momento mas fuerte de todos. Si un clip no tiene ninguno "
             "que valga de verdad la pena, dejalo vacio; es una opcion valida."),
    "medio": dict(
        cada=12.0, maximo=3, separacion=3.5, repetir_tras=None,
        nota="Dos o tres memes por clip, en los mejores momentos. Cada uno tiene "
             "que ganarse el lugar: si dudas entre poner uno mas o no ponerlo, no "
             "lo pongas."),
    "extremo": dict(
        cada=6.0, maximo=6, separacion=2.0, repetir_tras=12.0,
        nota="Bastantes memes: uno cada cinco o seis segundos. Aca si podes usar "
             "momentos apenas graciosos, y hasta neutros si el meme funciona como "
             "comentario ironico. Podes repetir un meme en el mismo clip si pasaron "
             "unos diez segundos."),
}
NIVEL_DEFECTO = "medio"

DUR_MIN, DUR_MAX = 0.6, 2.4       # cuanto se queda en pantalla
DUR_DEFECTO = 1.3


# ---------------------------------------------------------------- estilos
# DOS MANERAS DE MOSTRAR EL MEME, y la diferencia no es cosmetica.
#
# `sticker` fue la primera: chiquito, marco blanco, esquinas redondeadas, sombra,
# inclinado, y entra con un rebote. Esta prolijo. Y ESE es el problema: el
# usuario lo vio andando y dijo que "al estar muy bien editado le saca gracia".
# Tiene razon, y es la misma logica por la que el zoom va a saltos secos y los
# empalmes son jump cuts duros: lo que da risa hoy es que se vea MAL editado. Un
# sticker con sombra y rebote se lee como plantilla de editor; una foto enorme
# tirada encima del gameplay se lee como que alguien la pego ahi a mano.
#
# `crudo` es esa segunda manera, y es la de por defecto: la foto sola, sin marco
# ni sombra ni inclinacion, gigante -puede tapar el gameplay entero, y esta bien
# que lo tape-, y SIN NINGUNA ANIMACION: aparece y desaparece de golpe. Encima
# sale mas barato de renderizar, porque sin animacion el `scale` no necesita
# recalcularse por frame.
#
# Lo unico que los dos respetan es la camara: la cara no se tapa nunca.
ESTILOS = {
    "crudo": dict(
        etiqueta="Crudo (mal editado a proposito)",
        tamanos=dict(chico=680, mediano=880, grande=1120),
        marco=False, radio=0.0, sombra=False, inclinar=False,
        pop=0.0, bamboleo=0.0, jitter=(10, 12), sangrado=60, lado=1024,
        respeta_subtitulos=False,
        nota_modelo="Los memes se ven ENORMES: ocupan casi toda la pantalla y tapan "
                    "el gameplay entero. No importa que lo tapen. Por eso `posicion` "
                    "casi no cambia nada -elegila igual, para que dos seguidos no "
                    "caigan clavados en el mismo lugar- y `tamano` es lo que importa: "
                    "chico ya tapa medio gameplay, grande tapa la pantalla de lado a "
                    "lado. Ante la duda, grande."),
    "sticker": dict(
        etiqueta="Sticker (chico, con marco blanco)",
        tamanos=dict(chico=280, mediano=360, grande=440),
        marco=True, radio=0.07, sombra=True, inclinar=True,
        pop=0.20, bamboleo=5.0, jitter=(16, 15), sangrado=4, lado=640,
        respeta_subtitulos=True,
        nota_modelo="Los memes se ven como stickers chicos pegados en una esquina "
                    "del gameplay, asi que la `posicion` importa: ir cambiandola."),
    }
ESTILO_DEFECTO = "crudo"

# Los nombres de tamaño son los mismos en los dos estilos; lo que cambia es a
# cuantos pixeles corresponde cada uno (ver `tamanos` de cada estilo).
TAMANOS = ("chico", "mediano", "grande")

# El rebote de entrada del estilo `sticker`. `crudo` no tiene ninguno.
POP_CAIDA, POP_FRECUENCIA = 11.0, 16.0
BAMBOLEO_HZ = 1.4

COLUMNAS = dict(izq=282, centro=540, der=798)
POSICIONES = tuple(f"{f}-{c}" for f in ("arriba", "abajo") for c in COLUMNAS)


# DONDE PUEDE IR EL MEME. Cada franja es (centro_y, y_minimo, y_maximo): el
# ancla donde se lo quiere poner, y los limites duros que no puede cruzar.
#
# Los numeros salen de medir el layout, no de tantear:
#   - la camara termina en y=608, y ESE limite no se cruza en ningun estilo:
#     taparle la cara es lo unico que el usuario pidio que no pasara nunca;
#   - el subtitulo ocupa de y=1176 a y=1324. Es SIEMPRE una sola linea -no es una
#     suposicion: `armar_cues` corta el cartel cuando el ancho medido pasa el
#     margen, y con WrapStyle 2 libass no parte nada por su cuenta; contados
#     2.093 subtitulos ya generados, cero con salto de linea-;
#   - de 1800 para abajo ya se lo empieza a comer la interfaz de TikTok.
#
# El estilo `sticker` respeta las dos cosas y se mete en los huecos. El `crudo`
# solo respeta la camara: tapar el subtitulo un segundo es parte del chiste.
def _franjas(con_camara, estilo=ESTILO_DEFECTO):
    techo = CAM_ALTO if con_camara else 120
    if ESTILOS[estilo]["respeta_subtitulos"]:
        return dict(arriba=(892, techo, 1176), abajo=(1566, 1324, 1800))
    # el gameplay entero: el meme se centra abajo o arriba de esa banda
    medio = (techo + ALTO) // 2
    return dict(arriba=(medio - 210, techo, ALTO), abajo=(medio + 220, techo, ALTO))


def _alto_tope(franja, estilo=ESTILO_DEFECTO):
    """El alto maximo del meme YA ASENTADO para que ni en el pico del rebote se
    salga de su franja.

    Se acota por el PICO y no por el tamaño final: medido sobre un render, un
    sticker de 440 px asentado llegaba a 546 px en el primer frame del golpe y
    se metia 12 px dentro de la webcam. Dura dos frames, pero es justo lo que se
    pidio que no pasara. (En `crudo` no hay rebote, asi que pico = tamaño.)
    """
    e = ESTILOS[estilo]
    _, y0, y1 = franja
    return (y1 - y0 - 2 * e["jitter"][1]) / (1.0 + e["pop"])


# ---------------------------------------------------------------- sonidos
# `desde`/`hasta` salen de medir la envolvente de energia de cada archivo: casi
# todos traen cola, silencio adelante o dos golpes separados, y pegarlos enteros
# seria taparle la voz al clip durante seis segundos.
# CADA SONIDO, CON SU TONO. El tono es lo que decide con que meme puede ir: una
# musica tetrica debajo de una cara feliz no da risa, da confusion. Cada meme
# declara abajo que tonos le quedan bien, y `resolver` lo hace cumplir.
#
# Dos de estos estaban mal identificados por el nombre del archivo y se
# corrigieron buscando el origen de cada uno:
#   - "AUGGHH AHHHHH" NO es un grito de agonia: es un RONQUIDO exagerado (el
#     "goofy ahh" de TikTok, de un guardia que se durmio sobre un altavoz). Se
#     ve en la envolvente: dos golpes con silencio en el medio, que son la
#     inhalacion y la exhalacion. Estaba puesto en `locura`, donde no pegaba
#     nada; va con el perro durmiendo.
#   - "Plankton Groan" no es un quejido de dibujito: es el gemido grave y
#     fantasmal del "Cursed Plankton", que es tetrico, no comico.
TONOS = ("risa", "travieso", "grito", "tetrico", "dramatico", "triste")

SONIDOS = {
    "risa_gato": dict(
        carpeta="gato riendose", busca="cat laughing", desde=0.0, hasta=2.4, tono="risa",
        nombre="Gato cagandose de risa",
        cuando="Risa burlona y descarada, justo encima de la desgracia de otro."),
    "cocinado": dict(
        carpeta="perro", busca="cooked dog", desde=0.0, hasta=3.0, tono="triste",
        nombre="Musica del perro resignado (cooked)",
        cuando="Resignacion melancolica: ya esta, no hay vuelta atras."),
    "fahh": dict(
        busca="fahh", desde=0.88, hasta=2.6, tono="grito",
        nombre="El 'FAHHH' distorsionado",
        cuando="Remate de shock o de desastre chico. Es el 'uuuh, la cagaste' de "
               "TikTok: algo salio mal justo ahi."),
    "ah": dict(
        busca="ah sound effect", desde=0.6, hasta=2.3, tono="grito",
        nombre="Grito corto y fuerte con eco",
        cuando="Susto o dolor de golpe. Es el mas neutro de los gritos: sirve casi "
               "en cualquier lado donde algo pega fuerte."),
    "ronquido": dict(
        busca="augghh", desde=0.3, hasta=2.0, tono="travieso",
        nombre="Ronquido exagerado (el 'goofy ahh' de TikTok)",
        cuando="Alguien se durmio, se aburrio o esta en otra. Va encima de una "
               "explicacion larga o de un momento muerto. Es comico, no dramatico."),
    "andate": dict(
        busca="get out", desde=0.18, hasta=1.3, tono="grito",
        nombre="Alguien grita GET OUT",
        cuando="Echar a alguien, 'andate', 'sali de aca'. Tambien para cortar una "
               "frase de golpe."),
    "cueva": dict(
        busca="cave ambience", desde=0.0, hasta=2.6, tono="tetrico",
        nombre="Sonido de cueva de Minecraft",
        cuando="Silencio incomodo: alguien dijo algo y no le contesto nadie. El "
               "publico de Minecraft lo reconoce al instante y por eso pega el doble."),
    "quejido": dict(
        busca="plankton", desde=1.2, hasta=4.0, tono="tetrico",
        nombre="El gemido del Cursed Plankton",
        cuando="Fastidio con onda perturbadora. Grave y fantasmal: va donde algo "
               "incomoda o donde alguien ya no da mas, no donde algo da risa."),
    "amenaza": dict(
        busca="prowler", desde=1.0, hasta=3.4, tono="dramatico",
        nombre="Tema del Merodeador (Spider-Verse)",
        cuando="Entrada amenazante o revelacion: aparece alguien, se viene algo, se "
               "descubre quien fue. Grave y cinematografico."),
    "inquietante": dict(
        busca="annihilation", desde=0.2, hasta=2.8, tono="tetrico",
        nombre="El alien de Annihilation",
        cuando="Algo perturbador o directamente raro. Para cuando alguien dice una "
               "cosa que incomoda, o hay algo que da mala espina."),
}

# ---------------------------------------------------------------- catalogo
# La ficha de cada meme. Esto es lo que lee el modelo: si esta mal escrita, el
# meme cae en el momento equivocado por mas bueno que sea todo el resto.
CATALOGO = {
    "gato_burlon": dict(
        carpeta="gato riendose", sonido="risa_gato", tonos=("risa", "grito",),
        nombre="Gato cagandose de risa y señalando",
        que_es="Un gato blanco con la boca abierta de par en par gritando de risa, "
               "y una mano de emoji amarilla que señala a camara.",
        cuando="Burla directa y sin piedad de una desgracia ajena. Es el meme mas "
               "agresivo de la biblioteca: va cuando alguien FALLA y da risa que "
               "haya fallado. Se muere con todo encima, lo estafan, se cae al "
               "vacio, pierde una pelea, lo descubren.",
        ojo="No va con una desgracia que de lastima de verdad; va con la que da risa."),
    "gato_picaro": dict(
        carpeta="gato", sonido="risa_gato", tonos=("risa", "travieso",),
        nombre="Gato con sonrisita de complice",
        que_es="Un gato blanco con los ojos entrecerrados y una sonrisa contenida, "
               "la lengua apenas afuera. Cara de 'jeje, yo se algo'.",
        cuando="Maldad chiquita y confesada: alguien admite que hizo una travesura, "
               "planea una joda, se hace el vivo, disimula. Es risita de complice, "
               "no burla: va con el que la hizo, no contra el que la sufrio.",
        ojo="Si la maldad ya salio mal y alguien esta sufriendo, va gato_burlon."),
    "gato_serio": dict(
        carpeta="gato negro", sonido="cueva", tonos=("tetrico", "dramatico",),
        nombre="Gato negro con cara de hombre mirando fijo",
        que_es="Un gato negro con una cara humana pegada encima, en blanco y negro, "
               "mirando fijo a camara sin ninguna expresion. Da cosa.",
        cuando="La mirada de juicio. Alguien dice una barbaridad, una mentira "
               "descarada o algo sin sentido, y la respuesta es el silencio. "
               "Tambien para el momento incomodo en que nadie sabe que contestar.",
        ojo="Es mirada, no risa: si el momento es gracioso y ruidoso, no es este."),
    "conexion_cerebral": dict(
        carpeta="conexion cerebral", sonido="amenaza", tonos=("dramatico", "travieso",),
        nombre="Dos cerebros conectados por un rayo",
        que_es="Dos hombres azules de perfil, frente a frente, con los cerebros "
               "encendidos y un rayo que va de una cabeza a la otra. El 'galaxy brain'.",
        cuando="Dos personas piensan lo mismo al mismo tiempo, o alguien larga una "
               "idea que suena a plan maestro. Lo mejor es usarlo IRONICO: cuando "
               "el 'plan brillante' es una estupidez enorme, el meme lo trata de "
               "genialidad y ahi esta el chiste.",
        ojo="Solo sirve si en la frase hay una IDEA o un PLAN."),
    "hombre_enojado": dict(
        carpeta="hombreenojado", sonido="quejido", tonos=("grito", "tetrico",),
        nombre="Señor con cara de orto",
        que_es="Un señor grande, medio pelado, sentado en un bar, mirando de costado "
               "con una cara de desprecio absoluto. No dice nada.",
        cuando="Reproche y fastidio. Alguien se queja, reclama, putea a otro, o dice "
               "algo que no le causo gracia a nadie. Es la cara del que ya esta "
               "harto. Cae perfecto encima de una puteada o de un reclamo.",
        ojo=None),
    "locura": dict(
        carpeta="locura", sonido="ah", tonos=("grito", "tetrico",),
        nombre="Tipo enloqueciendo en un cuarto acolchado",
        que_es="Un tipo vestido de blanco sentado en el rincon de una celda "
               "acolchada de manicomio, mordiendose la mano, con la mirada perdida.",
        cuando="Se le fue la paciencia. Algo que se repite y ya no se aguanta, una "
               "frustracion que viene de hace rato, 'me esta volviendo loco', 'es la "
               "tercera vez que me pasa'. Va con bronca acumulada, no con un susto.",
        ojo=None),
    "perrito_asustado": dict(
        carpeta="perrito asustado", sonido="amenaza", tonos=("dramatico", "tetrico", "grito",),
        nombre="Perrito chiquito cagado de miedo",
        que_es="Un perro chico, sentado, encogido, con la cabeza gacha y cara de "
               "susto y de culpa al mismo tiempo.",
        cuando="Miedo o culpa. Se viene algo feo -un monstruo, el warden, un creeper, "
               "alguien enojado que ya llega-, o alguien la mando y esta esperando el "
               "reto. Tambien el clasico 'ay no' justo antes de que pase.",
        ojo="Va ANTES del desastre o durante el miedo, no despues."),
    "perrito_durmiendo": dict(
        carpeta="perrito durmiendo", sonido="ronquido", tonos=("travieso", "triste",),
        nombre="Perrito durmiendo con cuerno de unicornio",
        que_es="Un perrito blanco panza arriba, dormido, con un cuerno de unicornio "
               "de juguete en la cabeza y un fondo de galaxia con arcoiris.",
        cuando="Aburrimiento y desconexion. Alguien explica algo largo, repite lo "
               "mismo por quinta vez, o esta en su mundo sin escuchar a nadie. Es el "
               "'me dormi' puesto encima de la explicacion.",
        ojo=None),
    "perro_cocinado": dict(
        carpeta="perro", sonido="cocinado", tonos=("triste", "dramatico",),
        nombre="Perro resignado mirando el atardecer (cooked)",
        que_es="Un labrador marron viejo, con los ojos entrecerrados, mirando a lo "
               "lejos con el sol del atardecer en la cara. Es el meme 'cooked'.",
        cuando="Ya esta, se acabo, no hay vuelta atras. Aceptar la derrota sin "
               "pelearla: 'estamos en el horno', 'perdi todo', 'me van a matar'. Es "
               "resignacion tranquila y triste, y ahi esta lo gracioso.",
        ojo="Si hay grito o bronca, no es este: este es el que ya se rindio."),
    "robot_shock": dict(
        carpeta="robot", sonido="fahh", tonos=("grito", "travieso", "tetrico",),
        nombre="El robot de Yo Robot con cara de shock",
        que_es="La cara palida del robot Sonny de 'Yo, Robot', con los ojos bien "
               "abiertos, mirando fijo sin parpadear.",
        cuando="No entender nada. Alguien dice algo random, fuera de contexto o tan "
               "raro que corta la conversacion. Es la cara de '¿que?' sostenida dos "
               "segundos.",
        ojo=None),
    "piedra_a_si_mismo": dict(
        carpeta="rocaaelmismo", sonido="fahh", tonos=("grito", "risa",),
        nombre="El tipo pegandose con una piedra a si mismo",
        que_es="El mismo señor dos veces en la misma foto: uno levanta una piedra y "
               "esta por pegarle en la cabeza al otro, que ni lo ve venir.",
        cuando="Autosabotaje. Alguien se caga solo: se cae al vacio sin que nadie lo "
               "empuje, se muere con su propia trampa, toma una decision que lo "
               "perjudica, cuenta algo que no tenia que contar. El chiste es que "
               "nadie se lo hizo.",
        ojo="Tiene que quedar claro que la victima y el culpable son el mismo."),
    "tiro_desde_la_luna": dict(
        carpeta="tiroalaire", sonido="fahh", tonos=("grito", "travieso", "dramatico",),
        nombre="Stephen Curry tirando al aro desde la luna",
        que_es="Un basquetbolista parado en la luna, tirando la pelota hacia la "
               "Tierra, que se ve chiquita al fondo.",
        cuando="Exageracion o distancia imposible. Alguien acierta un flechazo desde "
               "la otra punta, tira algo lejisimos, o larga una afirmacion tan "
               "exagerada que 'se fue a la luna'.",
        ojo=None),
}


# ------------------------------------------------------------- biblioteca
def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _buscar(carpeta, patron, ext):
    """El archivo de `carpeta` cuyo nombre contiene `patron`. None si no esta.

    Se busca por trozo de nombre y no por nombre exacto a proposito: dos de los
    mp3 tienen comillas tipograficas en el nombre, y cualquier retoque de la
    carpeta -renombrarlo, volver a bajarlo- romperia una coincidencia exacta sin
    que se note hasta el render.
    """
    if not carpeta.is_dir():
        return None
    p = _norm(patron)
    for f in sorted(carpeta.iterdir()):
        if f.suffix.lower() == ext and p in _norm(f.name):
            return f
    return None


def _carpeta_sonidos():
    """La carpeta de sonidos sueltos, por nombre aproximado."""
    if STICKERS.is_dir():
        for d in sorted(STICKERS.iterdir()):
            if d.is_dir() and "sonido" in _norm(d.name):
                return d
    return STICKERS


def sonidos():
    """Los sonidos que existen de verdad en el disco, con su recorte."""
    fuera = {}
    for k, s in SONIDOS.items():
        base = (STICKERS / s["carpeta"]) if s.get("carpeta") else _carpeta_sonidos()
        f = _buscar(base, s["busca"], ".mp3")
        if f:
            fuera[k] = dict(s, ruta=f, id=k)
    return fuera


def biblioteca():
    """Los memes que existen de verdad, con su png y su sonido ya resuelto."""
    snd = sonidos()
    fuera = {}
    for k, m in CATALOGO.items():
        d = STICKERS / m["carpeta"]
        if not d.is_dir():
            continue
        pngs = sorted(p for p in d.iterdir() if p.suffix.lower() == ".png")
        if not pngs:
            continue
        fuera[k] = dict(m, id=k, imagen=pngs[0],
                        sonido=m["sonido"] if m["sonido"] in snd else None)
    return fuera


def faltantes():
    """Carpetas de stickers sin ficha en el catalogo. Para avisar, no para romper."""
    if not STICKERS.is_dir():
        return []
    conocidas = {_norm(m["carpeta"]) for m in CATALOGO.values()}
    fuera = []
    for d in sorted(STICKERS.iterdir()):
        if not d.is_dir() or "sonido" in _norm(d.name):
            continue
        if _norm(d.name) not in conocidas and any(
                p.suffix.lower() == ".png" for p in d.iterdir()):
            fuera.append(d.name)
    return fuera


# -------------------------------------------------------- look de sticker
def preparar(origen, destino, estilo=ESTILO_DEFECTO, angulo=0):
    """Le fabrica el look de sticker a la foto: marco blanco, esquinas y sombra.

    Los 12 archivos son fotos opacas y rectangulares. Asi pegadas se leen como un
    error de edicion; con el marco blanco y la sombra se leen como un sticker
    puesto a proposito, que es lo que hace todo el mundo en TikTok.

    La inclinacion se hornea aca y no en ffmpeg: rotar por frame costaria en cada
    render lo que aca cuesta una sola vez, y el angulo no cambia con el tiempo.
    """
    from PIL import Image, ImageDraw, ImageFilter

    destino = Path(destino)
    if destino.exists():
        with Image.open(destino) as im:
            return im.size

    e = ESTILOS[estilo]
    im = Image.open(origen).convert("RGBA")
    im.thumbnail((e["lado"], e["lado"]), Image.LANCZOS)
    w, h = im.size
    m = min(w, h)

    if e["radio"]:
        radio = int(m * e["radio"])
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radio, fill=255)
        im.putalpha(mask)
    else:
        radio = 0

    if e["marco"]:
        borde = max(6, int(m * 0.045))
        W, H = w + 2 * borde, h + 2 * borde
        marco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        mm = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mm).rounded_rectangle([0, 0, W - 1, H - 1], radio + borde, fill=255)
        blanco = Image.new("RGBA", (W, H), (255, 255, 255, 255))
        blanco.putalpha(mm)
        marco.alpha_composite(blanco)
        marco.alpha_composite(im, (borde, borde))
    else:
        marco = im
    if e["inclinar"] and angulo:
        marco = marco.rotate(angulo, resample=Image.BICUBIC, expand=True)

    if e["sombra"]:
        d, off = max(8, int(m * 0.05)), max(4, int(m * 0.028))
        lienzo = Image.new("RGBA", (marco.width + 4 * d, marco.height + 4 * d), (0, 0, 0, 0))
        sombra = Image.new("RGBA", lienzo.size, (0, 0, 0, 0))
        sombra.paste((0, 0, 0, 170), (2 * d + off, 2 * d + off), marco.split()[3])
        lienzo.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(d * 0.55)))
        lienzo.alpha_composite(marco, (2 * d, 2 * d))
        marco = lienzo.crop(lienzo.getbbox())

    destino.parent.mkdir(parents=True, exist_ok=True)
    marco.save(destino)
    return marco.size


# ------------------------------------------------------------------ guion
def guion(palabras, huecos, duracion, decimales=1):
    """La transcripcion del clip YA MONTADO, en frases con su segundo.

    `huecos` son los tramos donde el detector de voz oye algo y el transcriptor
    no escribio nada: risas, gritos, quejidos. Entran al guion marcados, porque
    son justo los momentos donde mejor cae un meme y en el texto pelado no
    aparecen -Whisper escribe "jaj*" una sola vez en dos horas de stream-.
    """
    items = [dict(a=w["a"], b=w["b"], t=w["t"], risa=False) for w in palabras]
    items += [dict(a=a, b=b, t="(risa/grito/reaccion sin palabras)", risa=True)
              for a, b in huecos]
    items.sort(key=lambda w: w["a"])

    lineas, cur = [], []
    for w in items:
        if cur and (w["risa"] or cur[-1]["risa"]
                    or w["a"] - cur[-1]["b"] > 0.4 or len(cur) >= 9
                    or cur[-1]["t"].rstrip().endswith((".", "!", "?", "…"))):
            lineas.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lineas.append(cur)

    fuera = []
    for l in lineas:
        a, b = l[0]["a"], l[-1]["b"]
        if a > duracion + 0.5:
            continue
        txt = " ".join(w["t"] for w in l).strip()
        fuera.append(f"  [{a:.{decimales}f}-{b:.{decimales}f}] {txt}")
    return "\n".join(fuera)


# ----------------------------------------------------------------- prompt
CRITERIO = """Sos el editor de un canal de clips de Minecraft en español argentino. Tu trabajo es meter STICKERS DE MEME encima del gameplay: aparecen de golpe, duran un segundo y pico, y se van. Muchos traen sonido.

POR QUE SE HACE: un vertical se pierde cuando pasan dos segundos sin que aparezca nada nuevo. El meme es contenido extra sin material extra. Pero un meme puesto en el momento equivocado hace el efecto contrario: se lee como relleno y el clip queda barato.

LAS TRES REGLAS QUE IMPORTAN

1. EL MEME CAE EN EL REMATE, NO ANTES. El sticker aparece EXACTAMENTE cuando se escucha la palabra que lo justifica, o un pelin despues (hasta 0,2 s). Si se adelanta, spoilea el chiste. Si llega tarde, el que mira ya paso a otra cosa. Mirá los segundos de cada frase y elegí el instante, no la frase entera.

2. CONTRASTE ANTES QUE LITERALIDAD. El meme que solo ilustra lo que se dice no suma nada: si dice "un perro" y aparece un perro, eso es una foto, no un chiste. El que suma es el que le pone un COMENTARIO a lo que pasa. Alguien cuenta orgulloso un plan penoso -> los cerebros conectados, tratandolo de genio. Alguien perdio todo y lo cuenta tranquilo -> el perro resignado. La ironia es el chiste.

3. LO QUE NO TIENE GRACIA, VA VACIO. No hay ninguna obligacion de llenar el clip. Si en diez segundos no pasa nada que merezca un meme, no pongas ninguno y guardalos para donde de verdad pega. Tres memes bien puestos valen mas que diez de relleno.

LO QUE MEJOR FUNCIONA, POR ORDEN
- Encima de una REACCION sin palabras (en el guion aparecen marcadas: risas, gritos, quejidos). Ahi el meme es la traduccion visual de lo que se escucha y siempre pega.
- Encima de una puteada, un grito o un reclamo.
- En el remate de una historia: el segundo exacto en que se entiende que algo salio mal.
- Cuando alguien queda en ridiculo, se caga solo, o dice una barbaridad.

LO QUE NO FUNCIONA
- Coordinacion y logistica ("dale, voy", "esperame aca"): no hay de que reirse.
- Poner el mismo meme dos veces en un clip. Y en el stream entero, repetir poco: si ya usaste el gato burlon en tres clips, buscá otro.
- Amontonar dos memes en la misma frase, salvo que el momento sea enorme.
- Poner uno en el primer medio segundo del clip: recien arranca.

EL SONIDO
TODOS los memes llevan sonido, sin excepcion: la gente mira estos videos por el ruido, y un meme mudo directamente no se registra. Pero el sonido tiene que PEGAR con el meme: una musica tetrica debajo de una cara feliz no da risa, da confusion. Cada meme trae abajo la lista de los sonidos que le quedan bien; elegí de ahi.

EL LUGAR
Cada meme va en una de seis posiciones sobre el gameplay, y conviene ir cambiando: dos seguidos en el mismo lugar se leen como que quedo pegado. Nunca van sobre la camara: la cara del streamer no se tapa jamas. Cuanto pesa la posicion depende de como se vean, y eso te lo digo mas abajo."""

PROMPT = """{criterio}

LA BIBLIOTECA

{memes}

SONIDOS SUELTOS (se le pueden pegar a cualquier meme)

{sonidos}

POSICIONES: {posiciones}
TAMAÑOS: {tamanos}

COMO SE VEN EN PANTALLA

{estilo}

LOS CLIPS

Abajo van {n} clips YA MONTADOS de un stream de Minecraft en español argentino. El streamer es Tobi; juega en un servidor con amigos y lo que se escucha es sobre todo la charla entre ellos: drama del server, robos de bases, humor, puteadas.

Los segundos son los del CLIP TERMINADO (arranca en 0). Ya estan cortados los tiempos muertos, asi que va todo muy rapido: no sobra ni un segundo.

{clips}

{nota}

Cada clip trae arriba a cuantos memes apuntar, calculado por su duracion. Es una referencia, no una cuota exacta.
De cada meme: `t` (el segundo exacto en que aparece), `meme` (el id de la biblioteca), `posicion`, `tamano`, `dur` (entre {dmin} y {dmax} segundos), `sonido` y `por_que` en diez palabras.

EL SONIDO ES OBLIGATORIO: todos los memes llevan uno. La gente mira estos videos por el ruido, y un meme mudo no se registra. Si ninguno de los sueltos te cierra, usá el sonido propio del meme."""


def sonidos_de(m, snd):
    """Los sonidos que le quedan bien a este meme, por tono. El propio, primero.

    El tono es lo que evita el desastre tipico: una musica tetrica debajo de una
    cara feliz. No alcanza con describirle los sonidos al modelo -aca se le
    acota de que lista puede elegir, y `resolver` lo vuelve a comprobar-.
    """
    ok = [k for k, x in snd.items() if x["tono"] in m.get("tonos", TONOS)]
    propio = m.get("sonido")
    if propio in ok:
        ok.remove(propio)
        ok.insert(0, propio)
    return ok


def _ficha(m, snd):
    l = [f"[{m['id']}] {m['nombre']}",
         f"   Que se ve: {m['que_es']}",
         f"   Cuando va: {m['cuando']}"]
    if m.get("ojo"):
        l.append(f"   Ojo: {m['ojo']}")
    ok = sonidos_de(m, snd)
    if ok:
        l.append(f"   Sonidos que le quedan bien: {', '.join(ok)}"
                 f"  (si no elegis, va {ok[0]})")
    return "\n".join(l)


def _bloque(c, cfg):
    n = max(1, min(cfg["maximo"], round(c["duracion_final"] / cfg["cada"])))
    cab = f"--- CLIP {c['n']}: \"{c.get('titulo','')}\" ({c['duracion_final']:.0f}s)  ->  apuntá a unos {n} memes"
    if c.get("desde"):
        cab += (f"\n    OJO: los primeros {c['desde']:.1f} s son el adelanto y tienen "
                f"un cartel de texto grande encima. No pongas memes antes de "
                f"{c['desde'] + 0.2:.1f} s.")
    return f"{cab}\n{c['guion']}"


def _esquema(ids_meme, ids_sonido, posiciones):
    """El esquema de salida. Los ids van como enumeracion, no como texto libre:
    asi el modelo no puede inventar un meme que no existe."""
    from typing import Literal

    from pydantic import BaseModel, ConfigDict, Field

    Meme = Literal[tuple(ids_meme)]          # type: ignore[valid-type]
    Sonido = Literal[tuple(ids_sonido)]      # type: ignore[valid-type]
    Pos = Literal[tuple(posiciones)]         # type: ignore[valid-type]

    class M(BaseModel):
        model_config = ConfigDict(extra="forbid")
        t: float = Field(description="Segundo exacto del clip en que aparece")
        meme: Meme = Field(description="Id del meme en la biblioteca")
        posicion: Pos = Field(description="Donde aparece, siempre sobre el gameplay")
        tamano: Literal["chico", "mediano", "grande"]
        dur: float = Field(description="Cuantos segundos se queda en pantalla")
        sonido: Sonido = Field(description="Id del sonido. Obligatorio: tiene que "
                               "ser uno de los que la ficha del meme lista como "
                               "que le quedan bien")
        por_que: str = Field(description="Por que cae bien ahi. Maximo 10 palabras.")

    class C(BaseModel):
        model_config = ConfigDict(extra="forbid")
        clip: int = Field(description="El numero de clip al que corresponde")
        memes: list[M]

    class R(BaseModel):
        model_config = ConfigDict(extra="forbid")
        clips: list[C]

    return R


# ------------------------------------------------------------- la llamada
def elegir(clips, nivel=NIVEL_DEFECTO, estilo=ESTILO_DEFECTO, cb=None, modelo=None):
    """Elige los memes de todos los clips en UNA sola llamada.

    Van todos juntos para que el modelo no repita el mismo meme en los diez
    clips: el repertorio es de doce, y usado clip por clip se agota en dos.

    `clips` son dicts con n, titulo, duracion_final, guion y desde (el largo del
    cold open, si hay). Devuelve dict(planes={n: [...]}, uso={...}).

    Lanza RuntimeError si la llamada no se pudo completar: el que llama NO debe
    cachear un resultado vacio, porque seria dejar ese stream sin memes para
    siempre y en silencio.
    """
    import anthropic

    cfg = NIVELES.get(nivel)
    if not cfg or not clips:
        return dict(planes={}, uso={})
    key = api_key()
    if not key:
        raise RuntimeError(f"Falta la API key: pone {VAR_KEY}=sk-ant-... en el .env")

    lib, snd = biblioteca(), sonidos()
    if not lib:
        raise RuntimeError(f"No encontre ningun meme en {STICKERS}")

    prompt = PROMPT.format(
        criterio=CRITERIO,
        memes="\n\n".join(_ficha(m, snd) for m in lib.values()),
        sonidos="\n".join(f"[{k}] {s['nombre']} — {s['cuando']}" for k, s in snd.items()),
        posiciones=", ".join(POSICIONES),
        tamanos=", ".join(f"{k} ({v} px de ancho)"
                          for k, v in ESTILOS[estilo]["tamanos"].items()),
        estilo=ESTILOS[estilo]["nota_modelo"],
        n=len(clips), clips="\n\n".join(_bloque(c, cfg) for c in clips),
        nota=cfg["nota"], dmin=DUR_MIN, dmax=DUR_MAX)

    if cb:
        cb(f"Eligiendo los memes de {len(clips)} clips...", None)

    cliente = anthropic.Anthropic(api_key=key, max_retries=3)
    Esq = _esquema(sorted(lib), sorted(snd), POSICIONES)
    datos, uso = _llamar(cliente, modelo or MODELO_MEMES, prompt, Esq, EFFORT_MEMES)

    planes = {}
    for c in datos:
        orig = next((x for x in clips if x["n"] == c.get("clip")), None)
        if orig is None:
            continue
        planes[orig["n"]] = resolver(c.get("memes") or [], orig, cfg, lib, snd)
    uso["costo_usd"] = round(uso["entrada"] / 1e6 * 5 + uso["salida"] / 1e6 * 25, 4)
    return dict(planes=planes, uso=uso)


def _llamar(cliente, modelo, prompt, Esq, effort):
    """Igual que en gancho.py: si se queda sin presupuesto razonando, baja el
    effort y reintenta. Devolver vacio dejaria el stream sin memes en silencio."""
    escalones = {"max": ["max", "high", "medium"], "xhigh": ["xhigh", "high", "medium"],
                 "high": ["high", "medium"], "medium": ["medium", "low"]}.get(effort, [effort])
    ultimo = ""
    for niv in escalones:
        with cliente.messages.stream(
            model=modelo, max_tokens=MAX_TOKENS_MEMES,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": niv,
                           "format": {"type": "json_schema", "schema": Esq.model_json_schema()}},
        ) as flujo:
            r = flujo.get_final_message()
        if r.stop_reason == "refusal":
            raise RuntimeError("El modelo rechazo la peticion de los memes.")
        txt = "".join(b.text for b in r.content if b.type == "text").strip()
        if txt:
            uso = dict(entrada=r.usage.input_tokens, salida=r.usage.output_tokens,
                       modelo=modelo, effort=niv)
            return Esq.model_validate_json(txt).model_dump()["clips"], uso
        ultimo = (f"se quedo sin presupuesto razonando con effort={niv} "
                  f"({r.usage.output_tokens} tokens, stop_reason={r.stop_reason})")
    raise RuntimeError(f"El modelo no devolvio ningun meme: {ultimo}")


def _sonido_de(elegido, ficha, snd):
    """El sonido valido para este meme: el elegido si le pega, si no el propio."""
    if elegido in snd and snd[elegido]["tono"] in ficha.get("tonos", TONOS):
        return elegido
    ok = sonidos_de(ficha, snd)
    return ok[0] if ok else ficha.get("sonido")


def resolver(memes, clip, cfg, lib, snd):
    """Valida y ordena lo que eligio el modelo. Descarta lo que no entra.

    Lo que se corrige aca: memes fuera del clip, encima del cartel del cold open,
    demasiado pegados entre si, repetidos, mas de los que permite el nivel, y
    posiciones o sonidos que no existen.
    """
    dur_clip = clip["duracion_final"]
    piso = max(0.5, (clip.get("desde") or 0.0) + 0.2)

    limpio = []
    for m in memes:
        if m.get("meme") not in lib:
            continue
        try:
            t, d = float(m["t"]), float(m.get("dur") or DUR_DEFECTO)
        except (TypeError, ValueError, KeyError):
            continue
        d = max(DUR_MIN, min(DUR_MAX, d))
        if not (piso <= t <= dur_clip - 0.35):
            continue
        d = min(d, dur_clip - t)
        if d < DUR_MIN:
            continue
        limpio.append(dict(
            t=round(t, 2), dur=round(d, 2), meme=m["meme"],
            posicion=m["posicion"] if m.get("posicion") in POSICIONES else POSICIONES[0],
            tamano=m["tamano"] if m.get("tamano") in TAMANOS else "grande",
            # El sonido nunca queda vacio -un meme mudo se pierde- y nunca
            # queda fuera de tono: si el modelo eligio uno que no le pega al
            # meme (musica tetrica con una cara feliz), va el propio del meme.
            sonido=_sonido_de(m.get("sonido"), lib[m["meme"]], snd),
            por_que=m.get("por_que", "")))

    limpio.sort(key=lambda m: m["t"])
    repetir = cfg.get("repetir_tras")
    fuera, ultimo_t, usados, ultima_pos = [], -99.0, {}, None
    for m in limpio:
        if m["t"] - ultimo_t < cfg["separacion"]:
            continue
        # el mismo meme dos veces seguidas cansa; en extremo se permite volver a
        # usarlo si ya pasaron unos segundos, porque el repertorio es de doce y
        # ese nivel pide mas memes que memes distintos hay
        antes = usados.get(m["meme"])
        if antes is not None and (repetir is None or m["t"] - antes < repetir):
            continue
        if m["posicion"] == ultima_pos:
            # dos seguidos en el mismo lugar se leen como que quedo pegado
            otras = [p for p in POSICIONES if p != ultima_pos]
            m["posicion"] = otras[(len(fuera) * 3 + 1) % len(otras)]
        fuera.append(m)
        ultimo_t, ultima_pos = m["t"], m["posicion"]
        usados[m["meme"]] = m["t"]
        if len(fuera) >= cfg["maximo"]:
            break
    return fuera


# -------------------------------------------------------------- filtergraph
def _spring(base, estilo):
    """El tamaño del meme como expresion de ffmpeg, sobre su tiempo local.

    En `sticker` es un rebote: entra un 20% mas grande y se asienta. En `crudo`
    no hay rebote y devuelve un numero pelado, que ademas ahorra el `eval=frame`
    del `scale` -o sea que el estilo que se ve peor sale mas barato-.
    """
    a = ESTILOS[estilo]["pop"]
    if not a:
        return f"{base:.0f}"
    return f"{base:.0f}*(1+{a}*exp(-{POP_CAIDA}*t)*cos({POP_FRECUENCIA}*t))"


def preparar_archivos(plan, trabajo, estilo=ESTILO_DEFECTO, semilla=0, mudo=False):
    """Copia a la carpeta de trabajo los memes y sonidos que usa este clip.

    Todo con nombre ASCII y sin espacios, y despues se referencia por ruta
    RELATIVA: ffmpeg corre con el cwd en la carpeta de trabajo y en Windows una
    ruta absoluta le rompe el parseo del filtro, porque el ':' de la unidad se
    confunde con el separador de parametros. Es el mismo motivo por el que se
    copian las fuentes y el golpe del cold open.

    Devuelve el plan filtrado: si un meme ya no esta en el disco, se cae solo.

    Con `mudo` se copian los PNG pero NO los mp3, asi que el meme se ve y no
    suena. El plan no se toca -el sonido elegido queda anotado igual-, y por eso
    prender y apagar el mudo no obliga a volver a llamar al modelo: se vuelve a
    renderizar y listo.
    """
    import shutil

    lib, snd = biblioteca(), sonidos()
    rnd = random.Random(semilla * 104729 + 7)
    dir_m = Path(trabajo) / "memes"
    dir_m.mkdir(parents=True, exist_ok=True)

    vivos = []
    for m in plan:
        ficha = lib.get(m["meme"])
        if ficha is None:
            continue
        ang = rnd.choice((-8, -5, -3, 3, 5, 8)) if ESTILOS[estilo]["inclinar"] else 0
        png = dir_m / "{}_{}_{}{}.png".format(
            m["meme"], estilo, "m" if ang < 0 else "p", abs(ang))
        w, h = preparar(ficha["imagen"], png, estilo, angulo=ang)
        m["_png"] = f"memes/{png.name}"
        m["_ratio"] = (h / w) if w else 1.0
        # el sonido nunca puede faltar: si el plan viene sin uno, va el propio
        # del meme. Un meme mudo se pierde -el usuario lo vio pasar con un gato-.
        sid = m.get("sonido") if m.get("sonido") in snd else ficha.get("sonido")
        if sid in snd and not mudo:
            m["sonido"] = sid
            sonido = snd[sid]
            mp3 = dir_m / f"snd_{sid}.mp3"
            if not mp3.exists() or mp3.stat().st_size != sonido["ruta"].stat().st_size:
                shutil.copy2(sonido["ruta"], mp3)
            m["_mp3"] = f"memes/{mp3.name}"
            m["_corte"] = (sonido["desde"], sonido["hasta"])
        vivos.append(m)
    return vivos


def caja(m, i, franjas, estilo):
    """Donde y de que tamaño va este meme, ya acotado a su franja.

    Devuelve (cx, cy, ancho, alto). El tamaño se recorta si no entra, y el
    centro se corre hasta que el meme entero cae dentro de los limites: es lo
    que garantiza que ni el sticker mas grande ni el crudo a pantalla completa
    le tapen la cara.
    """
    e = ESTILOS[estilo]
    jx, jy = e["jitter"]
    banda, col = m["posicion"].split("-")
    ancla, y0, y1 = franjas[banda]

    w = e["tamanos"][m["tamano"]]
    tope = _alto_tope(franjas[banda], estilo)
    if w * m["_ratio"] > tope:
        w = tope / m["_ratio"]
    h = w * m["_ratio"]
    pico = h * (1 + e["pop"])

    # un empujoncito por meme, para que las seis posiciones no se lean como una
    # grilla; despues el centro se acomoda para que el meme entre entero
    cx = COLUMNAS[col] + ((i * 37) % (2 * jx + 1)) - jx
    cy = ancla + ((i * 53) % (2 * jy + 1)) - jy
    cy = min(max(cy, y0 + pico / 2), y1 - pico / 2)
    pico_w = w * (1 + e["pop"])
    lim = ANCHO + e["sangrado"]
    cx = min(max(cx, pico_w / 2 - e["sangrado"]), lim - pico_w / 2)
    return round(cx), round(cy), w, h


def filtro_video(plan, entrada, salida, con_camara, duracion, fps,
                 estilo=ESTILO_DEFECTO):
    """Los overlays de los memes. Cadena vacia si no hay ninguno.

    Cada meme es una fuente `movie` ACOTADA a su ventana y rellenada antes con
    `tpad` transparente. No es un detalle de estilo:

    - Con la fuente sin acotar (`loop=-1`) el grafo NO TERMINA NUNCA. Medido: un
      clip de prueba de 3 s salia de 166 MB y seguia creciendo.
    - El `scale` corre en cada frame que le entra. Acotado a la ventana, quince
      memes en un clip de 25 s le suman un 25% al render (6,8 s -> 8,5 s); sin
      acotar correria en los 1.500 frames en que el meme ni se ve.
    """
    if not plan:
        return ""
    e = ESTILOS[estilo]
    franjas = _franjas(con_camara, estilo)
    partes, prev = [], entrada
    for i, m in enumerate(plan):
        cx, cy, w, h = caja(m, i, franjas, estilo)
        t0 = m["t"]
        t1 = min(duracion, t0 + m["dur"])
        largo = t1 - t0 + 0.2
        m["_caja"] = dict(w=round(w), h=round(h), x=cx, y=cy)

        cad = (f"movie={m['_png']},loop=loop={max(2, int(largo * fps))}:size=1:start=0,"
               f"setpts=N/{fps}/TB,trim=duration={largo:.3f},format=rgba,"
               f"scale=w='{_spring(w, estilo)}':h='{_spring(h, estilo)}'")
        if e["pop"]:
            cad += ":eval=frame"
        if t0 > 0.02:
            cad += f",tpad=start_duration={t0:.3f}:start_mode=add:color=0x00000000"
        partes.append(f"{cad}[mk{i}];")
        y = (f"{cy}-h/2+{e['bamboleo']}*sin({2 * math.pi * BAMBOLEO_HZ:.3f}*t)"
             if e["bamboleo"] else f"{cy}-h/2")
        sal = f"mv{i}"
        partes.append(f"[{prev}][mk{i}]overlay=x='{cx}-w/2':y='{y}':"
                      f"enable='between(t,{t0:.3f},{t1:.3f})'[{sal}];")
        prev = sal
    partes.append(f"[{prev}]null[{salida}];")
    return "".join(partes)


def filtro_audio(plan, entrada, salida, volumen=None):
    """Mezcla los sonidos de los memes. Cadena vacia si ninguno tiene sonido.

    Va ANTES de la cadena de audio del clip, igual que el golpe del cold open,
    para que el loudnorm los mida junto con el resto y el clip entero siga
    saliendo a -14 LUFS. El precio es que el compresor tambien los ve: por eso el
    volumen es moderado y esta en config.
    """
    con = [m for m in plan or [] if m.get("_mp3")]
    if not con:
        return ""
    vol = MEMES_VOLUMEN if volumen is None else volumen
    partes, etiquetas = [], []
    for i, m in enumerate(con):
        a, b = m["_corte"]
        largo = max(0.3, min(b - a, m["dur"] + 0.45))   # no sonar despues de irse
        fout = max(0.08, min(0.3, largo * 0.25))
        ms = int(m["t"] * 1000)
        partes.append(
            f"amovie={m['_mp3']},atrim=start={a:.3f}:end={a + largo:.3f},"
            f"asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.03,"
            f"afade=t=out:st={largo - fout:.3f}:d={fout:.3f},volume={vol},"
            f"adelay={ms}|{ms}:all=1,"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[mz{i}];")
        etiquetas.append(f"[mz{i}]")
    partes.append(f"[{entrada}]{''.join(etiquetas)}"
                  f"amix=inputs={len(con) + 1}:duration=first:normalize=0[{salida}];")
    return "".join(partes)
