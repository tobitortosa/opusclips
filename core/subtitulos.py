# -*- coding: utf-8 -*-
"""Subtitulos karaoke estilo Opus Clip: frase en blanco, palabra activa en verde.

Tecnica: en vez de los tags \\k de ASS (que libass renderiza de forma
inconsistente), se emite UNA linea de Dialogue POR PALABRA ACTIVA. Cada linea
muestra la frase entera y pinta de verde solo la palabra que suena en ese
instante. Es lo que hacen las herramientas serias y da control total.

El ancho del texto se mide con las metricas reales de la fuente, asi que
nunca se desborda del video (el primer intento se salia de pantalla).
"""
import io
from pathlib import Path

from fontTools.ttLib import TTFont

from .config import (ALTO, ANCHO, CARTEL_BORDE, CARTEL_COLOR, CARTEL_ESTILO,
                     CARTEL_MARGEN_V, CARTEL_MAX_LINEAS, CARTEL_OUTLINE, CARTEL_SIZE,
                     COLOR_ACTIVO, COLOR_BASE, ESTILOS_SUB, ESTILO_SUB_DEFECTO,
                     FUENTES, SUB_MARGEN, SUB_MARGEN_V)

FIN_FRASE = ".!?…"
FIN_CLAUSULA = ",;:"
_cache_medidor = {}


