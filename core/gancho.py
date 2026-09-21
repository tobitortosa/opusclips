# -*- coding: utf-8 -*-
"""Cold open: el pedacito mas llamativo del clip, pegado al principio.

QUE ES Y POR QUE FUNCIONA
--------------------------
El clip no arranca por donde empieza la historia, sino por el momento MAS
fuerte que va a pasar: un grito, una risa, una puteada con timing, una frase
que hace parar el dedo. Dura dos o tres segundos, corta seco, y recien ahi
empieza el clip de verdad. Es el avance de una pelicula comprimido.

POR QUE NO SE DETECTA, SE ELIGE
--------------------------------
Se probaron TRES enfoques de deteccion automatica sobre este audio, y los tres
se descartaron con mediciones. El audio del stream es un MIX (voz + Minecraft +
las voces de los otros por Discord), y eso rompe cualquier clasificador:

1. HEURISTICA DE VOLUMEN + diccionario de puteadas. El volumen no distingue un
   grito de una explosion del juego, y las risas no las agarra.

2. CLASIFICADOR ENTRENADO EN AUDIOSET (AST, 527 clases, reconoce Laughter /
   Screaming / Shout). Barrido sobre el stream entero de 158 min: maximo 0,040
   de probabilidad para "grito" y 0,044 para "festejo" en TODO el stream.

3. TONO + PERIODICIDAD (un grito tiene F0 muy por encima de la mediana del
   hablante). Sobre 121 min dio 14 eventos, casi todos charla normal, y dos de
   ellos de 22 segundos. Inservible.

Tampoco sirve mirar la CARA: se extrajeron frames de la webcam en los 8
momentos de mayor energia del stream y en los 8 la cara esta neutra, mirando al
monitor, en un cuarto oscuro. Mandarle esos frames a un modelo con vision seria
caro y no aportaria nada.

LO QUE QUEDO
------------
Decide CLAUDE, leyendo. Pero con dos cambios respecto del primer diseño:

a) ELIGE DE UN MENU, NO INVENTA TIEMPOS. Aca abajo se arma la lista de todos
   los fragmentos que PODRIAN ser cold open -recortados en frontera de frase,
   con la duracion ya correcta- y el modelo devuelve el numero de uno. Antes
   devolvia `inicio` y `fin` en segundos, que solo podia deducir de los
   timestamps de las palabras: por construccion le era IMPOSIBLE elegir un
   momento sin palabras. Y medido sobre el stream: de los 30 picos de voz mas
   fuertes, 10 no tienen NINGUNA palabra transcrita (Whisper escribe "jaj*" una
   sola vez en dos horas). O sea que un tercio del mejor material le era
   invisible. Ahora esos tramos -voz segun el VAD, nada segun el ASR- entran al
   menu como candidatos marcados.

b) ESCRIBE EL CARTEL. El canal visual del cold open esta vacio (cara neutra +
   Minecraft), asi que el gancho visual hay que FABRICARLO: el modelo devuelve
   3 a 6 palabras que van en un cartel grande arriba, que es lo que se usa hoy
   en TikTok. No se detecta nada: se construye.
"""
import numpy as np

from .config import (EFFORT_GANCHO, MAX_TOKENS_GANCHO, MODELO_GANCHO, VAR_KEY,
                     api_key)

SR = 16000
DUR_MIN, DUR_MAX = 1.8, 3.6      # un gancho de 1 s no se entiende: hace falta la frase
DUR_OBJETIVO = 2.6
NO_ARRANCAR_ANTES = 2.0          # si el momento fuerte esta al principio, no hay gancho
ZOOM_GANCHO = 1.12               # el adelanto va mas cerrado, para que se lea como adelanto
FUERZA_MINIMA = 55               # debajo de esto, mejor sin cold open que con uno flojo

