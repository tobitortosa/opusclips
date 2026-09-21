# -*- coding: utf-8 -*-
"""Zoom continuo: el encuadre nunca se queda quieto.

QUE ES
------
Un vaiven de zoom que corre durante TODO el clip, independiente de los cortes.
El ojo se va de un plano fijo; un encuadre que respira lo retiene. Es distinto
del punch-in de `silencios.py`, que da un escalon FIJO por trozo y solo cambia
cuando hay un corte: esto se mueve siempre, tambien en medio de una frase.

DONDE SE APLICA, Y POR QUE AHI
-------------------------------
Despues de pegar los trozos y ANTES de quemar los subtitulos:

    [trozos] -> concat -> [vcat] -> ZOOM -> [vzm] -> ass -> [vo]

Las dos cosas importan:

- Despues del concat, porque cada trozo se corta con `setpts=PTS-STARTPTS` y su
  tiempo vuelve a cero. Si el zoom se aplicara por trozo, en modo "sin respiro"
  -que puede hacer 150 trozos en 35 segundos- el vaiven se reiniciaria 150
  veces y quedaria un temblor, no un movimiento.
- Antes del `ass`, porque si no el texto se agranda y se achica con la imagen.
  Los subtitulos tienen que quedar clavados; lo unico que se mueve es el video.

LA FORMA DEL MOVIMIENTO
-----------------------
No es una onda sola: son DOS sumadas, con periodos en proporcion aurea (0,618),
que no es un numero racional. Dos ondas con periodos racionales vuelven a
coincidir cada pocos segundos y el movimiento se vuelve predecible -se siente
mecanico, "de plantilla"-. Con esta proporcion el ciclo no se repite nunca en la
duracion de un clip, y el zoom se lee como decidido a mano.

Arranca siempre en el minimo (`1-cos`, no `sin`): el clip abre en el plano mas
abierto y entra. Al reves -abrir ya acercado y salir- el primer segundo se lee
como que algo se aleja, que es exactamente lo contrario de retener.

POR QUE ZOOMPAN Y NO OTRA COSA
-------------------------------
`scale` no acepta expresiones que cambien por frame salvo con `eval=frame`, y
combinado con un `crop` centrado cuantiza dos veces (el tamaño del escalado y el
origen del recorte): medido, saltos de hasta 1,88 px. `zoompan` cuantiza una vez
sola y cuesta 0,5 s por cada 10 s de video, contra 24 s que tarda el encode. Lo
que no se puede evitar con NINGUN filtro es que el resultado caiga en una grilla
de pixeles enteros: por eso un zoom MUY LENTO se ve escalonado -se queda quieto
y pega un tiron de 1 px- y uno marcado no, porque el escalon queda tapado por el
movimiento. Medido: a 4% en 7 segundos el escalon es el 100% del movimiento del
frame; a 12% en 4 segundos pasa a ser una fraccion.
"""

# amplitud: cuanto acerca en el pico (0.12 = 12%)
# ciclo:    segundos que tarda en ir y volver
NIVELES = {
    "apagado": None,
    "sutil": dict(amplitud=0.045, ciclo=7.0),
    "normal": dict(amplitud=0.075, ciclo=5.5),
    "llamativo": dict(amplitud=0.12, ciclo=4.0),
    "bestia": dict(amplitud=0.18, ciclo=3.0),
}
NIVEL_DEFECTO = "llamativo"

# Proporcion entre las dos ondas. 0,618 es irracional: nunca vuelven a coincidir.
RELACION = 0.618
PESO_PRINCIPAL = 0.65


def expresion(amplitud, ciclo):
    """La expresion de zoom para ffmpeg, en funcion de `time` (segundos de salida).

    Vale entre 1 y 1+amplitud: las dos ondas van de 0 a 1 y los pesos suman 1.
    """
    t2 = ciclo * RELACION
    a = f"(1-cos(2*PI*time/{ciclo:.4f}))/2"
    b = f"(1-cos(2*PI*time/{t2:.4f}))/2"
    return (f"1+{amplitud:.4f}*({PESO_PRINCIPAL}*{a}+{1 - PESO_PRINCIPAL:.2f}*{b})")


def filtro(nivel, ancho, alto, fps, entrada, salida):
    """El tramo de filtergraph que hace el vaiven. Cadena vacia si esta apagado."""
    cfg = NIVELES.get(nivel)
    if not cfg or cfg["amplitud"] <= 0:
        return ""
    z = expresion(cfg["amplitud"], cfg["ciclo"])
    # x/y centrados: zoompan los recalcula por frame a medida que cambia el zoom
    return (f"[{entrada}]zoompan=z='{z}':d=1:"
            f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
            f"s={ancho}x{alto}:fps={fps}[{salida}];")


def recorrido(nivel, fps=60, segundos=12.0):
    """Los valores de zoom que va a tomar. Solo para tests y para inspeccionar."""
    import math
    cfg = NIVELES.get(nivel)
    if not cfg:
        return []
    a, c = cfg["amplitud"], cfg["ciclo"]
    out = []
    for i in range(int(segundos * fps)):
        t = i / fps
        v = (PESO_PRINCIPAL * (1 - math.cos(2 * math.pi * t / c)) / 2
             + (1 - PESO_PRINCIPAL) * (1 - math.cos(2 * math.pi * t / (c * RELACION))) / 2)
        out.append(1 + a * v)
    return out
