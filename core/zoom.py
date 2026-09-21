# -*- coding: utf-8 -*-
"""Zoom a saltos sobre el gameplay: tac, tac. Sin transicion.

QUE ES
------
El encuadre del GAMEPLAY salta entre dos o tres distancias durante todo el clip.
No se desliza: salta. Se queda un segundo y medio en un plano, pega el salto al
siguiente, se queda, vuelve. La camara no se toca.

POR QUE A SALTOS Y NO DESLIZANDO
---------------------------------
La primera version hacia un vaiven suave (dos senoidales). Se descarto por lo
que pidio el usuario, y el motivo es correcto: *"la transicion suaviza y hace
que se pierda la dopamina de la sorpresa"*. Un zoom que se desliza el ojo lo
predice y deja de mirarlo; un salto seco no se puede predecir, y cada salto
vuelve a pedir atencion. Es la misma logica del jump cut duro que ya usa el
video en cada empalme.

Ademas resuelve gratis el problema que tenia el zoom suave: al deslizarse, el
encuadre se movia menos de un pixel por frame y la grilla de pixeles enteros lo
convertia en un escalonado (medido: a 4% en 7 segundos el escalon era el 100%
del movimiento del frame). Con saltos no hay movimiento sub-pixel que cuantizar:
cada tramo es un zoom fijo.

POR QUE SOLO EL GAMEPLAY
-------------------------
Zoomear el canvas entero acerca tambien la webcam, y la cara no aguanta el
tironeo: se lee como que se mueve la persona, no la edicion. El gameplay si -es
donde pasa la accion y donde el salto se lee como "mira esto"-.

DONDE SE ENGANCHA, Y POR QUE ES ASI DE RARO
--------------------------------------------
El gameplay se compone ANTES de cortar los trozos, asi que ahi su reloj es el
del stream original. Si el zoom se aplicara en esa rama, un salto programado
para el segundo 10 podria caer en cualquier lado del clip final -o quedar
directamente fuera, si ese pedazo se corto-. Por eso el panel se vuelve a
separar DESPUES del concat, cuando el reloj ya es el del clip terminado:

    [vcat] -> split -> recorte de arriba (camara, intacta) ------> [
            \\-> recorte de abajo (gameplay) -> ZOOM A SALTOS -> [ vstack -> ass

Y todo eso antes del `ass`, para que los subtitulos y el cartel queden clavados
y del mismo tamaño siempre.
"""
import random

# amplitud: cuanto acerca en el plano mas cerrado (0.14 = 14%)
# sostener:  (minimo, maximo) segundos que se queda en cada plano antes del salto
# Tres modos, y NINGUNO tiene transicion: los tres son salto seco. Lo unico que
# cambia entre ellos es cuanto acerca y cada cuanto salta.
NIVELES = {
    "apagado": None,
    "simple": dict(amplitud=0.08, sostener=(1.8, 2.8)),
    "mediano": dict(amplitud=0.15, sostener=(1.0, 1.8)),
    "extremo": dict(amplitud=0.22, sostener=(0.7, 1.2)),
}
NIVEL_DEFECTO = "mediano"

# Tres planos, no dos: con dos el vaiven se vuelve un interruptor y se predice
# despues de tres saltos. El del medio rompe el patron sin costar nada.
ESCALONES = (0.0, 0.55, 1.0)


def pasos(nivel, duracion, semilla=0):
    """Los saltos del clip: lista de (segundo en que salta, zoom).

    Los tiempos NO son parejos a proposito. Un salto cada exactamente 1,5 s se
    escucha como un metronomo y el ojo lo empieza a anticipar, que es justo lo
    que se quiere evitar. La variacion es pseudoaleatoria pero determinista
    -sembrada con el numero de clip-, asi que volver a renderizar el mismo clip
    da exactamente el mismo resultado.
    """
    cfg = NIVELES.get(nivel)
    if not cfg or duracion <= 0:
        return []
    rnd = random.Random(semilla * 7919 + 13)
    lo, hi = cfg["sostener"]
    # Arranca SIEMPRE en el plano mas abierto, para que el primer salto sea una
    # entrada. Al reves -abrir cerrado y saltar hacia afuera- el arranque se lee
    # como que algo se aleja, que es lo contrario de retener.
    fuera, t, previo = [], 0.0, 1.0
    while t < duracion:
        opciones = [e for e in ESCALONES if e != previo]
        # el plano abierto y el cerrado pesan mas que el del medio: el medio
        # esta para romper el patron, no para ser el estado habitual
        e = rnd.choices(opciones, weights=[1.0 if o != 0.55 else 0.45 for o in opciones])[0]
        previo = e
        fuera.append((round(t, 3), round(1.0 + cfg["amplitud"] * e, 4)))
        t += rnd.uniform(lo, hi)
    return fuera


def expresion(pasos_):
    """Los saltos, como expresion de ffmpeg en funcion de `time`.

    Sale una cadena de `if` anidados. Con un clip de 35 s y saltos cada ~1,4 s
    son unos 25 niveles, que ffmpeg evalua sin problema.
    """
    if not pasos_:
        return "1"
    e = f"{pasos_[-1][1]:.4f}"
    # de atras para adelante: cada nivel tapa al anterior hasta su propio corte.
    # `lt` estricto -> en el instante exacto del salto ya vale el zoom nuevo.
    for (t, z), (t_sig, _) in zip(reversed(pasos_[:-1]), reversed(pasos_[1:])):
        e = f"if(lt(time,{t_sig:.3f}),{z:.4f},{e})"
    return e


def filtro(nivel, duracion, ancho, alto, cam_alto, fps, entrada, salida, semilla=0):
    """El tramo de filtergraph que hace los saltos. Cadena vacia si esta apagado.

    `cam_alto` es la altura de la franja de camara, que queda INTACTA. Si es 0
    -no hay camara: el gameplay ocupa todo- se zoomea el cuadro entero.
    """
    ps = pasos(nivel, duracion, semilla)
    if not ps or all(z == 1.0 for _, z in ps):
        return ""
    z = expresion(ps)
    game_alto = alto - cam_alto

    zp = (f"zoompan=z='{z}':d=1:x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
          f"s={ancho}x{game_alto}:fps={fps}")

    if not cam_alto:
        return f"[{entrada}]{zp}[{salida}];"

    # se vuelven a separar los dos paneles del cuadro ya pegado, se zoomea solo
    # el de abajo y se re-apilan
    return (f"[{entrada}]split=2[zcam][zgame];"
            f"[zcam]crop={ancho}:{cam_alto}:0:0,setsar=1[zcamr];"
            f"[zgame]crop={ancho}:{game_alto}:0:{cam_alto},{zp},setsar=1[zgamer];"
            f"[zcamr][zgamer]vstack=inputs=2[{salida}];")