# Una pausa de este tamaño ya es frontera limpia para arrancar o cortar. Si con
# el umbral mas exigente no aparece material -pasa cuando habla de corrido, que
# es justo el material mas frenetico- se va aflojando: es preferible un corte en
# una frontera de palabra cualquiera que dejar el clip sin cold open.
PAUSAS_CORTE = (0.25, 0.14, 0.0)
MAX_CANDIDATOS = 16              # por clip; mas que esto solo confunde al modelo
MIN_CANDIDATOS = 5               # si no llega a esto, se afloja el umbral de pausa
# Un tramo de voz sin palabras solo entra al menu si dura lo suficiente Y suena
# MAS FUERTE que como habla normalmente en ese clip. Sin el segundo requisito el
# menu se llena de respiraciones y de relleno del VAD -medido sobre los clips
# reales: candidatos de "reaccion" a -1,5 dB, que desplazaban a las frases-.
REACCION_MINIMA = 0.6            # una risa o un grito no dura menos que esto
REACCION_DB = 1.0                # cuanto tiene que sobresalir sobre su voz normal
REACCION_CONTEXTO = 1            # palabras de contexto que se le pegan si entran

FIN_FRASE = ".!?…"

# Un fragmento que termina en una de estas palabras queda colgado -"...y", "...de
# que"- y como cold open suena a error de edicion, por mas que haya una pausa
# despues. Se ve a simple vista en el menu: "Si, de gana. Y".
CIERRE_COLGADO = {
    "y", "o", "u", "e", "de", "del", "a", "al", "en", "con", "sin", "por", "para",
    "que", "qué", "pero", "porque", "si", "como", "cuando", "donde", "el", "la",
    "los", "las", "un", "una", "unos", "unas", "mi", "tu", "su", "lo", "le", "se",
    "me", "te", "es", "muy", "mas", "más", "ya", "no", "ni", "tipo", "o sea",
}


# ------------------------------------------------------------------ candidatos
def _nivel_voz(pcm, palabras, inicio, fin):
    """dB de referencia: el nivel al que habla en ESTE clip, no en el stream."""
    if pcm is None:
        return None
    vals = []
    for w in palabras:
        a, b = int(w["a"] * SR), int(w["b"] * SR)
        if b - a < 320:
            continue
        x = pcm[max(0, a):min(len(pcm), b)]
        if len(x):
            vals.append(float(np.sqrt(np.mean(x ** 2)) + 1e-9))
    if not vals:
        return None
    return 20 * np.log10(float(np.median(vals)))


def _db(pcm, a, b):
    if pcm is None:
        return None
    x = pcm[max(0, int(a * SR)):min(len(pcm), int(b * SR))]
    if len(x) < 160:
        return None
    return 20 * np.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-9)


def _frontera_inicio(pal, i, pausa):
    """True si la palabra i es un arranque limpio (hay pausa o punto antes)."""
    if i == 0:
        return True
    return (pal[i]["a"] - pal[i - 1]["b"] >= pausa
            or pal[i - 1]["t"].rstrip().endswith(tuple(FIN_FRASE)))


def _frontera_fin(pal, j, pausa):
    """True si la palabra j es un cierre limpio (hay pausa o punto despues)."""
    if j == len(pal) - 1:
        return True
    return (pal[j + 1]["a"] - pal[j]["b"] >= pausa
            or pal[j]["t"].rstrip().endswith(tuple(FIN_FRASE)))


def _huecos_sin_palabras(tramos_voz, pal, inicio, fin):
    """Tramos donde el VAD oye voz y el ASR no escribio nada.

    Ahi viven las risas, los gritos y las reacciones: Whisper no las transcribe.
    Medido sobre el stream: un tercio de los picos de voz mas fuertes cae aca.
    """
    ocupado = sorted((w["a"], w["b"]) for w in pal)
    libres = []
    for t in tramos_voz:
        a, b = max(inicio, t["a"]), min(fin, t["b"])
        if b - a < REACCION_MINIMA:
            continue
        cursor = a
        for wa, wb in ocupado:
            if wb <= cursor or wa >= b:
                continue
            if wa - cursor >= REACCION_MINIMA:
                libres.append((cursor, wa))
            cursor = max(cursor, wb)
        if b - cursor >= REACCION_MINIMA:
            libres.append((cursor, b))
    return libres


