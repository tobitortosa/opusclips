# -*- coding: utf-8 -*-
"""Composicion y exportacion del clip vertical 1080x1920 a 60 fps.

Layout (validado con el usuario): camara COMPLETA sin zoom en el tercio de
arriba, gameplay recortado al centro en los dos tercios de abajo.
Sin camara: el gameplay va centrado sobre un fondo desenfocado de si mismo.
"""
import shutil
from pathlib import Path

from . import ff, zoom
from .config import (ALTO, ANCHO, CADENA_AUDIO, CAM_ALTO, EQ_CAMARA, EQ_GAMEPLAY,
                     FFMPEG, FPS, FUENTES, GAME_ALTO, GAME_CROP_ANCHO, GAME_CROP_X,
                     IMPACTO, IMPACTO_ADELANTO, IMPACTO_VOLUMEN, X264_CRF, X264_PRESET)


def _filtro_con_camara():
    return (
        # camara: frame entero, sin recorte ni zoom -> ocupa el tercio de arriba
        f"[1:v]scale={ANCHO}:{CAM_ALTO}:flags=lanczos,{EQ_CAMARA},setsar=1[cam];"
        # gameplay: recorte centrado -> llena los dos tercios de abajo
        f"[0:v]crop={GAME_CROP_ANCHO}:1080:{GAME_CROP_X}:0,"
        f"scale={ANCHO}:{GAME_ALTO}:flags=lanczos,{EQ_GAMEPLAY},setsar=1[game];"
        f"[cam][game]vstack=inputs=2[stack];"
    )


def _filtro_sin_camara():
    # el 16:9 completo, centrado, sobre una version ampliada y desenfocada de si mismo
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]crop={GAME_CROP_ANCHO}:1080:{GAME_CROP_X}:0,scale={ANCHO}:{ALTO}:flags=bilinear,"
        f"gblur=sigma=42,eq=brightness=-0.16:saturation=0.75,setsar=1[fondo];"
        f"[fg]scale={ANCHO}:-2:flags=lanczos,{EQ_GAMEPLAY},setsar=1[frente];"
        f"[fondo][frente]overlay=(W-w)/2:(H-h)/2[stack];"
    )


def _mezcla_impacto(entrada, salida, en):
    """Pega el golpe de audio justo en el corte del cold open al clip.

    El corte del cold open es el unico momento del clip donde el video cambia de
    contexto de golpe. Sin nada que lo acompañe en el audio se lee como un error
    de edicion; con el golpe se lee como un corte a proposito. Va ANTES de la
    cadena de audio para que el loudnorm lo mida junto con el resto y el clip
    entero siga saliendo a -14 LUFS.

    Se lee con `amovie` y ruta RELATIVA: ffmpeg corre con el cwd en la carpeta de
    trabajo, y en Windows una ruta absoluta le rompe el parseo del filtro, porque
    el ':' de la unidad se confunde con el separador de parametros. Es el mismo
    motivo por el que las fuentes se copian ahi.
    """
    ms = max(0, int((en - IMPACTO_ADELANTO) * 1000))
    return (f"amovie=impacto.wav,adelay={ms}|{ms}:all=1,volume={IMPACTO_VOLUMEN},"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[imp];"
            f"[{entrada}][imp]amix=inputs=2:duration=first:normalize=0[{salida}];")


def construir_filtro(ass_rel, con_camara, mapa=None, t0=0.0, punch_in=False,
                     zoom_gancho=None, impacto_en=None, nivel_zoom=None,
                     duracion=0.0, semilla=0):
    """`mapa` es un MapaTiempos si hay que sacar tiempos muertos, o None.

    Los cortes se aplican DESPUES de componer, sobre el video ya armado, y en el
    mismo filtergraph: una sola pasada de encoding, sin perdida extra de calidad.
    La cadena de audio (EQ, compresion, loudnorm) va al FINAL, sobre el audio ya
    pegado, para que el loudnorm mida el clip completo y no cada trozo suelto.

    Los saltos de zoom entran entre el concat y los subtitulos: sobre el video ya
    pegado -ahi el reloj ya es el del clip terminado, asi que un salto programado
    para el segundo 10 cae de verdad en el segundo 10- y antes del `ass`, para que
    el texto no salte de tamaño con la imagen.
    """
    base = _filtro_con_camara() if con_camara else _filtro_sin_camara()
    if mapa is not None and mapa.hay_cortes:
        golpe, fuente = "", "acat"
        if impacto_en:
            golpe = _mezcla_impacto("acat", "amez", impacto_en)
            fuente = "amez"
        saltos = zoom.filtro(nivel_zoom, duracion or mapa.duracion, ANCHO, ALTO,
                             CAM_ALTO if con_camara else 0, FPS, "vcat", "vzm", semilla)
        return (base +
                mapa.filtro_concat("stack", "0:a", "vcat", "acat", t0=t0,
                                   punch_in=punch_in, ancho=ANCHO, alto=ALTO,
                                   fps=FPS, zoom_primero=zoom_gancho) +
                golpe + saltos +
                f"[{'vzm' if saltos else 'vcat'}]ass={ass_rel}:fontsdir=fonts[vo];"
                f"[{fuente}]{CADENA_AUDIO}[ao]")
    saltos = zoom.filtro(nivel_zoom, duracion, ANCHO, ALTO,
                         CAM_ALTO if con_camara else 0, FPS, "stack", "vzm", semilla)
    return (base + saltos +
            f"[{'vzm' if saltos else 'stack'}]ass={ass_rel}:fontsdir=fonts[vo];"
            f"[0:a]{CADENA_AUDIO}[ao]")


