# -*- coding: utf-8 -*-
"""Reparacion de timestamps rotos por palabra, para que el karaoke no falle.

CONTEXTO DE LA DECISION (medido, no supuesto)
---------------------------------------------
Whisper deduce los tiempos por palabra con DTW sobre los pesos de atencion, y
a veces le sale cualquier cosa. En este stream: 369 palabras con duracion CERO
y una palabra de 3 letras que "duraba" 14 segundos. Eso en el karaoke se ve
como una palabra que nunca se pinta, o una que se queda pintada media frase.

Se probo la solucion canonica -alineacion forzada CTC con wav2vec2, que es lo
que hace WhisperX- y se midio contra el VAD, que es un sistema independiente:

    palabras que caen dentro de un tramo de voz : 98,2% -> 98,4%  (+0,2)
    tiempo de palabra que cae sobre voz real    : 94,0% -> 91,6%  (-2,4)
    tiempo de palabra que cae sobre silencio    :  274s ->  328s  (+54)
    palabras con timestamp invalido             :   959 ->  1402  (peor)

O sea: EMPEORO. El modelo CTC espera voz limpia y aca el audio es un mix con
Minecraft de fondo. Se descarto (eran 1,2 GB de modelo y 33 s por stream).

Lo que queda es esto: arreglar SOLO lo que esta roto, con reglas locales.
Es instantaneo, no agrega dependencias, y no toca los tiempos que ya estaban
bien -que son la gran mayoria-.
"""

DUR_MINIMA = 0.06
# Duracion tipica de una palabra en castellano hablado, estimada por longitud.
# Calibrado con este stream: 17.566 palabras en 4.542 s de habla = 258 ms de media.
BASE, POR_LETRA = 0.075, 0.042
DUR_TOPE = 1.30
HOLGURA = 0.02          # separacion minima entre dos palabras


def duracion_estimada(texto):
    n = len(texto.strip().strip(".,;:!?¡¿…\"'"))
    return max(0.10, min(DUR_TOPE, BASE + POR_LETRA * n))


def esta_roto(w, sig=None):
    """Un timestamp es invalido si dura nada, dura demasiado para lo corta que
    es la palabra, o pisa a la siguiente."""
    d = w["b"] - w["a"]
    if d < DUR_MINIMA:
        return "corta"
    if d > duracion_estimada(w["t"]) * 3.5 and d > 1.2:
        return "larga"
    if sig is not None and sig["a"] < w["b"] - 0.001:
        return "solape"
    return None


def reparar(palabras):
    """Corrige en el lugar. Devuelve un resumen de lo que toco."""
    if not palabras:
        return dict(total=0)

    n = len(palabras)
    antes = sum(1 for i, w in enumerate(palabras)
                if esta_roto(w, palabras[i + 1] if i + 1 < n else None))
    cero_antes = sum(1 for w in palabras if w["b"] - w["a"] <= 0.001)
    arregladas = dict(corta=0, larga=0, solape=0)

    # 1) duraciones invalidas: se reconstruyen a partir de la longitud de la
    #    palabra, sin invadir el espacio de la siguiente
    for i, w in enumerate(palabras):
        sig = palabras[i + 1] if i + 1 < n else None
        d = w["b"] - w["a"]
        if d < DUR_MINIMA:
            tope = (sig["a"] - w["a"] - HOLGURA) if sig else duracion_estimada(w["t"])
            w["b"] = round(w["a"] + max(DUR_MINIMA, min(duracion_estimada(w["t"]),
                                                        max(DUR_MINIMA, tope))), 3)
            arregladas["corta"] += 1
        elif d > duracion_estimada(w["t"]) * 3.5 and d > 1.2:
            # una palabra corta no dura 14 segundos: lo que sobra es silencio.
            # Se conserva el ARRANQUE, que es lo que importa para el karaoke.
            w["b"] = round(w["a"] + duracion_estimada(w["t"]), 3)
            arregladas["larga"] += 1

    # 2) solapes: ninguna palabra puede empezar antes de que termine la anterior
    for i in range(1, n):
        ant, act = palabras[i - 1], palabras[i]
        if act["a"] < ant["b"] - 0.001:
            arregladas["solape"] += 1
            medio = (act["a"] + ant["b"]) / 2
            if medio - ant["a"] >= DUR_MINIMA:
                ant["b"] = round(medio - HOLGURA / 2, 3)
                act["a"] = round(medio + HOLGURA / 2, 3)
            else:
                act["a"] = round(ant["b"] + HOLGURA, 3)
            if act["b"] < act["a"] + DUR_MINIMA:
                act["b"] = round(act["a"] + DUR_MINIMA, 3)

    despues = sum(1 for i, w in enumerate(palabras)
                  if esta_roto(w, palabras[i + 1] if i + 1 < n else None))
    return dict(total=n, rotas_antes=antes, rotas_despues=despues,
                duracion_cero_antes=cero_antes,
                duracion_cero_despues=sum(1 for w in palabras if w["b"] - w["a"] <= 0.001),
                **arregladas)