def candidatos(clip, palabras, tramos_voz, pcm):
    """Todos los fragmentos que podrian ser cold open de este clip.

    Ya vienen con la duracion correcta y cortados en frontera de frase, asi que
    lo que elija el modelo no necesita correccion: solo hay que buscarlo por id.

    Se intenta primero con el umbral de pausa mas exigente y se va aflojando
    hasta juntar material: si habla de corrido -que es justo lo mejor- con el
    umbral duro no hay ni una frontera y el clip se quedaria sin cold open.
    """
    for pausa in PAUSAS_CORTE:
        cands = _candidatos(clip, palabras, tramos_voz, pcm, pausa)
        if len(cands) >= MIN_CANDIDATOS:
            return cands
    return cands


def _candidatos(clip, palabras, tramos_voz, pcm, pausa):
    a0, b0 = clip["inicio"], clip["fin"]
    pal = [w for w in palabras if w["b"] > a0 and w["a"] < b0]
    if len(pal) < 4:
        return []
    ref = _nivel_voz(pcm, pal, a0, b0)
    fuera, vistos = [], set()

    def agregar(a, b, tipo, texto):
        a, b = round(float(a), 2), round(float(b), 2)
        if not (a0 <= a < b <= b0):
            return
        if a - a0 < NO_ARRANCAR_ANTES:       # seria mostrar dos veces lo mismo
            return
        if not (DUR_MIN <= b - a <= DUR_MAX):
            return
        clave = (round(a, 1), round(b, 1))
        if clave in vistos:
            return
        vistos.add(clave)
        d = _db(pcm, a, b)
        previas = [w["t"] for w in pal if w["b"] <= a][-8:]
        fuera.append(dict(a=a, b=b, dur=round(b - a, 2), tipo=tipo, texto=texto,
                          antes=" ".join(previas),
                          exceso=None if (d is None or ref is None) else round(d - ref, 1)))

    # --- candidatos de frase: arrancan y terminan donde hay pausa o punto
    for i in range(len(pal)):
        if not _frontera_inicio(pal, i, pausa):
            continue
        for j in range(i, len(pal)):
            dur = pal[j]["b"] - pal[i]["a"]
            if dur > DUR_MAX:
                break
            if dur < DUR_MIN or not _frontera_fin(pal, j, pausa):
                continue
            ultima = pal[j]["t"].strip().strip(".,;:!?¡¿…").lower()
            if ultima in CIERRE_COLGADO:
                continue
            agregar(pal[i]["a"] - 0.06, pal[j]["b"] + 0.10, "frase",
                    " ".join(w["t"] for w in pal[i:j + 1]))

    # --- candidatos de reaccion: voz que el ASR no transcribio (risa, grito)
    for ha, hb in _huecos_sin_palabras(tramos_voz, pal, a0, b0):
        d = _db(pcm, ha, hb)
        if ref is None or d is None or d - ref < REACCION_DB:
            continue                          # apenas respiracion: no es reaccion
        # Una risa suelta no dice nada; "no queda nada" + risa si. Se ofrecen dos
        # formas: la reaccion PELADA -cuando ya dura lo suficiente sola, porque
        # dos segundos y medio de carcajada son el gancho- y la reaccion con la
        # frase de al lado pegada, cuando entra en los 3,6 s. En los dos casos el
        # menu le muestra ademas lo que se dice justo antes, que es lo que le
        # permite al modelo saber DE QUE se esta riendo sin gastar duracion.
        if hb - ha >= DUR_MIN:
            agregar(ha, min(hb, ha + DUR_MAX), "reaccion", "[reaccion sin palabras]")

        antes = [w for w in pal if w["b"] <= ha]
        despues = [w for w in pal if w["a"] >= hb]
        for lado, fuente in (("antes", list(reversed(antes))), ("despues", despues)):
            a, b, ctx = ha, hb, []
            for w in fuente:
                if lado == "antes":
                    na = w["a"] - 0.06
                    if b - na > DUR_MAX:
                        break
                    a, ctx = na, [w["t"]] + ctx
                else:
                    nb = w["b"] + 0.10
                    if nb - a > DUR_MAX:
                        break
                    b, ctx = nb, ctx + [w["t"]]
                if b - a < DUR_MIN or len(ctx) < REACCION_CONTEXTO:
                    continue
                frase = " ".join(ctx).strip()
                agregar(a, b, "reaccion",
                        f"{frase} [reaccion sin palabras]" if lado == "antes"
                        else f"[reaccion sin palabras] {frase}")

    # El tope se reparte por FUERZA, no por tipo. Ordenar las reacciones primero
    # dejaba clips con 5 reacciones dudosas y solo 2 frases para elegir. La
    # reaccion lleva una ventaja de 2 dB -vale mas que una frase del mismo
    # volumen-, pero compite.
    fuera.sort(key=lambda c: -((c["exceso"] or 0) + (2.0 if c["tipo"] == "reaccion" else 0)))
    elegidos, ocupados = [], []
    for c in fuera:
        if any(abs(c["a"] - o) < 0.9 for o in ocupados):
            continue
        ocupados.append(c["a"])
        elegidos.append(c)
        if len(elegidos) >= MAX_CANDIDATOS:
            break
    elegidos.sort(key=lambda c: c["a"])
    for k, c in enumerate(elegidos, 1):
        c["id"] = k
    return elegidos


