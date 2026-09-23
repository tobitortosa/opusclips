# -*- coding: utf-8 -*-
"""Tests de los memes: colocacion, franjas y filtergraph.

Todo lo de aca falla EN SILENCIO. El clip sale, pesa bien y se reproduce; lo
que se rompe es que el meme cae medio segundo tarde, o le tapa la cara, o el
sonido suena cuando el sticker ya se fue. Nada de eso tira una excepcion.

Correr con:  .venv\\Scripts\\python.exe -m pytest tests -q
o directo:   .venv\\Scripts\\python.exe tests\\test_memes.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import memes
from core.config import ALTO, ANCHO, CAM_ALTO

# Donde vive el subtitulo, medido del layout: es SIEMPRE una sola linea.
SUB_ARRIBA, SUB_ABAJO = 1176, 1324


def _clip(dur=30.0, desde=0.0, n=1):
    return dict(n=n, titulo="x", duracion_final=dur, desde=desde, guion="")


def _lib():
    return {k: dict(v, id=k) for k, v in memes.CATALOGO.items()}


# ------------------------------------------------------- la biblioteca
def test_todos_los_memes_del_catalogo_existen_en_el_disco():
    lib = memes.biblioteca()
    faltan = sorted(set(memes.CATALOGO) - set(lib))
    assert not faltan, f"sin archivo: {faltan}"


def test_todos_los_sonidos_del_catalogo_existen_en_el_disco():
    snd = memes.sonidos()
    faltan = sorted(set(memes.SONIDOS) - set(snd))
    assert not faltan, f"sin archivo: {faltan}"


def test_cada_meme_tiene_sonido_propio_y_le_pega():
    """Ninguno puede salir mudo, y el sonido tiene que ser del tono del meme:
    una musica tetrica debajo de una cara feliz no da risa, da confusion."""
    for k, m in memes.CATALOGO.items():
        assert m["sonido"] in memes.SONIDOS, f"{k} sin sonido propio"
        assert m["tonos"] and set(m["tonos"]) <= set(memes.TONOS), k
        assert memes.SONIDOS[m["sonido"]]["tono"] in m["tonos"], \
            f"{k}: su propio sonido no le pega"


def test_cada_sonido_tiene_un_tono_conocido():
    for k, x in memes.SONIDOS.items():
        assert x["tono"] in memes.TONOS, k


def test_todo_meme_tiene_al_menos_un_sonido_que_le_queda():
    snd = memes.sonidos()
    for k, m in memes.biblioteca().items():
        assert memes.sonidos_de(m, snd), k


def test_ningun_recorte_de_sonido_esta_al_reves_ni_es_larguisimo():
    for k, s in memes.SONIDOS.items():
        assert 0 <= s["desde"] < s["hasta"], k
        assert s["hasta"] - s["desde"] <= 3.2, f"{k}: taparia la voz"


def test_no_hay_carpetas_de_stickers_sin_ficha():
    """Si se agrega una carpeta nueva, hay que escribirle la ficha: sin ficha el
    modelo no la puede usar y el meme queda muerto en el disco."""
    assert memes.faltantes() == []


# -------------------------------------------------------- las franjas
def _casos():
    """Todas las combinaciones que pueden salir: estilo x camara x posicion x
    tamaño x forma del meme x empujon."""
    for estilo in memes.ESTILOS:
        for con_camara in (True, False):
            franjas = memes._franjas(con_camara, estilo)
            for pos in memes.POSICIONES:
                for tam in memes.TAMANOS:
                    for ratio in (1.0, 0.75, 1.35):   # cuadrado, apaisado, alto
                        m = dict(posicion=pos, tamano=tam, _ratio=ratio)
                        for i in range(6):
                            yield (dict(estilo=estilo, camara=con_camara, pos=pos,
                                        tam=tam, ratio=ratio),
                                   memes.caja(m, i, franjas, estilo))


def test_el_meme_nunca_le_tapa_la_cara():
    """Lo unico que el usuario pidio que no pasara NUNCA, en los dos estilos.

    Se comprueba contra el pico del rebote de entrada y no contra el tamaño
    asentado: medido, un sticker de 440 px llegaba a 546 px en el primer frame
    y se metia 12 px dentro de la webcam. Dura dos frames, pero se ve.
    """
    for caso, (cx, cy, w, h) in _casos():
        techo = CAM_ALTO if caso["camara"] else 0
        pico = h * (1 + memes.ESTILOS[caso["estilo"]]["pop"])
        assert cy - pico / 2 >= techo - 0.5, (caso, cy, h)


def test_el_meme_nunca_se_sale_del_cuadro():
    for caso, (cx, cy, w, h) in _casos():
        e = memes.ESTILOS[caso["estilo"]]
        pw, ph = w * (1 + e["pop"]), h * (1 + e["pop"])
        assert cy + ph / 2 <= ALTO + 0.5, (caso, cy, h)
        assert cx - pw / 2 >= -e["sangrado"] - 0.5, (caso, cx, w)
        assert cx + pw / 2 <= ANCHO + e["sangrado"] + 0.5, (caso, cx, w)


def test_el_sticker_ademas_esquiva_los_subtitulos():
    """Solo el estilo `sticker`: el `crudo` los tapa a proposito."""
    for caso, (cx, cy, w, h) in _casos():
        if not memes.ESTILOS[caso["estilo"]]["respeta_subtitulos"]:
            continue
        pico = h * (1 + memes.ESTILOS[caso["estilo"]]["pop"])
        arriba, abajo = cy - pico / 2, cy + pico / 2
        assert abajo <= SUB_ARRIBA + 0.5 or arriba >= SUB_ABAJO - 0.5, (caso, arriba, abajo)


def test_el_crudo_es_mucho_mas_grande_que_el_sticker():
    """Es la razon de ser del estilo: que tape el gameplay entero."""
    for tam in memes.TAMANOS:
        assert (memes.ESTILOS["crudo"]["tamanos"][tam]
                > 2 * memes.ESTILOS["sticker"]["tamanos"][tam]), tam
    assert memes.ESTILOS["crudo"]["tamanos"]["grande"] >= ANCHO


def test_las_seis_posiciones_existen_en_las_franjas_y_las_columnas():
    for estilo in memes.ESTILOS:
        for p in memes.POSICIONES:
            banda, col = p.split("-")
            assert banda in memes._franjas(True, estilo)
            assert col in memes.COLUMNAS


# --------------------------------------------------------- resolver()
def test_descarta_los_memes_que_caen_fuera_del_clip():
    cfg = memes.NIVELES["extremo"]
    plan = memes.resolver([
        dict(t=-2.0, dur=1.2, meme="locura", posicion="arriba-izq",
             tamano="mediano", sonido=None),
        dict(t=29.9, dur=1.2, meme="robot_shock", posicion="abajo-izq",
             tamano="mediano", sonido=None),
        dict(t=10.0, dur=1.2, meme="perro_cocinado", posicion="abajo-der",
             tamano="mediano", sonido=None),
    ], _clip(30.0), cfg, _lib(), memes.sonidos())
    assert [m["meme"] for m in plan] == ["perro_cocinado"]


def test_no_pone_memes_encima_del_cartel_del_cold_open():
    """Los primeros segundos son el adelanto y ya tienen un cartel gigante."""
    cfg = memes.NIVELES["extremo"]
    plan = memes.resolver([
        dict(t=1.5, dur=1.0, meme="locura", posicion="arriba-izq",
             tamano="chico", sonido=None),
        dict(t=4.0, dur=1.0, meme="robot_shock", posicion="abajo-izq",
             tamano="chico", sonido=None),
    ], _clip(30.0, desde=2.6), cfg, _lib(), memes.sonidos())
    assert [m["meme"] for m in plan] == ["robot_shock"]


def test_respeta_el_tope_y_la_separacion_del_nivel():
    ids = list(memes.CATALOGO)
    crudos = [dict(t=1.0 + i * 0.5, dur=1.0, meme=ids[i % len(ids)],
                   posicion="arriba-izq", tamano="grande", sonido=None)
              for i in range(12)]
    for nivel in ("poco", "medio", "extremo"):
        cfg = memes.NIVELES[nivel]
        plan = memes.resolver(crudos, _clip(60.0), cfg, _lib(), memes.sonidos())
        assert len(plan) <= cfg["maximo"], nivel
        for a, b in zip(plan, plan[1:]):
            assert b["t"] - a["t"] >= cfg["separacion"] - 1e-9, nivel


def test_no_repite_el_mismo_meme_dentro_de_un_clip():
    crudos = [dict(t=2.0 + i * 3.0, dur=1.0, meme="gato_burlon",
                   posicion="abajo-izq", tamano="chico", sonido=None)
              for i in range(5)]
    for nivel in ("poco", "medio"):
        plan = memes.resolver(crudos, _clip(40.0), memes.NIVELES[nivel],
                              _lib(), memes.sonidos())
        assert len(plan) == 1, nivel


def test_en_extremo_se_puede_repetir_un_meme_si_paso_rato():
    """El repertorio es de doce y extremo pide mas memes que memes distintos
    hay; lo que no puede pasar es que el mismo aparezca dos veces seguidas."""
    cfg = memes.NIVELES["extremo"]
    crudos = [dict(t=2.0 + i * 3.0, dur=1.0, meme="gato_burlon",
                   posicion="abajo-izq", tamano="chico", sonido=None)
              for i in range(8)]
    plan = memes.resolver(crudos, _clip(40.0), cfg, _lib(), memes.sonidos())
    assert len(plan) > 1
    for a, b in zip(plan, plan[1:]):
        assert b["t"] - a["t"] >= cfg["repetir_tras"] - 1e-9


def test_no_deja_dos_seguidos_en_la_misma_posicion():
    cfg = memes.NIVELES["extremo"]
    ids = list(memes.CATALOGO)[:6]
    crudos = [dict(t=2.0 + i * 2.0, dur=1.0, meme=ids[i], posicion="abajo-der",
                   tamano="chico", sonido=None) for i in range(6)]
    plan = memes.resolver(crudos, _clip(40.0), cfg, _lib(), memes.sonidos())
    assert len(plan) == 6
    for a, b in zip(plan, plan[1:]):
        assert a["posicion"] != b["posicion"]


def test_ningun_meme_sale_mudo():
    """Paso de verdad con un gato y no se registro. Si el modelo no elige
    sonido, o elige uno que no existe, va el propio del meme."""
    cfg = memes.NIVELES["extremo"]
    crudos = [dict(t=2.0 + i * 7.0, dur=1.0, meme=k, posicion="arriba-izq",
                   tamano="grande", sonido=None)
              for i, k in enumerate(list(memes.CATALOGO)[:5])]
    plan = memes.resolver(crudos, _clip(80.0), cfg, _lib(), memes.sonidos())
    assert plan
    for m in plan:
        assert m["sonido"] in memes.SONIDOS, m["meme"]


def test_un_sonido_fuera_de_tono_se_reemplaza():
    """Musica tetrica encima de una cara feliz: se cambia por uno que le pegue."""
    cfg = memes.NIVELES["extremo"]
    plan = memes.resolver([dict(t=5.0, dur=1.0, meme="gato_picaro",
                                posicion="arriba-izq", tamano="grande",
                                sonido="inquietante")],
                          _clip(30.0), cfg, _lib(), memes.sonidos())
    assert plan[0]["sonido"] != "inquietante"
    assert (memes.SONIDOS[plan[0]["sonido"]]["tono"]
            in memes.CATALOGO["gato_picaro"]["tonos"])


def test_un_sonido_que_si_le_pega_se_respeta():
    cfg = memes.NIVELES["extremo"]
    plan = memes.resolver([dict(t=5.0, dur=1.0, meme="perrito_asustado",
                                posicion="arriba-izq", tamano="grande",
                                sonido="inquietante")],   # tetrico sobre miedo: si
                          _clip(30.0), cfg, _lib(), memes.sonidos())
    assert plan[0]["sonido"] == "inquietante"


def test_limpia_la_posicion_y_el_tamano_inventados():
    cfg = memes.NIVELES["medio"]
    plan = memes.resolver([dict(t=5.0, dur=1.0, meme="locura",
                                posicion="al-medio", tamano="descomunal",
                                sonido="trombon_triste")],
                          _clip(30.0), cfg, _lib(), memes.sonidos())
    assert plan[0]["posicion"] in memes.POSICIONES
    assert plan[0]["tamano"] in memes.TAMANOS
    assert plan[0]["sonido"] in memes.SONIDOS


def test_el_sticker_nunca_sigue_en_pantalla_despues_del_final():
    cfg = memes.NIVELES["medio"]
    plan = memes.resolver([dict(t=28.5, dur=2.4, meme="locura",
                                posicion="arriba-izq", tamano="chico",
                                sonido=None)],
                          _clip(30.0), cfg, _lib(), memes.sonidos())
    assert plan and plan[0]["t"] + plan[0]["dur"] <= 30.0 + 1e-9


def test_cada_nivel_tiene_su_nota():
    for nivel, cfg in memes.NIVELES.items():
        if cfg is None:
            continue
        assert cfg["nota"].strip(), nivel
        assert 0 < cfg["cada"] and 0 < cfg["maximo"], nivel


def test_los_niveles_son_de_pocos_memes():
    """Se bajaron los tres: estaban altos y no quedaba escalon para abajo. El
    nivel por defecto tiene que dar dos o tres memes por clip, no nueve."""
    assert memes.NIVELES["poco"]["maximo"] <= 2
    assert memes.NIVELES["medio"]["maximo"] <= 3
    assert memes.NIVELES["extremo"]["maximo"] <= 6
    for a, b in (("poco", "medio"), ("medio", "extremo")):
        assert memes.NIVELES[a]["maximo"] < memes.NIVELES[b]["maximo"]
        assert memes.NIVELES[a]["cada"] > memes.NIVELES[b]["cada"]


def test_el_objetivo_por_clip_sale_de_la_duracion():
    """Se le pide un numero concreto por clip, no 'uno cada N segundos': con la
    consigna en segundos el modelo ponia la mitad de los que se le pedian."""
    assert "apuntá a unos 6 memes" in memes._bloque(_clip(40.0), memes.NIVELES["extremo"])
    assert "apuntá a unos 2 memes" in memes._bloque(_clip(40.0), memes.NIVELES["poco"])


# ------------------------------------------------------------ guion()
def test_el_guion_marca_las_reacciones_sin_palabras():
    pal = [dict(t="no", a=1.0, b=1.3), dict(t="queda", a=1.35, b=1.7),
           dict(t="nada", a=1.75, b=2.1), dict(t="bueno", a=5.0, b=5.4)]
    g = memes.guion(pal, [(3.0, 4.2)], 10.0)
    assert "reaccion sin palabras" in g
    assert "[3.0-4.2]" in g
    assert "no queda nada" in g


def test_el_guion_no_pasa_lineas_de_despues_del_final():
    pal = [dict(t="hola", a=1.0, b=1.4), dict(t="chau", a=40.0, b=40.4)]
    g = memes.guion(pal, [], 20.0)
    assert "hola" in g and "chau" not in g


# ------------------------------------------------------- filtergraph
def _plan_listo(**kw):
    """Un plan con los campos que deja `preparar_archivos`, sin tocar el disco."""
    base = dict(t=3.0, dur=1.4, meme="locura", posicion="arriba-der",
                tamano="grande", sonido=None, por_que="",
                _png="memes/locura_p5.png", _ratio=1.0)
    base.update(kw)
    return [base]


def test_la_fuente_del_sticker_esta_ACOTADA():
    """El bug que hacia que ffmpeg no terminara nunca.

    Con `loop=-1` el grafo no llega jamas al final: medido, un clip de prueba de
    3 segundos salia de 166 MB y seguia creciendo. Ademas el `scale` animado
    correria en todos los frames del clip y no solo en los que se ve.
    """
    f = memes.filtro_video(_plan_listo(), "v0", "vo", True, 30.0, 60)
    assert "loop=-1" not in f and "loop=loop=-1" not in f
    n = int(re.search(r"loop=loop=(\d+)", f).group(1))
    assert 60 <= n <= 60 * 2          # solo la ventana del sticker, no el clip
    assert "trim=duration=" in f
    assert "tpad=start_duration=3.000" in f


def test_el_sticker_se_ve_exactamente_en_su_ventana():
    f = memes.filtro_video(_plan_listo(t=4.25, dur=1.1), "v0", "vo", True, 30.0, 60)
    a, b = re.search(r"enable='between\(t,([\d.]+),([\d.]+)\)'", f).groups()
    assert float(a) == 4.25 and abs(float(b) - 5.35) < 1e-6


def test_el_sticker_no_sobrevive_al_final_del_clip():
    f = memes.filtro_video(_plan_listo(t=9.5, dur=2.0), "v0", "vo", True, 10.0, 60)
    b = float(re.search(r"enable='between\(t,[\d.]+,([\d.]+)\)'", f).group(1))
    assert b <= 10.0


def test_sin_memes_el_filtro_no_deja_rastro():
    for plan in (None, []):
        assert memes.filtro_video(plan, "v0", "vo", True, 30.0, 60) == ""
        assert memes.filtro_audio(plan, "a0", "ao") == ""


def test_el_sonido_arranca_cuando_aparece_el_sticker():
    plan = _plan_listo(t=7.25, dur=1.2, sonido="fahh",
                       _mp3="memes/snd_fahh.mp3", _corte=(0.88, 2.6))
    f = memes.filtro_audio(plan, "acat", "ao")
    assert "adelay=7250|7250:all=1" in f
    a, b = re.search(r"atrim=start=([\d.]+):end=([\d.]+)", f).groups()
    assert float(a) == 0.88
    # se recorta al tramo util del mp3 y no suena mucho despues de irse
    assert float(b) - float(a) <= 1.2 + 0.45 + 1e-9


def test_un_sonido_larguisimo_se_recorta():
    plan = _plan_listo(t=1.0, dur=0.8, sonido="cocinado",
                       _mp3="memes/snd_cocinado.mp3", _corte=(0.0, 3.0))
    f = memes.filtro_audio(plan, "acat", "ao")
    a, b = re.search(r"atrim=start=([\d.]+):end=([\d.]+)", f).groups()
    assert float(b) - float(a) < 3.0


def test_la_mezcla_cuenta_bien_las_entradas():
    plan = (_plan_listo(t=2.0, sonido="fahh", _mp3="memes/snd_fahh.mp3",
                        _corte=(0.88, 2.6))
            + _plan_listo(t=6.0, meme="robot_shock", sonido="ah",
                          _mp3="memes/snd_ah.mp3", _corte=(0.6, 2.3)))
    f = memes.filtro_audio(plan, "acat", "ao")
    assert "amix=inputs=3:" in f          # el audio del clip + los dos sonidos
    assert f.count("amovie=") == 2


def test_el_crudo_no_tiene_ninguna_animacion():
    """Es el punto del estilo: se ve MAL editado. Sin rebote y sin bamboleo el
    `scale` ademas no necesita recalcularse por frame, asi que sale mas barato
    que el prolijo."""
    f = memes.filtro_video(_plan_listo(), "v0", "vo", True, 30.0, 60, "crudo")
    assert "eval=frame" not in f
    assert "sin(" not in f
    g = memes.filtro_video(_plan_listo(), "v0", "vo", True, 30.0, 60, "sticker")
    assert "eval=frame" in g and "sin(" in g


def test_el_crudo_no_le_pone_marco_blanco_ni_esquinas(tmp_path):
    """La foto pelada. El marco blanco y las esquinas redondeadas son justo lo
    que hace que se vea 'bien editado', y eso le saca la gracia."""
    from PIL import Image
    origen = memes.biblioteca()["perro_cocinado"]["imagen"]
    crudo = tmp_path / "crudo.png"
    stick = tmp_path / "stick.png"
    memes.preparar(origen, crudo, "crudo")
    memes.preparar(origen, stick, "sticker")
    with Image.open(crudo) as im:
        assert im.convert("RGBA").getpixel((0, 0))[3] == 255      # esquina opaca
    with Image.open(stick) as im:
        assert im.convert("RGBA").getpixel((0, 0))[3] == 0        # sombra/esquina
    assert crudo.stat().st_size > 0


def test_mudo_deja_el_meme_pero_le_saca_el_sonido(tmp_path):
    """El plan NO se toca: el sonido elegido queda anotado igual. Por eso
    prender y apagar el mudo no obliga a volver a llamar al modelo, solo a
    volver a renderizar."""
    plan = [dict(t=3.0, dur=1.2, meme="perro_cocinado", posicion="abajo-der",
                 tamano="grande", sonido="cocinado", por_que="")]
    vivos = memes.preparar_archivos(plan, tmp_path, "crudo", mudo=True)
    assert len(vivos) == 1
    assert vivos[0]["_png"]                       # se sigue viendo
    assert "_mp3" not in vivos[0]                 # pero no suena
    assert vivos[0]["sonido"] == "cocinado"       # y el plan queda intacto
    assert memes.filtro_audio(vivos, "acat", "ao") == ""
    assert memes.filtro_video(vivos, "v0", "vo", True, 30.0, 60, "crudo") != ""
    assert not list((tmp_path / "memes").glob("*.mp3"))


def test_sin_mudo_si_copia_el_sonido(tmp_path):
    plan = [dict(t=3.0, dur=1.2, meme="perro_cocinado", posicion="abajo-der",
                 tamano="grande", sonido="cocinado", por_que="")]
    vivos = memes.preparar_archivos(plan, tmp_path, "crudo")
    assert vivos[0]["_mp3"]
    assert memes.filtro_audio(vivos, "acat", "ao") != ""


def test_el_zoom_no_arrastra_los_stickers():
    """Los overlays van DESPUES del zoom: si fueran antes, el salto de encuadre
    recortaria y agrandaria el sticker, y el meme se leeria como parte del
    gameplay en vez de como algo pegado encima."""
    from core.render import construir_filtro
    from core.silencios import MapaTiempos
    f = construir_filtro("x.ass", True, MapaTiempos([(0.0, 5.0), (7.0, 12.0)]),
                         nivel_zoom="mediano", duracion=10.0,
                         memes=_plan_listo())
    assert f.index("zoompan") < f.index("overlay=x=")
    assert f.index("overlay=x=") < f.index("ass=x.ass")


def test_los_sonidos_entran_antes_de_la_cadena_de_audio():
    """Para que el loudnorm los mida y el clip siga saliendo a -14 LUFS."""
    from core.render import construir_filtro
    from core.silencios import MapaTiempos
    plan = _plan_listo(sonido="fahh", _mp3="memes/snd_fahh.mp3", _corte=(0.88, 2.6))
    f = construir_filtro("x.ass", True, MapaTiempos([(0.0, 5.0), (7.0, 12.0)]),
                         duracion=10.0, memes=plan)
    assert f.index("amix=inputs=2") < f.index("loudnorm")
    assert "[amm]highpass" in f


# ------------------------------------------- la base de tiempo de los cues
def test_los_cues_de_otro_montaje_se_descartan():
    """El bug que dejaba clips SIN NINGUN SUBTITULO: los cues guardados podian
    estar en el reloj del stream y el clip renderizarse con el reloj del clip."""
    from core.pipeline import _cues_del_clip
    del_clip = [[dict(t="hola", a=0.2, b=0.6)], [dict(t="chau", a=9.0, b=9.4)]]
    del_stream = [[dict(t="hola", a=4494.0, b=4494.4)]]
    assert _cues_del_clip(del_clip, 30.0)
    assert not _cues_del_clip(del_stream, 30.0)
    assert not _cues_del_clip([], 30.0)
    assert not _cues_del_clip(None, 30.0)


def test_las_palabras_salen_siempre_en_el_reloj_del_clip():
    import inspect

    from core import pipeline
    src = inspect.getsource(pipeline.Trabajo._plan_clip)
    # ningun camino puede devolver ya el inicio del clip como t0 de subtitulos
    assert 'c["inicio"], False, None, None' not in src
    assert src.count("_correr(pal") == 2


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
