# -*- coding: utf-8 -*-
"""Envoltorio de ffmpeg/ffprobe: sondeo, extraccion de audio y ejecucion con progreso."""
import json
import re
import subprocess
import sys
from pathlib import Path

from .config import FFMPEG, FFPROBE

CREAR_SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0


def _correr(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=CREAR_SIN_VENTANA, **kw)


def sondear(ruta):
    """Devuelve metadatos del archivo: duracion, video y audio."""
    r = _correr([FFPROBE, "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", str(ruta)])
    if r.returncode != 0:
        raise RuntimeError(f"No pude leer el archivo:\n{r.stderr[:500]}")
    d = json.loads(r.stdout)
    vid = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    aud = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if vid is None:
        raise RuntimeError("El archivo no tiene pista de video.")

    def frac(x):
        try:
            a, b = x.split("/")
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0

    r_fps, avg_fps = frac(vid.get("r_frame_rate", "0/1")), frac(vid.get("avg_frame_rate", "0/1"))
    return dict(
        ruta=str(ruta),
        duracion=float(d["format"].get("duration", 0)),
        ancho=int(vid["width"]), alto=int(vid["height"]),
        fps=r_fps or avg_fps,
        vfr=bool(r_fps and avg_fps and abs(r_fps - avg_fps) > 0.02),
        codec=vid.get("codec_name"),
        tiene_audio=aud is not None,
        canales=int(aud["channels"]) if aud else 0,
        sample_rate=int(aud["sample_rate"]) if aud else 0,
        bitrate=int(d["format"].get("bit_rate", 0) or 0),
    )


def extraer_wav(entrada, salida, sr=16000, inicio=None, dur=None):
    """Audio mono PCM para analisis. Rapidisimo incluso en archivos de 12 GB."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if inicio is not None:
        cmd += ["-ss", f"{inicio:.3f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", str(entrada), "-vn", "-ac", "1", "-ar", str(sr),
            "-c:a", "pcm_s16le", "-y", str(salida)]
    r = _correr(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"Fallo extrayendo audio:\n{r.stderr[:500]}")
    return Path(salida)


_RE_TIME = re.compile(r"out_time_ms=(\d+)")


def correr_con_progreso(cmd, dur_total, cb=None, cancelado=None, cwd=None):
    """Ejecuta ffmpeg informando avance 0..1. Devuelve (ok, stderr).

    `cwd` importa: el filtro `ass=` y `fontsdir=` usan rutas RELATIVAS a proposito,
    porque libass en Windows no digiere rutas absolutas con ':' adentro.
    """
    cmd = list(cmd) + ["-progress", "pipe:1", "-nostats"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         cwd=str(cwd) if cwd else None,
                         creationflags=CREAR_SIN_VENTANA)
    err = []
    try:
        for linea in p.stdout:
            if cancelado is not None and cancelado():
                p.kill()
                return False, "cancelado"
            m = _RE_TIME.search(linea)
            if m and cb and dur_total > 0:
                cb(min(1.0, int(m.group(1)) / 1e6 / dur_total))
    finally:
        try:
            err = (p.stderr.read() or "")[-2000:]
        except Exception:
            err = ""
        p.wait()
    return p.returncode == 0, err