# ------------------------------------------------------------------- el prompt
CRITERIO = """El COLD OPEN es el pedacito que se pega al principio del clip, antes de que el clip empiece de verdad. Su unico trabajo es frenar el dedo de alguien que esta scrolleando TikTok.

QUE FUNCIONA, de mejor a peor:
1. Una REACCION fuerte y sonora: un grito, una carcajada, una puteada con timing, alguien indignado, alguien que no puede creer lo que pasa. Los candidatos marcados como REACCION son justamente eso: el detector de voz oye a alguien pero el transcriptor no escribio ninguna palabra, que es lo que pasa con las risas y los gritos. Si el texto de alrededor hace pensar que ahi hay una risa o un grito, es de lo mejor que podes elegir.
2. Una frase que SE MALPIENSA o que suena escandalosa fuera de contexto, y que da intriga por saber de que hablaban.
3. Una frase corta y tajante que genera pregunta: "no queda nada", "la explote toda", "me esta re tilteando", "que hiciste".
4. Un remate comico que se entiende solo.

QUE NO FUNCIONA:
- Una explicacion, por mas interesante que sea.
- Una frase a mitad de camino que no se entiende sin lo anterior.
- Algo que suena neutro o tranquilo, aunque el contenido sea bueno.
- Coordinacion o logistica del juego ("dale, voy", "esperame aca").

EL CARTEL:
Junto al fragmento vas a escribir un CARTEL: 3 a 6 palabras que aparecen en letras grandes arriba de la pantalla durante esos dos segundos y medio. Es importante: la imagen de este stream no vende sola -es una webcam oscura y Minecraft-, asi que el cartel es la mitad del gancho.
- Que genere una PREGUNTA o prometa algo, no que describa lo que se ve.
- NO repitas la frase que ya se escucha: seria decir dos veces lo mismo.
- Espanol argentino, sin hashtags, sin emojis, sin comillas.
- Bien: "SE SUBASTO MI CABEZA" · "NO SABE QUE LO VEO" · "PELEO AL WARDEN SOLO"
- Mal: "Tobi juega Minecraft" · "Un momento gracioso" · "Mira esto"

LA FUERZA:
`fuerza` de 1 a 100: cuanto frena el scroll ESTE fragmento concreto. Usa todo el rango y se duro. Un fragmento que solo esta "bien" es 40. Arriba de 70 va lo que de verdad hace girar la cabeza. Si el mejor candidato del clip no llega a {fuerza}, poné `sirve: false`: un cold open flojo es peor que ninguno, porque le roba los primeros segundos al clip."""

PROMPT = """{criterio}

Abajo van {n} clips ya elegidos de un stream de Minecraft en espanol argentino (el streamer es Tobi, juega en un servidor con amigos y el contenido es sobre todo la charla entre ellos: drama del server, robos, humor).

De cada clip tenes su transcripcion completa y una lista numerada de FRAGMENTOS CANDIDATOS. Los candidatos ya estan recortados con la duracion justa y en frontera de frase: tu trabajo es elegir cual, no ajustar los bordes.

Cada candidato trae:
  - su numero, que es lo que tenes que devolver
  - FRASE o REACCION (REACCION = hay voz pero el transcriptor no escribio nada: risa, grito, queja)
  - cuantos dB esta por encima del nivel al que habla normalmente en ese clip
  - el texto que se escucha

{clips}

Para cada clip elegi UN candidato y escribi su cartel. Devolve el `candidato` por numero."""