class Medidor:
    """Ancho de texto en pixeles, usando las metricas del TTF."""

    def __init__(self, ttf, size):
        f = TTFont(str(ttf), lazy=True)
        self.upem = f["head"].unitsPerEm
        self.hmtx = f["hmtx"].metrics
        self.cmap = f.getBestCmap()
        self.size = size
        self.notdef = self.hmtx.get(".notdef", (self.upem // 2, 0))[0]

    def ancho(self, texto):
        tot = 0
        for ch in texto:
            g = self.cmap.get(ord(ch))
            tot += self.hmtx.get(g, (self.notdef, 0))[0] if g else self.notdef
        return tot * self.size / self.upem


def medidor(estilo):
    e = ESTILOS_SUB[estilo]
    clave = (e["ttf"], e["size"])
    if clave not in _cache_medidor:
        _cache_medidor[clave] = Medidor(FUENTES / e["ttf"], e["size"])
    return _cache_medidor[clave]


def armar_cues(palabras, estilo=ESTILO_SUB_DEFECTO, pausa=0.32, max_pal=5):
    """Agrupa palabras en carteles. Corta por: fin de frase > pausa > ancho >
    fin de clausula > tope de palabras. Asi no parte frases al medio."""
    med = medidor(estilo)
    e = ESTILOS_SUB[estilo]
    ancho_max = ANCHO - 2 * SUB_MARGEN - 2 * e["outline"]

    cues, cur = [], []
    for w in palabras:
        if cur:
            prev = cur[-1]["t"].rstrip()
            cand = " ".join(p["t"] for p in cur + [w]).upper()
            if (prev.endswith(tuple(FIN_FRASE))
                    or w["a"] - cur[-1]["b"] > pausa
                    or med.ancho(cand) > ancho_max
                    or len(cur) >= max_pal
                    or (prev.endswith(tuple(FIN_CLAUSULA)) and len(cur) >= 3)):
                cues.append(cur)
                cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    return [[dict(t=w["t"], a=w["a"], b=w["b"], p=w.get("p", 1.0)) for w in c] for c in cues]


def _cs(t):
    t = max(0.0, t)
    return "%d:%02d:%05.2f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


CABECERA = """[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: K,{familia},{size},&H00FFFFFF,&H00FFFFFF,&H00141414,&H64000000,0,0,0,0,100,100,0,0,1,{outline},{shadow},2,{mg},{mg},{mv},1
Style: CARTEL,{cfam},{csize},{ccol},{ccol},{cbor},&H64000000,0,0,0,0,100,100,1,0,1,{cout},3,8,{cmg},{cmg},{cmv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ancho_max():
    return ANCHO - SUB_MARGEN - 2 * CARTEL_OUTLINE


def partir_cartel(texto, size=CARTEL_SIZE, max_lineas=CARTEL_MAX_LINEAS):
    """Reparte el cartel en hasta dos lineas EQUILIBRADAS.

    El reparto codicioso -meter todo lo que entre en la primera linea- deja
    carteles como "LO DESPERTAMOS SIN / QUERER": 909 px contra 318. Se prueban
    todos los puntos de corte y se elige el que deja la linea mas ancha lo mas
    angosta posible, que es lo que da el bloque compacto de TikTok.
    """
    e = ESTILOS_SUB[CARTEL_ESTILO]
    med = Medidor(FUENTES / e["ttf"], size)
    pal = texto.upper().split()
    if not pal:
        return []
    if med.ancho(" ".join(pal)) <= _ancho_max() or len(pal) == 1:
        return [" ".join(pal)]

    mejor, mejor_peor = None, None
    for k in range(1, len(pal)):
        a, b = " ".join(pal[:k]), " ".join(pal[k:])
        if max_lineas >= 2 and med.ancho(b) > _ancho_max() * 1.6:
            continue                       # la segunda linea seria imposible
        peor = max(med.ancho(a), med.ancho(b))
        if mejor_peor is None or peor < mejor_peor:
            mejor, mejor_peor = [a, b], peor
    if mejor is None:
        corte = -(-len(pal) // max_lineas)
        return [" ".join(pal[i:i + corte]) for i in range(0, len(pal), corte)][:max_lineas]
    return mejor


def _lineas_cartel(texto, hasta):
    """El cartel del cold open: entra con un golpe, se va con el corte.

    El tamaño se ajusta para que el cartel LLENE el ancho. Sin esto un cartel
    corto como "QUE HICISTE" ocupaba la mitad de la pantalla y se leia como un
    subtitulo mas, que es justo lo contrario de lo que tiene que pasar.
    """
    lineas = partir_cartel(texto)
    if not lineas:
        return []
    e = ESTILOS_SUB[CARTEL_ESTILO]
    med = Medidor(FUENTES / e["ttf"], CARTEL_SIZE)
    peor = max(med.ancho(l) for l in lineas)
    tope = 150 if len(lineas) == 1 else 122     # con dos lineas, sin comerse la camara
    escala = max(70, min(tope, int(100 * _ancho_max() / peor))) if peor else 100
    txt = r"\N".join(l.replace("{", "(").replace("}", ")") for l in lineas)
    # el \fad lo hace entrar rapido y el \t de arranque es el "golpe": aparece
    # un 14% mas grande y se asienta en 110 ms. Es lo que lo hace leer como un
    # cartel de TikTok y no como un subtitulo mas.
    efecto = (r"{\fad(90,70)\fscx%d\fscy%d\t(0,110,\fscx%d\fscy%d)}"
              % (int(escala * 1.14), int(escala * 1.14), escala, escala))
    return ["Dialogue: 1,%s,%s,CARTEL,,0,0,0,,%s%s"
            % (_cs(0.0), _cs(hasta), efecto, txt)]


def escribir_ass(cues, destino, estilo=ESTILO_SUB_DEFECTO, t0=0.0, pop=True,
                 mayusculas=True, margen_v=None, cartel=None, cartel_hasta=0.0):
    """Genera el .ass. `t0` es el inicio del clip: los tiempos se hacen relativos.

    `cartel` es el texto grande del cold open, visible hasta `cartel_hasta`
    segundos (relativos al clip ya cortado, o sea desde 0).
    """
    e = ESTILOS_SUB[estilo]
    lineas = []
    for cue in cues:
        if not cue:
            continue
        for k, w in enumerate(cue):
            partes = []
            for j, w2 in enumerate(cue):
                txt = w2["t"].upper() if mayusculas else w2["t"]
                txt = txt.replace("{", "(").replace("}", ")")
                if j == k:
                    if pop:
                        partes.append(r"{\c%s\fscy110}%s{\c%s\fscy100}" % (COLOR_ACTIVO, txt, COLOR_BASE))
                    else:
                        partes.append(r"{\c%s}%s{\c%s}" % (COLOR_ACTIVO, txt, COLOR_BASE))
                else:
                    partes.append(txt)
            ini = w["a"] - t0
            fin = (cue[k + 1]["a"] if k + 1 < len(cue) else w["b"]) - t0
            if fin <= ini:
                fin = ini + 0.05
            fade = r"{\fad(80,0)}" if k == 0 else ""
            lineas.append("Dialogue: 0,%s,%s,K,,0,0,0,,%s%s"
                          % (_cs(ini), _cs(fin), fade, " ".join(partes)))

    if cartel and cartel_hasta > 0:
        lineas = _lineas_cartel(cartel, cartel_hasta) + lineas

    ce = ESTILOS_SUB[CARTEL_ESTILO]
    cab = CABECERA.format(W=ANCHO, H=ALTO, familia=e["familia"], size=e["size"],
                          outline=e["outline"], shadow=e["shadow"], mg=SUB_MARGEN,
                          mv=SUB_MARGEN_V if margen_v is None else margen_v,
                          cfam=ce["familia"], csize=CARTEL_SIZE, ccol=CARTEL_COLOR,
                          cbor=CARTEL_BORDE, cout=CARTEL_OUTLINE, cmg=SUB_MARGEN // 2,
                          cmv=CARTEL_MARGEN_V)
    Path(destino).write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8-sig")
    return destino