def renderizar(pantalla, camara, offset_cam, inicio, dur, ass, destino,
               cb=None, cancelado=None, crf=None, preset=None, mapa=None,
               punch_in=False, zoom_gancho=None, impacto_en=None, nivel_zoom=None,
               semilla=0):
    """Renderiza un clip.

    ffmpeg corre con el cwd en la carpeta del .ass y usa rutas RELATIVAS para
    los subtitulos y las fuentes: libass en Windows no soporta rutas absolutas
    (se le atraganta el ':' de 'C:\\'). La salida si va por ruta absoluta, asi
    la carpeta de clips queda limpia y sin archivos intermedios.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    ass = Path(ass)
    trabajo = ass.parent

    # libass busca la fuente en ./fonts, relativo al cwd
    fonts = trabajo / "fonts"
    fonts.mkdir(exist_ok=True)
    for ttf in FUENTES.glob("*.ttf"):
        d = fonts / ttf.name
        if not d.exists() or d.stat().st_size != ttf.stat().st_size:
            shutil.copy2(ttf, d)

    # el golpe del cold open, tambien por ruta relativa (ver _mezcla_impacto)
    if impacto_en and IMPACTO.exists():
        d = trabajo / "impacto.wav"
        if not d.exists() or d.stat().st_size != IMPACTO.stat().st_size:
            shutil.copy2(IMPACTO, d)
    else:
        impacto_en = None

    con_cam = bool(camara)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-ss", f"{inicio:.3f}", "-t", f"{dur:.3f}", "-i", str(pantalla)]
    if con_cam:
        cmd += ["-ss", f"{inicio + offset_cam:.3f}", "-t", f"{dur:.3f}", "-i", str(camara)]

    # El filtergraph se pasa por ARCHIVO (sintaxis "-/opcion archivo"), no por
    # linea de comandos. Con muchos cortes -el modo "sin respiro" puede hacer 150
    # trozos, unos 49.000 caracteres- se supera el limite de 32.767 de
    # CreateProcess en Windows y el render ni arranca: falla con "El nombre del
    # archivo o la extension es demasiado largo".
    # Ojo: `-filter_complex_script` ya no existe en ffmpeg 8; la forma actual es
    # `-/filter_complex`, verificada contra el binario que trae el proyecto.
    filtro = construir_filtro(ass.name, con_cam, mapa, t0=inicio, punch_in=punch_in,
                              zoom_gancho=zoom_gancho, impacto_en=impacto_en,
                              nivel_zoom=nivel_zoom, semilla=semilla,
                              duracion=mapa.duracion if mapa is not None else dur)
    f_filtro = trabajo / f"{destino.stem}.filtro"
    f_filtro.write_text(filtro, encoding="utf-8")

    cmd += [
        "-/filter_complex", f_filtro.name,
        "-map", "[vo]", "-map", "[ao]",
        "-c:v", "libx264", "-crf", str(crf or X264_CRF), "-preset", preset or X264_PRESET,
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
        "-r", str(FPS), "-g", str(FPS * 2), "-bf", "3",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", "-y", str(destino.resolve()),
    ]
    ok, err = ff.correr_con_progreso(cmd, dur, cb=cb, cancelado=cancelado, cwd=trabajo)
    if not ok:
        raise RuntimeError(err[-600:] or "ffmpeg fallo sin mensaje")
    return destino


def miniatura(clip, destino, t=1.0):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
           "-i", str(clip), "-frames:v", "1", "-vf", "scale=270:-1",
           "-q:v", "4", "-y", str(destino)]
    ff._correr(cmd)
    return destino