def _esquema():
    from pydantic import BaseModel, ConfigDict, Field

    class G(BaseModel):
        model_config = ConfigDict(extra="forbid")
        clip: int = Field(description="El numero de clip al que corresponde")
        sirve: bool = Field(description="False si ningun candidato del clip llega a frenar el scroll")
        candidato: int = Field(description="El numero del fragmento elegido")
        cartel: str = Field(description="3 a 6 palabras para el cartel grande. Sin comillas ni emojis.")
        fuerza: int = Field(description="1 a 100: cuanto frena el scroll este fragmento")
        por_que: str = Field(description="Por que frena el scroll. Maximo 14 palabras.")

    class R(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ganchos: list[G]

    return R


def _bloque(c, cands, palabras):
    pal = [w for w in palabras if w["b"] > c["inicio"] and w["a"] < c["fin"]]
    texto = " ".join(w["t"] for w in pal)
    lineas = []
    for k in cands:
        ex = "" if k["exceso"] is None else f" | {k['exceso']:+.0f} dB"
        marca = "REACCION" if k["tipo"] == "reaccion" else "FRASE   "
        lineas.append(f"   {k['id']:2d}. [{marca}] {k['dur']:.1f}s{ex}  \"{k['texto']}\"")
        if k["tipo"] == "reaccion" and k["antes"]:
            lineas.append(f"       viene justo despues de: \"...{k['antes']}\"")
    return (f"--- CLIP {c['n']}: \"{c.get('titulo','')}\" ({c['fin']-c['inicio']:.0f}s)\n"
            f"    lo que se dice: {texto}\n"
            f"    candidatos:\n" + "\n".join(lineas))


# -------------------------------------------------------------------- llamada
def elegir(clips, palabras, tramos_voz, pcm, cb=None, modelo=None):
    """Elige el cold open y el cartel de cada clip, en UNA sola llamada.

    Va todo junto a proposito: asi el modelo ve el conjunto y no repite el mismo
    recurso ni el mismo cartel en los diez clips.

    Devuelve dict(ganchos={n_clip: {...}}, uso={...}, menu={n_clip: [...]}).
    Lanza RuntimeError si la llamada no se pudo completar: el que llama NO debe
    cachear un resultado vacio, porque seria dejar ese stream sin gancho para
    siempre.
    """
    import anthropic

    key = api_key()
    if not key:
        raise RuntimeError(f"Falta la API key: pone {VAR_KEY}=sk-ant-... en el .env")
    if not clips:
        return dict(ganchos={}, uso={}, menu={})

    menu, bloques = {}, []
    for c in clips:
        cands = candidatos(c, palabras, tramos_voz, pcm)
        if not cands:
            continue
        menu[c["n"]] = cands
        bloques.append(_bloque(c, cands, palabras))
    if not bloques:
        return dict(ganchos={}, uso={}, menu={})

    if cb:
        cb(f"Eligiendo el gancho de {len(bloques)} clips...", None)

    cliente = anthropic.Anthropic(api_key=key, max_retries=3)
    Esq = _esquema()
    prompt = PROMPT.format(criterio=CRITERIO.format(fuerza=FUERZA_MINIMA),
                           n=len(bloques), clips="\n\n".join(bloques))

    datos, uso = _llamar(cliente, modelo or MODELO_GANCHO, prompt, Esq, EFFORT_GANCHO)

    fuera = {}
    for g in datos:
        c = next((x for x in clips if x["n"] == g.get("clip")), None)
        if c is None:
            continue
        v = resolver(g, c, menu.get(c["n"], []))
        if v:
            fuera[c["n"]] = v
    uso["costo_usd"] = round(uso["entrada"] / 1e6 * 5 + uso["salida"] / 1e6 * 25, 4)
    return dict(ganchos=fuera, uso=uso, menu=menu)


def _llamar(cliente, modelo, prompt, Esq, effort):
    """Una llamada con salida estructurada, con reintento a menos razonamiento.

    El modo de falla conocido es quedarse sin presupuesto RAZONANDO y no emitir
    una sola linea de texto. Si pasa, se reintenta con effort mas bajo en vez de
    devolver vacio: devolver vacio hace que el stream quede sin gancho.
    """
    escalones = {"max": ["max", "high", "medium"], "xhigh": ["xhigh", "high", "medium"],
                 "high": ["high", "medium"], "medium": ["medium", "low"]}.get(effort, [effort])
    ultimo = ""
    for niv in escalones:
        with cliente.messages.stream(
            model=modelo, max_tokens=MAX_TOKENS_GANCHO,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": niv,
                           "format": {"type": "json_schema", "schema": Esq.model_json_schema()}},
        ) as flujo:
            r = flujo.get_final_message()
        if r.stop_reason == "refusal":
            raise RuntimeError("El modelo rechazo la peticion del gancho.")
        txt = "".join(b.text for b in r.content if b.type == "text").strip()
        if txt:
            uso = dict(entrada=r.usage.input_tokens, salida=r.usage.output_tokens,
                       modelo=modelo, effort=niv)
            return Esq.model_validate_json(txt).model_dump()["ganchos"], uso
        ultimo = (f"se quedo sin presupuesto razonando con effort={niv} "
                  f"({r.usage.output_tokens} tokens, stop_reason={r.stop_reason})")
    raise RuntimeError(f"El modelo no devolvio ningun gancho: {ultimo}")


