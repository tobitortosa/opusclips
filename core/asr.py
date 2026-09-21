# -*- coding: utf-8 -*-
"""Transcripcion con faster-whisper large-v3 en modo batched.

Medido en esta maquina (RTX 5070 Ti): 89x tiempo real -> un stream de 2h38m
se transcribe en 1.8 minutos. El modo secuencial tarda 23 min y large-v3-turbo
es mas rapido pero inventa palabras, asi que se usa large-v3 batched.
"""
import gc

from . import reparar
from .config import ASR_BATCH, ASR_MODELO, ASR_PROMPT, dlls_cuda

_modelo = None


def _cargar(nombre=None):
    global _modelo
    if _modelo is None:
        dlls_cuda()
        from faster_whisper import WhisperModel, BatchedInferencePipeline
        m = WhisperModel(nombre or ASR_MODELO, device="cuda", compute_type="float16")
        _modelo = (m, BatchedInferencePipeline(model=m))
    return _modelo


def liberar():
    global _modelo
    _modelo = None
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass


def transcribir(wav, duracion, cb=None, prompt=None):
    """Devuelve dict(duracion, segmentos, palabras). Cada palabra: t, a, b, p."""
    _, pipe = _cargar()
    if cb:
        cb("Transcribiendo el stream...", 0.05)

    segs, info = pipe.transcribe(
        str(wav), batch_size=ASR_BATCH, language="es", word_timestamps=True,
        initial_prompt=prompt or ASR_PROMPT, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=200),
    )

    segmentos, palabras = [], []
    for s in segs:
        ws = [dict(t=w.word.strip(), a=round(w.start, 3), b=round(w.end, 3),
                   p=round(w.probability, 3))
              for w in (s.words or []) if w.word.strip()]
        if not ws:
            continue
        segmentos.append(dict(a=round(s.start, 3), b=round(s.end, 3), texto=s.text.strip()))
        palabras.extend(ws)
        if cb and duracion:
            cb(f"Transcribiendo... {s.end/60:.0f} de {duracion/60:.0f} min",
               0.05 + 0.9 * min(1.0, s.end / duracion))

    # Whisper deja timestamps invalidos (duracion cero, palabras de 3 letras que
    # "duran" 14 s, solapes). Se reparan antes de guardar: el karaoke depende de esto.
    arreglos = reparar.reparar(palabras)

    return dict(duracion=duracion, idioma=getattr(info, "language", "es"),
                n_palabras=len(palabras), segmentos=segmentos, palabras=palabras,
                arreglos=arreglos)


def palabras_en(palabras, a, b):
    return [w for w in palabras if w["b"] > a and w["a"] < b]


def ajustar_a_palabras(palabras, a, b, margen=0.12):
    """Corre los limites del clip a fronteras reales de palabra, para que no
    empiece ni termine cortando una silaba al medio."""
    dentro = palabras_en(palabras, a, b)
    if not dentro:
        return a, b
    return max(0.0, dentro[0]["a"] - margen), dentro[-1]["b"] + margen
