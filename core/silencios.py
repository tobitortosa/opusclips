# -*- coding: utf-8 -*-
"""Corte de tiempos muertos: deja el clip sin un solo momento sin voz.

DOS LOGICAS DISTINTAS, NO UNA CON PARAMETROS
---------------------------------------------
El primer diseño fue conservador: arrancar del clip entero e ir sacandole las
pausas mas largas que un umbral. Eso tiene un TECHO matematico -por mas que se
baje el umbral, nunca llega a cero silencio, porque siempre queda el aire que
se deja a los costados de cada corte-.

El usuario pidio explicitamente que no quede NINGUN silencio de voz. Para eso
la logica se da vuelta:

  modo "huecos"   (suave / normal / frenetico)
      Parte del clip completo y le saca las pausas > umbral. Conserva el ritmo
      natural del habla. Nunca llega a cero silencio.

  modo "solo_voz" (maximo)  <- el que se usa por defecto
      No saca nada: ARMA el clip pegando unicamente los tramos donde hay voz,
      con 20 ms de respiro a cada lado, y corta hasta las micro-pausas DENTRO
      de una frase. El silencio es cero por construccion.

      El usuario fue explicito: "prefiero que dure 10 segundos pero que sea
      frenetico antes que 30 y lento". Por eso aca la duracion final no se
      protege: si un clip de 40 s queda en 12 s, esta bien.

Lo que se conserva de la version conservadora, porque sigue siendo cierto:

- La voz es la UNION de las palabras del ASR y los tramos del VAD. Si se mirara
  solo la transcripcion se perderian las risas y los gritos, que Whisper no
  transcribe y que son lo mejor de un clip de gaming.
- Cortar el audio de golpe hace un chasquido. Cada empalme lleva un fundido de
  12 ms: imperceptible como fundido, pero sin el, con 30 cortes, el clip es
  injugable.
"""
import numpy as np

SR = 16000
VENTANA_FONDO = 0.15       # se mide el fondo en ventanas de 150 ms
FUNDIDO = 0.012            # micro-fundido de audio en cada empalme (12 ms)
MAX_SEGMENTOS = 150        # tope de trozos por clip, para no armar un filtergraph gigante
PUNCH_ZOOM = 1.075         # cuanto acerca el encuadre
PUNCH_CADA = 1.6           # cada cuantos segundos de metraje cambia el encuadre

NIVELES = {
    # modo "huecos": arranca del clip entero y le saca las pausas mas largas
    # que `hueco_minimo`. Tiene un techo: nunca llega a cero silencio.
    "suave": dict(
        modo="huecos",
        hueco_minimo=0.70,     # solo corta pausas largas
        aire=0.18,             # deja bastante respiro a cada lado
        max_prop=0.25,         # nunca saca mas del 25%
        dif_fondo_db=4.0,      # muy exigente con la continuidad del ruido de fondo
        chequear_golpes=True,
    ),
    "normal": dict(
        modo="huecos", hueco_minimo=0.45, aire=0.11, max_prop=0.45,
        dif_fondo_db=7.0, chequear_golpes=True,
    ),
    "frenetico": dict(
        modo="huecos", hueco_minimo=0.26, aire=0.06, max_prop=0.70,
        dif_fondo_db=99.0, chequear_golpes=True,
    ),

    # modo "solo_voz": la logica al reves. No saca pausas del clip: ARMA el clip
    # pegando unicamente los tramos donde hay voz. El silencio queda en cero por
    # construccion, no por umbral. Es lo que se busca cuando el clip tiene que
    # ser "ta-ta-ta-ta sin parar".
    "maximo": dict(
        modo="solo_voz",
        pad=0.02,              # apenas 20 ms de respiro: pega una palabra con la otra
        unir_bajo=0.06,        # corta hasta las micro-pausas DENTRO de una frase
        min_trozo=0.08,        # conserva trozos de 80 ms
        max_prop=0.96,         # puede sacar casi todo el clip
        chequear_golpes=False, # a esta altura el ritmo manda sobre todo lo demas
        punch_in=True,         # ademas mueve el encuadre
    ),
}
NIVEL_DEFECTO = "maximo"