def resolver(g, clip, cands):
    """Busca el candidato elegido en el menu. None si no sirve.

    Como el modelo elige de una lista ya validada, aca no hay bordes que
    corregir: solo se comprueba que el numero exista y que la fuerza alcance.
    """
    if not g.get("sirve", True):
        return None
    try:
        idx = int(g["candidato"])
    except (TypeError, ValueError, KeyError):
        return None
    k = next((c for c in cands if c["id"] == idx), None)
    if k is None:
        return None
    fuerza = int(g.get("fuerza", 0) or 0)
    if fuerza < FUERZA_MINIMA:
        return None
    if not (clip["inicio"] <= k["a"] < k["b"] <= clip["fin"]):
        return None
    cartel = " ".join((g.get("cartel") or "").split()).strip(' "\'')
    return dict(desde=k["a"], hasta=k["b"], dur=k["dur"], texto=k["texto"],
                tipo=k["tipo"], cartel=cartel, fuerza=fuerza,
                por_que=g.get("por_que", ""), version=2)


# ------------------------------------------------------- compatibilidad / tests
def validar(g, clip, palabras):
    """Camino viejo: el modelo devolvia `inicio`/`fin` en segundos.

    Se conserva porque sigue siendo la red de seguridad si alguna vez se vuelve
    a pedir tiempos libres, y porque describe exactamente que es un cold open
    invalido: fuera del clip, demasiado corto, o en los primeros 2 segundos.
    """
    if not g.get("sirve", True):
        return None
    try:
        a, b = float(g["inicio"]), float(g["fin"])
    except (TypeError, ValueError, KeyError):
        return None
    if not (clip["inicio"] <= a < b <= clip["fin"]):
        return None
    if a - clip["inicio"] < NO_ARRANCAR_ANTES:
        return None
    if b - a < DUR_MIN:
        b = min(clip["fin"], a + DUR_OBJETIVO)
    if b - a > DUR_MAX:
        b = a + DUR_MAX
    if b - a < DUR_MIN or b > clip["fin"]:
        return None
    a, b = _ajustar(palabras, a, b)
    if not (DUR_MIN - 0.3 <= b - a <= DUR_MAX + 0.3):
        return None
    return dict(desde=round(a, 2), hasta=round(b, 2),
                texto=g.get("frase", ""), por_que=g.get("por_que", ""),
                dur=round(b - a, 2), version=2)


def _ajustar(palabras, a, b):
    """Corre los bordes a limites de palabra, sin salirse del rango permitido."""
    dentro = [w for w in palabras if w["b"] > a and w["a"] < b]
    if not dentro:
        return a, b
    if 0 < dentro[0]["a"] - a < 0.35:
        a = dentro[0]["a"] - 0.06
    enteras = [w for w in dentro if w["b"] <= b + 0.20]
    if enteras:
        nb = enteras[-1]["b"] + 0.10
        if DUR_MIN <= nb - a <= DUR_MAX:
            b = nb
    return a, b
