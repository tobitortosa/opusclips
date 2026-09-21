# -*- coding: utf-8 -*-
"""Tests del mapa de tiempos y de la reparacion de timestamps.

Estas dos piezas fallan EN SILENCIO: el clip sale, pesa bien, se reproduce, y
el error solo se ve mirando con atencion que el subtitulo va corrido. Por eso
tienen test propio.

Correr con:  .venv\\Scripts\\python.exe -m pytest tests -q
o directo:   .venv\\Scripts\\python.exe tests\\test_tiempos.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.silencios import MapaTiempos
from core.reparar import reparar, esta_roto


def test_sin_cortes_es_identidad_desplazada():
    m = MapaTiempos([(100.0, 130.0)])
    assert m.duracion == 30.0
    assert m.mapear(100.0) == 0.0
    assert m.mapear(115.0) == 15.0
    assert m.mapear(130.0) == 30.0


def test_un_corte_en_el_medio():
    # se conserva 100-110 y 115-130; el hueco 110-115 (5 s) se corta
    m = MapaTiempos([(100.0, 110.0), (115.0, 130.0)])
    assert m.duracion == 25.0
    assert m.mapear(100.0) == 0.0
    assert m.mapear(110.0) == 10.0
    assert m.mapear(115.0) == 10.0          # justo despues del corte
    assert m.mapear(120.0) == 15.0          # 5 s dentro del segundo tramo
    assert m.mapear(130.0) == 25.0


def test_instante_dentro_de_un_hueco_va_al_borde():
    m = MapaTiempos([(0.0, 10.0), (20.0, 30.0)])
    assert m.mapear(12.0) == 10.0           # cayo en el hueco -> borde siguiente
    assert m.mapear(19.9) == 10.0


def test_varios_cortes_acumulan_bien():
    # este es el caso que se desfasa si el acumulado esta mal
    m = MapaTiempos([(0, 5), (10, 15), (20, 25), (30, 35)])
    assert m.duracion == 20
    assert m.mapear(0) == 0
    assert m.mapear(4) == 4
    assert m.mapear(10) == 5
    assert m.mapear(14) == 9
    assert m.mapear(20) == 10
    assert m.mapear(24) == 14
    assert m.mapear(34) == 19
    # el error tipico seria que el ultimo diera 34 en vez de 19


def test_monotonia_nunca_va_para_atras():
    m = MapaTiempos([(0, 5), (10, 15), (20, 25)])
    ant = -1.0
    t = 0.0
    while t <= 26.0:
        v = m.mapear(t)
        assert v >= ant - 1e-9, f"el mapa retrocedio en t={t}"
        ant = v
        t += 0.05


def test_palabras_dentro_de_un_corte_se_descartan():
    m = MapaTiempos([(0, 5), (10, 15)])
    palabras = [
        dict(t="hola", a=1.0, b=1.4),     # se conserva
        dict(t="chau", a=7.0, b=7.4),     # cae en el hueco -> fuera
        dict(t="dale", a=11.0, b=11.5),   # se conserva, corrido -6 s
    ]
    out = m.mapear_palabras(palabras)
    assert [w["t"] for w in out] == ["hola", "dale"]
    assert out[0]["a"] == 1.0
    assert out[1]["a"] == 6.0             # 11.0 - 5 s de hueco cortado


def test_filtro_ffmpeg_tiene_un_between_por_tramo():
    m = MapaTiempos([(1.5, 9.25), (12.0, 20.0)])
    v, a = m.filtro_ffmpeg()
    assert v.count("between") == 2 and a.count("between") == 2
    assert "1.5000,9.2500" in v and "12.0000,20.0000" in v
    assert v.startswith("select=") and a.startswith("aselect=")


def test_filtro_concat_arma_un_trozo_por_tramo():
    m = MapaTiempos([(100.0, 105.0), (106.5, 110.0), (112.0, 118.0)])
    fg = m.filtro_concat("stack", "0:a", "vo", "ao", t0=100.0)
    assert fg.count("trim=start=") == 6        # 3 de video + 3 de audio (atrim)
    assert fg.count("afade=t=in") == 3         # un fundido de entrada por trozo
    assert fg.count("afade=t=out") == 3
    assert "concat=n=3:v=1:a=1[vo][ao]" in fg
    assert "split=3" in fg and "asplit=3" in fg
    # los tiempos van relativos a t0, porque el -ss ya posiciono el input
    assert "trim=start=0.0000:end=5.0000" in fg
    assert "trim=start=12.0000:end=18.0000" in fg


def test_filtro_concat_vacio_si_no_hay_cortes():
    assert MapaTiempos([(0.0, 30.0)]).filtro_concat("v", "a", "vo", "ao") == ""


def test_fundido_no_supera_un_tercio_del_trozo():
    # un trozo muy corto no puede llevar un fundido de 12 ms de entrada y otro
    # de salida sin comerse el trozo entero
    m = MapaTiempos([(0.0, 0.02), (1.0, 5.0)])
    fg = m.filtro_concat("v", "a", "vo", "ao")
    import re
    for d in re.findall(r"afade=t=in:st=0:d=([\d.]+)", fg):
        assert float(d) <= 0.02 / 3 + 1e-9 or float(d) <= 0.012 + 1e-9


# ------------------------------------------------------------ reparar.py
def test_duracion_cero_se_arregla():
    p = [dict(t="que", a=10.0, b=10.0), dict(t="tal", a=12.0, b=12.4)]
    reparar(p)
    assert p[0]["b"] > p[0]["a"] + 0.05
    assert p[0]["b"] <= p[1]["a"]           # no invade a la siguiente


def test_palabra_corta_con_duracion_absurda_se_recorta():
    p = [dict(t="si", a=1.0, b=15.0)]
    reparar(p)
    assert p[0]["a"] == 1.0                 # el ARRANQUE se respeta siempre
    assert p[0]["b"] - p[0]["a"] < 1.5


def test_solapes_se_eliminan():
    p = [dict(t="hola", a=1.0, b=2.0), dict(t="che", a=1.5, b=2.5)]
    reparar(p)
    assert p[1]["a"] >= p[0]["b"] - 1e-9


def test_no_toca_lo_que_esta_bien():
    p = [dict(t="hola", a=1.0, b=1.4), dict(t="che", a=1.5, b=1.9)]
    copia = [dict(w) for w in p]
    reparar(p)
    assert p == copia


def test_esta_roto_detecta_los_tres_casos():
    assert esta_roto(dict(t="que", a=1.0, b=1.0)) == "corta"
    assert esta_roto(dict(t="si", a=1.0, b=9.0)) == "larga"
    assert esta_roto(dict(t="hola", a=1.0, b=2.0), dict(t="che", a=1.5, b=2.0)) == "solape"
    assert esta_roto(dict(t="hola", a=1.0, b=1.4), dict(t="che", a=1.5, b=1.9)) is None


# ------------------------------------------------------- modo "solo voz"
def test_solo_voz_no_deja_ningun_silencio():
    from core.silencios import planificar, NIVELES
    # 40 s de clip con voz solo en tres tramos
    palabras = [dict(t="a", a=1.0, b=2.0), dict(t="b", a=10.0, b=12.0),
                dict(t="c", a=30.0, b=33.0)]
    tramos = [dict(a=1.0, b=2.0), dict(a=10.0, b=12.0), dict(a=30.0, b=33.0)]
    cons, inf = planificar(palabras, tramos, None, 0.0, 40.0, nivel="maximo")
    assert inf["modo"] == "solo_voz"
    # lo que queda es solo voz mas el pad de 50 ms a cada lado
    esperado = (1.0 + 2.0 + 3.0) + 3 * 2 * NIVELES["maximo"]["pad"]
    assert abs(inf["duracion_final"] - esperado) < 0.01
    assert inf["duracion_final"] < 7.0        # de 40 s quedan menos de 7
    assert inf["cortes"] == 2


def test_solo_voz_pega_los_tramos_casi_juntos():
    from core.silencios import planificar
    # dos tramos separados por 80 ms: no vale la pena cortar ahi
    palabras = [dict(t="a", a=1.0, b=2.0), dict(t="b", a=2.08, b=3.0)]
    tramos = [dict(a=1.0, b=2.0), dict(a=2.08, b=3.0)]
    cons, inf = planificar(palabras, tramos, None, 0.0, 10.0, nivel="maximo")
    assert len(cons) == 1, "dos tramos casi pegados tienen que quedar en uno solo"
    assert inf["cortes"] == 0


def test_solo_voz_usa_el_vad_ademas_del_asr():
    from core.silencios import planificar, NIVELES
    # una risa que el VAD detecta pero el ASR no transcribe
    palabras = [dict(t="a", a=1.0, b=2.0)]
    tramos = [dict(a=1.0, b=2.0), dict(a=5.0, b=7.0)]   # 5-7 es la risa
    cons, inf = planificar(palabras, tramos, None, 0.0, 10.0, nivel="maximo")
    assert len(cons) == 2, "la risa detectada por el VAD tiene que conservarse"
    pad = NIVELES["maximo"]["pad"]
    assert any(abs(a - (5.0 - pad)) < 0.01 for a, b in cons), \
        "el tramo de la risa tiene que estar, con su pad"


def test_solo_voz_sin_voz_devuelve_el_clip_entero():
    from core.silencios import planificar
    cons, inf = planificar([], [], None, 0.0, 20.0, nivel="maximo")
    assert cons == [(0.0, 20.0)] and inf["cortes"] == 0


def test_punch_in_alterna_por_tiempo_no_por_trozo():
    from core.silencios import PUNCH_CADA
    # 20 trozos de 0,2 s: si alternara por trozo habria 10 cambios de encuadre
    # y seria un parpadeo. Alternando por tiempo tiene que haber muchos menos.
    m = MapaTiempos([(i * 0.25, i * 0.25 + 0.2) for i in range(20)])
    fg = m.filtro_concat("v", "a", "vo", "ao", punch_in=True)
    total = 20 * 0.2
    cambios_esperados = total / PUNCH_CADA          # ~2,5 cambios en 4 s
    con_zoom = fg.count("crop=1080:1920:")
    assert 0 < con_zoom < 20, "tiene que acercar algunos trozos, no todos ni ninguno"
    # los trozos con zoom vienen en rachas, no uno si uno no
    assert con_zoom <= 12, f"{con_zoom} trozos con zoom es demasiado parpadeo"


def test_punch_in_arranca_sin_zoom():
    m = MapaTiempos([(0, 3), (4, 7)])
    fg = m.filtro_concat("v", "a", "vo", "ao", punch_in=True)
    primero = fg.split("[v0]")[0].split("[sv0]")[1]
    assert "crop=" not in primero, "el primer trozo va sin zoom"


def test_punch_in_apagado_no_toca_el_encuadre():
    m = MapaTiempos([(0, 1), (2, 3), (4, 5)])
    assert "crop=" not in m.filtro_concat("v", "a", "vo", "ao", punch_in=False)


# ------------------------------------------------------- cold open (gancho)
# El gancho lo elige Claude leyendo lo que se dice. Lo que se testea aca es la
# VALIDACION de lo que devuelve: un modelo puede mandar cualquier cosa y nada de
# eso puede llegar al render.
CLIP = dict(n=1, inicio=100.0, fin=140.0)
PAL = [dict(t=f"p{i}", a=100.0 + i * 0.5, b=100.0 + i * 0.5 + 0.35) for i in range(80)]


def _g(**kw):
    base = dict(clip=1, sirve=True, inicio=120.0, fin=122.6, frase="x", por_que="y")
    base.update(kw)
    return base


def test_gancho_valido_pasa():
    from core.gancho import validar, DUR_MIN, DUR_MAX
    v = validar(_g(), CLIP, PAL)
    assert v is not None
    assert DUR_MIN - 0.3 <= v["dur"] <= DUR_MAX + 0.3
    assert CLIP["inicio"] <= v["desde"] < v["hasta"] <= CLIP["fin"]


def test_gancho_fuera_del_clip_se_rechaza():
    from core.gancho import validar
    assert validar(_g(inicio=50.0, fin=53.0), CLIP, PAL) is None     # antes del clip
    assert validar(_g(inicio=138.0, fin=145.0), CLIP, PAL) is None   # se pasa del final
    assert validar(_g(inicio=125.0, fin=120.0), CLIP, PAL) is None   # invertido


def test_gancho_en_el_arranque_del_clip_se_rechaza():
    from core.gancho import validar
    # mostrar los primeros segundos como adelanto seria repetir lo mismo
    assert validar(_g(inicio=100.5, fin=103.0), CLIP, PAL) is None


def test_gancho_muy_corto_se_estira():
    from core.gancho import validar, DUR_MIN
    v = validar(_g(inicio=120.0, fin=120.4), CLIP, PAL)   # 0,4 s: no se entiende
    assert v is not None and v["dur"] >= DUR_MIN - 0.3


def test_gancho_muy_largo_se_recorta():
    from core.gancho import validar, DUR_MAX
    v = validar(_g(inicio=110.0, fin=128.0), CLIP, PAL)   # 18 s: no es un adelanto
    assert v is not None and v["dur"] <= DUR_MAX + 0.3


def test_gancho_marcado_como_inservible_se_descarta():
    from core.gancho import validar
    assert validar(_g(sirve=False), CLIP, PAL) is None


def test_gancho_con_datos_basura_no_explota():
    from core.gancho import validar
    for malo in (_g(inicio="hola"), _g(fin=None), dict(clip=1, sirve=True)):
        assert validar(malo, CLIP, PAL) is None


# --- el menu de candidatos ------------------------------------------------
# El modelo ya no inventa tiempos: elige el NUMERO de un fragmento de esta lista.
# Por eso lo que hay que testear es que la lista este bien armada.

def _pcm_de(tramos, dur=145.0, sr=16000, base=0.02):
    """Audio sintetico del STREAM entero: ruido bajo y los tramos mas fuertes.

    Tiene que llegar hasta el final del clip (que arranca en el segundo 100):
    el nivel de referencia se mide sobre las palabras del clip, y si el pcm se
    corta antes no hay con que comparar.
    """
    import numpy as np
    x = (np.random.RandomState(3).randn(int(dur * sr)) * base).astype("float32")
    for a, b, g in tramos:
        x[int(a * sr):int(b * sr)] *= g
    return x


def test_candidatos_respetan_duracion_y_no_pisan_el_arranque():
    from core.gancho import candidatos, DUR_MIN, DUR_MAX, NO_ARRANCAR_ANTES
    pcm = _pcm_de([(120.0, 123.0, 8.0)])
    cands = candidatos(CLIP, PAL, [], pcm)
    assert cands, "tiene que ofrecer al menos un fragmento"
    assert any(c["exceso"] is not None for c in cands), "tienen que traer su nivel en dB"
    for c in cands:
        assert DUR_MIN <= c["dur"] <= DUR_MAX, c
        assert CLIP["inicio"] <= c["a"] < c["b"] <= CLIP["fin"], c
        assert c["a"] - CLIP["inicio"] >= NO_ARRANCAR_ANTES, "no puede repetir el arranque"
    assert [c["id"] for c in cands] == list(range(1, len(cands) + 1))


def test_la_risa_sin_palabras_entra_al_menu():
    """Lo que hace posible elegir una risa o un grito.

    Medido sobre el stream real: de los 30 picos de voz mas fuertes, 10 no tienen
    NINGUNA palabra transcrita (Whisper escribe "jaj*" una sola vez en dos
    horas). Antes esos momentos eran inelegibles, porque el modelo solo podia
    devolver tiempos deducidos de los timestamps de las palabras.
    """
    from core.gancho import candidatos
    # palabras hasta 110 y desde 113: entre medio el VAD oye voz y el ASR no
    pal = [dict(t=f"p{i}", a=100.0 + i * 0.5, b=100.0 + i * 0.5 + 0.35) for i in range(20)]
    pal += [dict(t=f"q{i}", a=113.0 + i * 0.5, b=113.0 + i * 0.5 + 0.35) for i in range(20)]
    tramos = [dict(a=110.2, b=112.6)]                       # la risa
    pcm = _pcm_de([(110.2, 112.6, 10.0)])
    cands = candidatos(CLIP, pal, tramos, pcm)
    reac = [c for c in cands if c["tipo"] == "reaccion"]
    assert reac, f"la reaccion sin palabras tiene que ser elegible: {cands}"
    assert any(c["a"] <= 111.0 <= c["b"] for c in reac), "y tiene que cubrir la risa"


def test_resolver_toma_el_candidato_por_numero():
    from core.gancho import candidatos, resolver, FUERZA_MINIMA
    pcm = _pcm_de([(120.0, 123.0, 8.0)])
    cands = candidatos(CLIP, PAL, [], pcm)
    r = dict(clip=1, sirve=True, candidato=cands[0]["id"], cartel="QUE HICISTE",
             fuerza=80, por_que="x")
    v = resolver(r, CLIP, cands)
    assert v and v["desde"] == cands[0]["a"] and v["cartel"] == "QUE HICISTE"
    assert v["version"] == 2
    # un numero que no existe, o poca fuerza, no llegan al render
    assert resolver(dict(r, candidato=999), CLIP, cands) is None
    assert resolver(dict(r, fuerza=FUERZA_MINIMA - 1), CLIP, cands) is None
    assert resolver(dict(r, sirve=False), CLIP, cands) is None


def test_cartel_nunca_se_desborda():
    from core.subtitulos import partir_cartel
    from core.config import CARTEL_MAX_LINEAS
    for txt in ("QUE HICISTE", "SE SUBASTO MI PROPIA CABEZA EN LA TIENDA DEL SERVIDOR",
                "A", "PELEO AL WARDEN SOLO"):
        lineas = partir_cartel(txt)
        assert lineas and len(lineas) <= CARTEL_MAX_LINEAS, (txt, lineas)


def test_el_cartel_solo_dura_el_cold_open(tmp=None):
    import tempfile, os
    from core.subtitulos import escribir_ass
    cues = [[dict(t="hola", a=0.0, b=0.4, p=1.0)]]
    d = os.path.join(tempfile.gettempdir(), "cartel_test.ass")
    escribir_ass(cues, d, t0=0.0, cartel="QUE HICISTE", cartel_hasta=2.6)
    txt = open(d, encoding="utf-8-sig").read()
    linea = [l for l in txt.splitlines() if l.startswith("Dialogue") and "CARTEL" in l]
    assert len(linea) == 1, "un solo cartel"
    assert "0:00:00.00,0:00:02.60" in linea[0], "y solo durante el cold open"
    # sin cartel no se emite nada
    escribir_ass(cues, d, t0=0.0)
    assert "CARTEL,," not in open(d, encoding="utf-8-sig").read()


def test_el_golpe_de_audio_cae_en_el_corte():
    from core.render import construir_filtro
    m = MapaTiempos([(125.0, 127.6), (100.0, 110.0), (120.0, 130.0)])
    f = construir_filtro("x.ass", True, m, t0=100.0, punch_in=True,
                         zoom_gancho=1.12, impacto_en=2.6)
    assert "amovie=impacto.wav" in f and "amix=inputs=2" in f
    assert "adelay=2550|2550" in f, "50 ms antes del corte del cold open"
    # y el loudnorm mide el clip CON el golpe adentro, no antes
    assert f.index("amix=inputs=2") < f.index("loudnorm")
    assert "amovie" not in construir_filtro("x.ass", True, m, t0=100.0)


def test_zoom_del_gancho_solo_en_el_primer_trozo():
    m = MapaTiempos([(18.0, 19.0), (0.0, 10.0), (12.0, 20.0)])
    fg = m.filtro_concat("v", "a", "vo", "ao", punch_in=True, zoom_primero=1.12)
    primero = fg.split("[v0]")[0]
    assert "crop=" in primero, "el cold open va con su propio acercamiento"
    # y usa el zoom del gancho, no el del punch-in
    assert "scale=1210:2150" in primero or "scale=1208:2150" in primero


def test_palabras_repetidas_por_el_cold_open():
    # el cold open repite 18-19, que tambien esta dentro del clip
    m = MapaTiempos([(18.0, 19.0), (10.0, 25.0)])
    pal = [dict(t="NO", a=18.2, b=18.6), dict(t="hola", a=11.0, b=11.4)]
    out = m.mapear_palabras(pal)
    assert sum(1 for w in out if w["t"] == "NO") == 2,         "la palabra del adelanto tiene que aparecer dos veces"
    assert out[0]["t"] == "NO" and out[0]["a"] < 0.5    # primero, en el adelanto
    assert out[-1]["t"] == "NO"                          # y de nuevo en el clip


# ------------------------------------------------- vaiven de zoom (core/zoom.py)
# El encuadre se mueve durante TODO el clip. Lo que se testea: que el zoom se
# quede dentro del rango prometido, que no se repita, y sobre todo DONDE se
# engancha en el filtergraph -despues del concat y antes de los subtitulos-,
# que es de lo que depende que el texto no se agrande con la imagen.

def test_el_zoom_se_queda_en_el_rango_prometido():
    from core import zoom
    for nivel, cfg in zoom.NIVELES.items():
        r = zoom.recorrido(nivel, segundos=60)
        if cfg is None:
            assert r == []
            continue
        assert min(r) >= 1.0 - 1e-6, f"{nivel} se aleja mas alla del plano original"
        assert max(r) <= 1.0 + cfg["amplitud"] + 1e-6, f"{nivel} se pasa de la amplitud"
        assert r[0] == min(r), "tiene que abrir en el plano mas abierto y entrar"


def test_el_zoom_no_se_repite():
    """Dos ondas en proporcion aurea: el movimiento no se repite.

    Si se repitiera, se vuelve predecible y se lee como plantilla. La proporcion
    aurea es el numero mas dificil de aproximar por una fraccion, o sea lo mas
    lejos que se puede estar de un ciclo que vuelve. Aun asi hay CASI
    coincidencias en los indices de Fibonacci -la mas cercana cae en el ciclo 8,
    a los 32 segundos- y eso es irreducible: cualquier otra proporcion vuelve a
    coincidir antes. Lo que se exige es que ninguna se acerque a menos del 5% de
    la amplitud, que es la diferencia que ya no se percibe.
    """
    from core import zoom
    amp = zoom.NIVELES["llamativo"]["amplitud"]
    r = zoom.recorrido("llamativo", segundos=40)
    c = int(zoom.NIVELES["llamativo"]["ciclo"] * 60)
    primero = r[:c]
    for k in range(1, len(r) // c):
        dif = max(abs(a - b) for a, b in zip(primero, r[k * c:(k + 1) * c]))
        assert dif > 0.05 * amp, f"el ciclo {k} repite el primero (difiere {dif:.4f})"


def test_el_zoom_va_despues_del_concat_y_antes_de_los_subtitulos():
    """El orden es lo unico que importa de verdad aca.

    Si el zoom fuera ANTES del concat se reiniciaria en cada trozo (150 en modo
    sin respiro) y seria un temblor. Si fuera DESPUES del `ass`, el texto se
    agrandaria y achicaria con la imagen.
    """
    from core.render import construir_filtro
    m = MapaTiempos([(0.0, 3.0), (5.0, 9.0), (12.0, 20.0)])
    f = construir_filtro("x.ass", True, m, nivel_zoom="llamativo")
    assert f.index("concat=") < f.index("zoompan"), "el zoom va despues de pegar los trozos"
    assert f.index("zoompan") < f.index("ass=x.ass"), "y antes de quemar los subtitulos"
    # el trozo de zoom toma [vcat] y entrega [vzm], que es lo que consume el ass
    assert "[vcat]zoompan" in f and "[vzm]ass=x.ass" in f


def test_sin_cortes_el_zoom_igual_se_aplica():
    from core.render import construir_filtro
    f = construir_filtro("x.ass", True, nivel_zoom="llamativo")
    assert "[stack]zoompan" in f and "[vzm]ass=x.ass" in f


def test_zoom_apagado_no_deja_rastro():
    from core.render import construir_filtro
    m = MapaTiempos([(0.0, 3.0), (5.0, 9.0)])
    for nivel in (None, "apagado"):
        f = construir_filtro("x.ass", True, m, nivel_zoom=nivel)
        assert "zoompan" not in f
        assert "[vcat]ass=x.ass" in f, "el ass tiene que tomar directo del concat"


def test_punch_in_y_vaiven_no_se_encinan():
    """Los dos zooms multiplicados dan un movimiento inestable.

    El punch-in se apaga solo cuando hay vaiven; ya no hace falta que el ojo
    registre el corte, porque el encuadre nunca esta quieto.
    """
    import inspect
    from core import pipeline
    src = inspect.getsource(pipeline.Trabajo._plan_clip)
    assert "not zoom.NIVELES.get(self.nivel_zoom)" in src


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    fallos = 0
    for n, f in fns:
        try:
            f()
            print(f"  OK    {n}")
        except Exception:
            fallos += 1
            print(f"  FALLA {n}")
            traceback.print_exc()
    print(f"\n{len(fns)-fallos}/{len(fns)} tests pasaron")
    sys.exit(1 if fallos else 0)