# compatibilidad con el codigo viejo
HUECO_MINIMO = NIVELES["suave"]["hueco_minimo"]
AIRE = NIVELES["suave"]["aire"]
MAX_PROPORCION = NIVELES["suave"]["max_prop"]
DIF_FONDO_DB = NIVELES["suave"]["dif_fondo_db"]


def _rms_db(pcm, t, dur=VENTANA_FONDO):
    a = max(0, int(t * SR))
    b = min(len(pcm), int((t + dur) * SR))
    if b - a < 160:
        return None
    x = pcm[a:b]
    return 20 * np.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-12)


def _hay_transitorio(pcm, t, radio=0.25):
    """True si hay un golpe seco cerca (explosion, impacto): cortar ahi se nota."""
    a = max(0, int((t - radio) * SR))
    b = min(len(pcm), int((t + radio) * SR))
    if b - a < SR // 20:
        return False
    x = np.abs(pcm[a:b])
    h = max(1, SR // 200)                      # ventanas de 5 ms
    n = len(x) // h
    if n < 4:
        return False
    env = x[:n * h].reshape(n, h).max(axis=1)
    subidas = np.diff(env)
    return bool(subidas.max() > 4.0 * (np.median(np.abs(subidas)) + 1e-6) and subidas.max() > 0.05)


def _union_voz(palabras, tramos_voz, inicio, fin):
    """Todo lo que cuenta como voz: union de las palabras del ASR y los tramos
    del VAD. Se usan los dos porque el ASR no transcribe risas ni gritos, y el
    VAD no distingue palabras."""
    ocupado = [(w["a"], w["b"]) for w in palabras if w["b"] > inicio and w["a"] < fin]
    ocupado += [(t["a"], t["b"]) for t in tramos_voz if t["b"] > inicio and t["a"] < fin]
    if not ocupado:
        return []
    ocupado.sort()
    union = [list(ocupado[0])]
    for a, b in ocupado[1:]:
        if a <= union[-1][1]:
            union[-1][1] = max(union[-1][1], b)
        else:
            union.append([a, b])
    return union


def _plan_solo_voz(palabras, tramos_voz, inicio, fin, cfg):
    """Arma el clip pegando SOLO los tramos con voz. Cero silencio por diseño."""
    pad = cfg["pad"]
    unir = cfg["unir_bajo"]
    union = _union_voz(palabras, tramos_voz, inicio, fin)
    if not union:
        return [(inicio, fin)], dict(cortes=0, quitado=0.0, proporcion=0.0,
                                     duracion_final=round(fin - inicio, 2),
                                     modo="solo_voz", motivo="no hay voz detectada")

    # cada tramo de voz, con un respiro minimo a los costados
    trozos = []
    for a, b in union:
        trozos.append([max(inicio, a - pad), min(fin, b + pad)])

    # pegar los que quedan casi tocandose: cortar por 80 ms no aporta nada y
    # multiplica los empalmes
    fusion = [trozos[0]]
    for a, b in trozos[1:]:
        if a - fusion[-1][1] < unir:
            fusion[-1][1] = max(fusion[-1][1], b)
        else:
            fusion.append([a, b])

    conservar = [(a, b) for a, b in fusion if b - a >= cfg["min_trozo"]]
    if not conservar:
        return [(inicio, fin)], dict(cortes=0, quitado=0.0, proporcion=0.0,
                                     duracion_final=round(fin - inicio, 2), modo="solo_voz")

    # tope de seguridad y de cantidad de empalmes
    dur = fin - inicio
    final = sum(b - a for a, b in conservar)
    if dur - final > dur * cfg["max_prop"]:
        # se estaria sacando demasiado: se agrandan los trozos hasta el limite
        falta = (dur - final) - dur * cfg["max_prop"]
        extra = falta / (2 * len(conservar))
        conservar = [(max(inicio, a - extra), min(fin, b + extra)) for a, b in conservar]
    if len(conservar) > MAX_SEGMENTOS:
        # se queda con los trozos mas largos, para no armar un filtergraph gigante
        largos = sorted(conservar, key=lambda t: -(t[1] - t[0]))[:MAX_SEGMENTOS]
        conservar = sorted(largos)

    final = sum(b - a for a, b in conservar)
    return conservar, dict(
        cortes=max(0, len(conservar) - 1), quitado=round(dur - final, 2),
        proporcion=round((dur - final) / dur, 3) if dur else 0.0,
        duracion_final=round(final, 2), modo="solo_voz",
        habla_final=1.0, rechazados=[])


def planificar(palabras, tramos_voz, pcm, inicio, fin, nivel=NIVEL_DEFECTO,
               hueco_minimo=None, aire=None, max_prop=None):
    """Devuelve (tramos_a_conservar, informe).

    `pcm` es el audio COMPLETO del stream (float32 mono 16 kHz), y los tiempos
    estan en la escala del stream, no del clip.
    """
    cfg = NIVELES.get(nivel, NIVELES[NIVEL_DEFECTO])
    if cfg.get("modo") == "solo_voz":
        return _plan_solo_voz(palabras, tramos_voz, inicio, fin, cfg)

    hueco_minimo = cfg["hueco_minimo"] if hueco_minimo is None else hueco_minimo
    aire = cfg["aire"] if aire is None else aire
    max_prop = cfg["max_prop"] if max_prop is None else max_prop
    dif_fondo = cfg["dif_fondo_db"]
    chequear_golpes = cfg["chequear_golpes"]
    dur = fin - inicio
    # todo lo que cuenta como "hay voz": union de palabras del ASR y tramos del VAD
    ocupado = []
    for w in palabras:
        if w["b"] > inicio and w["a"] < fin:
            ocupado.append((w["a"], w["b"]))
    for t in tramos_voz:
        if t["b"] > inicio and t["a"] < fin:
            ocupado.append((t["a"], t["b"]))
    if not ocupado:
        return [(inicio, fin)], dict(cortes=0, quitado=0.0, motivo="no hay voz detectada")

    ocupado.sort()
    union = [list(ocupado[0])]
    for a, b in ocupado[1:]:
        if a <= union[-1][1]:
            union[-1][1] = max(union[-1][1], b)
        else:
            union.append([a, b])

    # los huecos son lo que queda entre medio
    huecos, rechazados = [], []
    for (a1, b1), (a2, b2) in zip(union, union[1:]):
        h0, h1 = b1, a2
        if h1 - h0 < hueco_minimo + 2 * aire:
            continue
        corte_a, corte_b = h0 + aire, h1 - aire
        centro = (corte_a + corte_b) / 2

        if dif_fondo < 90:
            izq, der = _rms_db(pcm, corte_a - VENTANA_FONDO), _rms_db(pcm, corte_b)
            if izq is None or der is None:
                continue
            if abs(izq - der) > dif_fondo:
                rechazados.append(dict(t=round(centro, 2),
                                       motivo=f"el fondo cambia {abs(izq-der):.1f} dB"))
                continue
        if chequear_golpes and (_hay_transitorio(pcm, corte_a) or _hay_transitorio(pcm, corte_b)):
            rechazados.append(dict(t=round(centro, 2), motivo="hay un golpe de audio cerca"))
            continue
        huecos.append((corte_a, corte_b))

    # tope: sacar primero los huecos mas largos hasta llegar al limite
    huecos.sort(key=lambda h: -(h[1] - h[0]))
    elegidos, quitado = [], 0.0
    for a, b in huecos:
        if quitado + (b - a) > dur * max_prop:
            continue
        if len(elegidos) >= MAX_SEGMENTOS - 1:
            break
        elegidos.append((a, b))
        quitado += b - a
    elegidos.sort()

    # lo que queda entre los huecos elegidos es lo que se conserva
    conservar, cursor = [], inicio
    for a, b in elegidos:
        if a > cursor:
            conservar.append((cursor, a))
        cursor = b
    if cursor < fin:
        conservar.append((cursor, fin))
    conservar = [(a, b) for a, b in conservar if b - a > 0.15]
    if not conservar:
        conservar = [(inicio, fin)]
        elegidos, quitado = [], 0.0

    return conservar, dict(
        cortes=len(elegidos), quitado=round(quitado, 2),
        proporcion=round(quitado / dur, 3) if dur else 0.0,
        duracion_final=round(sum(b - a for a, b in conservar), 2),
        rechazados=rechazados[:8],
    )


class MapaTiempos:
    """Traduce un instante del stream original al instante del clip ya cortado.

    Es la pieza que puede fallar en silencio: si esta mal, el mp4 sale bien,
    pesa bien, y los subtitulos se van corriendo un poco mas con cada corte
    hasta quedar media palabra atrasados al final.
    """

    def __init__(self, conservar):
        self.tramos = list(conservar)
        self.acum = []
        t = 0.0
        for a, b in self.tramos:
            self.acum.append(t)
            t += b - a
        self.duracion = t

    def __call__(self, t):
        return self.mapear(t)

    def mapear(self, t):
        """Instante original -> instante en el clip. Si cae en un hueco cortado,
        se lo lleva al borde mas cercano que si quedo.

        Cuando hay cold open los tramos NO estan ordenados -el primero es un
        pedazo de mas adelante, pegado al principio-, y un mismo instante puede
        aparecer dos veces en el clip. Aca se recorre en orden temporal y se
        devuelve la aparicion mas tardia, que es la del clip "de verdad"; para
        los subtitulos, que si necesitan las dos apariciones, esta
        mapear_palabras(), que recorre tramo por tramo.
        """
        if not self.tramos:
            return 0.0
        orden = sorted(range(len(self.tramos)), key=lambda i: self.tramos[i][0])
        if t <= self.tramos[orden[0]][0]:
            return 0.0
        for i in orden:
            a, b = self.tramos[i]
            if t < a:                      # cayo en un hueco: va al inicio de este tramo
                return round(self.acum[i], 4)
            if t <= b:
                return round(self.acum[i] + (t - a), 4)
        return round(self.duracion, 4)

    def mapear_palabras(self, palabras, min_dur=0.06):
        """Reescribe las palabras a la escala del clip.

        Recorre TRAMO por TRAMO, no palabra por palabra, porque un mismo instante
        del original puede aparecer VARIAS veces en el clip: el cold open repite
        al principio un pedazo que despues vuelve a pasar. Con este orden, esas
        palabras salen dos veces, que es justo lo que tiene que pasar.
        """
        out = []
        for i, (a, b) in enumerate(self.tramos):
            base = self.acum[i]
            for w in palabras:
                if w["b"] <= a or w["a"] >= b:
                    continue               # la palabra no toca este tramo
                na = base + max(0.0, w["a"] - a)
                nb = base + min(b - a, w["b"] - a)
                if nb - na < min_dur:
                    nb = na + min_dur
                out.append(dict(w, a=round(na, 3), b=round(nb, 3)))
        out.sort(key=lambda w: w["a"])
        return out

    def filtro_ffmpeg(self, t0=0.0):
        """Version simple con select/aselect. Sirve para pocos cortes.

        Con muchos cortes deja un 'click' audible en cada empalme, porque la
        onda se corta de golpe. Para eso esta filtro_concat().
        """
        cond = "+".join(f"between(t,{a-t0:.4f},{b-t0:.4f})" for a, b in self.tramos)
        return (f"select='{cond}',setpts=N/FRAME_RATE/TB",
                f"aselect='{cond}',asetpts=N/SR/TB")

    def filtro_concat(self, ent_v, ent_a, sal_v, sal_a, t0=0.0, fundido=FUNDIDO,
                      punch_in=False, ancho=1080, alto=1920, zoom=PUNCH_ZOOM,
                      fps=60, zoom_primero=None):
        """Filtergraph que corta y pega con un micro-fundido de audio en cada empalme.

        Cortar el audio de golpe produce un chasquido en cada corte: con dos
        cortes no se nota, con veinticinco arruina el clip. El fundido de 12 ms
        es imperceptible como fundido pero elimina el chasquido por completo.

        El video se corta seco a proposito: el jump cut duro es lo que se busca.

        `punch_in` alterna el encuadre entre normal y un zoom leve en cada trozo.
        Es el recurso que usan los editores para que el ojo registre cada corte:
        no se percibe como "efecto", se percibe como que el video no se queda
        quieto nunca. El zoom va ANTES de quemar los subtitulos, asi el texto
        queda fijo y del mismo tamaño siempre.
        """
        n = len(self.tramos)
        if n <= 1:
            return ""
        p = []
        p.append(f"[{ent_v}]split={n}" + "".join(f"[sv{i}]" for i in range(n)))
        p.append(f"[{ent_a}]asplit={n}" + "".join(f"[sa{i}]" for i in range(n)))
        # concat EXIGE que todos los trozos tengan exactamente los mismos
        # parametros. El punch-in mete un scale/crop en los trozos alternados,
        # asi que hay que normalizar formato, SAR y frame rate en TODOS -incluso
        # en los que no llevan zoom- o el filtro falla al configurar la salida.
        # El punch-in alterna por TIEMPO ACUMULADO, no por trozo. Con cortes muy
        # finos puede haber cien trozos en un clip: alternar en cada uno seria un
        # parpadeo insoportable. Cambiando cada ~1,6 s el ojo percibe un ritmo.
        acum, zoom_on = 0.0, False
        for i, (a, b) in enumerate(self.tramos):
            ini, fin = a - t0, b - t0
            largo = fin - ini
            if punch_in and acum >= PUNCH_CADA:
                zoom_on = not zoom_on
                acum = 0.0
            acum += largo
            # el cold open (tramo 0, cuando lo hay) va con su propio acercamiento,
            # mas marcado, para que se lea como "adelanto" y no como parte del clip
            z = zoom_primero if (zoom_primero and i == 0) else (zoom if zoom_on else None)
            vid = f"[sv{i}]trim=start={ini:.4f}:end={fin:.4f},setpts=PTS-STARTPTS"
            # el acercamiento del cold open NO depende del punch-in: es lo que lo
            # hace leer como adelanto, y tiene que estar tambien en los niveles
            # donde el punch-in esta apagado (suave / normal / frenetico).
            if z:
                za, zl = int(round(ancho * z / 2)) * 2, int(round(alto * z / 2)) * 2
                vid += (f",scale={za}:{zl}:flags=bicubic"
                        f",crop={ancho}:{alto}:{(za-ancho)//2}:{(zl-alto)//2}")
            vid += f",format=yuv420p,setsar=1,fps={fps}"
            p.append(vid + f"[v{i}]")
            f = min(fundido, largo / 3)
            p.append(
                f"[sa{i}]atrim=start={ini:.4f}:end={fin:.4f},asetpts=PTS-STARTPTS,"
                f"afade=t=in:st=0:d={f:.4f},"
                f"afade=t=out:st={max(0.0, largo - f):.4f}:d={f:.4f},"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{i}]")
        cadena = "".join(f"[v{i}][a{i}]" for i in range(n))
        p.append(f"{cadena}concat=n={n}:v=1:a=1[{sal_v}][{sal_a}]")
        return ";".join(p) + ";"

    @property
    def hay_cortes(self):
        return len(self.tramos) > 1
