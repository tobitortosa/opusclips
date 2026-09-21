# -*- coding: utf-8 -*-
"""Sincronizacion entre el archivo de pantalla y el de camara.

OBS arranca las dos grabaciones con unas decimas de diferencia. En el stream
de prueba el desfase medido fue de +283.31 ms, constante (drift 0.00 ms en
2.5 h). Sin corregirlo, todos los clips con camara salen con los labios
desincronizados. Se mide por correlacion cruzada del audio de ambos archivos.
"""
import tempfile
from pathlib import Path

import numpy as np

from . import ff
from .audio import leer_wav

SR = 16000
VENTANA = 60.0          # segundos de audio por sonda
MAX_LAG = 3.0           # busca el desfase dentro de +-3 s


def _lag(a, b, sr, max_lag=MAX_LAG):
    """Desfase en segundos entre dos señales, y que tan confiable es (0..1)."""
    n = min(len(a), len(b))
    if n < sr:
        return 0.0, 0.0
    a = a[:n] - a[:n].mean()
    b = b[:n] - b[:n].mean()
    N = 1 << int(np.ceil(np.log2(2 * n)))
    cc = np.fft.irfft(np.fft.rfft(a, N) * np.conj(np.fft.rfft(b, N)), N)
    m = int(sr * max_lag)
    cc = np.concatenate((cc[-m:], cc[:m + 1]))
    i = int(np.argmax(cc))
    norma = np.linalg.norm(a) * np.linalg.norm(b) + 1e-12
    return (i - m) / sr, float(cc.max() / norma)


def medir_desfase(pantalla, camara, duracion, cb=None):
    """Mide el desfase en varios puntos del stream y comprueba que no haya drift.

    Devuelve dict(offset, confianza, drift, puntos). El offset es cuanto hay
    que adelantar la camara: tiempo_camara = tiempo_pantalla + offset.
    """
    puntos = [p for p in (0.08, 0.35, 0.65, 0.92) if duracion * p + VENTANA < duracion]
    if not puntos:
        puntos = [0.0]

    tmp = Path(tempfile.mkdtemp(prefix="sync_"))
    medidas = []
    try:
        for i, p in enumerate(puntos):
            t = duracion * p
            if cb:
                cb(f"Sincronizando camara ({i + 1}/{len(puntos)})...", 0.2 + 0.6 * i / len(puntos))
            wa = ff.extraer_wav(pantalla, tmp / f"p{i}.wav", SR, t, VENTANA)
            wb = ff.extraer_wav(camara, tmp / f"c{i}.wav", SR, t, VENTANA)
            a, _ = leer_wav(wa)
            b, _ = leer_wav(wb)
            lag, conf = _lag(a, b, SR)
            medidas.append(dict(t=round(t, 1), offset=round(-lag, 5), confianza=round(conf, 4)))
    finally:
        for f in tmp.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            tmp.rmdir()
        except OSError:
            pass

    buenas = [m for m in medidas if m["confianza"] > 0.5]
    if not buenas:
        # Sin correlacion clara: probablemente son audios distintos. No inventamos nada.
        return dict(offset=0.0, confianza=0.0, drift=0.0, puntos=medidas,
                    nota="No pude correlacionar los audios; asumo que ya estan sincronizados.")

    offsets = [m["offset"] for m in buenas]
    offset = float(np.median(offsets))
    drift = float(max(offsets) - min(offsets))
    nota = ""
    if drift > 0.08:
        nota = (f"Ojo: el desfase varia {drift*1000:.0f} ms a lo largo del stream "
                f"(hay drift). Uso la mediana.")
    return dict(offset=round(offset, 5),
                confianza=round(float(np.mean([m["confianza"] for m in buenas])), 4),
                drift=round(drift, 5), puntos=medidas, nota=nota)
