# -*- coding: utf-8 -*-
"""Analisis de audio: deteccion de voz (VAD) y densidad de habla.

Hallazgo que justifica todo este modulo: el audio del stream es un mix
(voz + Minecraft), asi que detectar "silencio" por VOLUMEN es incorrecto.
Medido sobre este stream: silencedetect a -35 dB decia 71.5% de silencio,
cuando el VAD neuronal mide 50.9% real. Por eso se usa VAD, no umbrales.
"""
import json
import wave

import numpy as np

RES = 10          # resolucion de la mascara de habla, en Hz


def leer_wav(ruta):
    with wave.open(str(ruta), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return x.astype(np.float32) / 32768.0, sr


def detectar_voz(wav, cb=None):
    """Tramos de voz con silero-vad. ~105x tiempo real en esta maquina."""
    import torch
    from silero_vad import load_silero_vad, get_speech_timestamps

    x, sr = leer_wav(wav)
    if cb:
        cb("Detectando donde hablas...", 0.1)
    modelo = load_silero_vad(onnx=False)
    tramos = get_speech_timestamps(
        torch.from_numpy(x), modelo, sampling_rate=sr,
        min_speech_duration_ms=250, min_silence_duration_ms=400,
        speech_pad_ms=150, return_seconds=True,
    )
    return [dict(a=round(t["start"], 3), b=round(t["end"], 3)) for t in tramos], len(x) / sr


def mascara_habla(tramos, duracion):
    m = np.zeros(int(duracion * RES) + 1, dtype=np.float32)
    for t in tramos:
        m[int(t["a"] * RES):int(t["b"] * RES)] = 1.0
    return m


def densidad(mascara, inicio, fin):
    a, b = int(inicio * RES), int(fin * RES)
    if b <= a:
        return 0.0
    return float(mascara[a:b].mean())


def ventanas_candidatas(mascara, duracion, largo=35.0, paso=5.0, minimo=0.62):
    """Zonas del stream donde ya se habla seguido. Filtra el tiempo muerto
    antes de gastar un solo token de LLM."""
    out = []
    t = 0.0
    while t + largo <= duracion:
        d = densidad(mascara, t, t + largo)
        if d >= minimo:
            out.append(dict(inicio=round(t, 2), fin=round(t + largo, 2), densidad=round(d, 4)))
        t += paso
    return out


def fusionar(ventanas, hueco=10.0):
    """Une ventanas solapadas o pegadas en zonas continuas."""
    if not ventanas:
        return []
    ventanas = sorted(ventanas, key=lambda v: v["inicio"])
    out = [dict(ventanas[0])]
    for v in ventanas[1:]:
        if v["inicio"] - out[-1]["fin"] <= hueco:
            out[-1]["fin"] = max(out[-1]["fin"], v["fin"])
            out[-1]["densidad"] = max(out[-1]["densidad"], v["densidad"])
        else:
            out.append(dict(v))
    return out


def energia(wav, res=RES):
    """Curva de energia en dB, para detectar gritos y reacciones."""
    x, sr = leer_wav(wav)
    hop = max(1, sr // res)
    n = len(x) // hop
    r = np.sqrt(np.maximum(np.mean(x[:n * hop].reshape(n, hop) ** 2, axis=1), 1e-12))
    return 20 * np.log10(r)


def picos_energia(db, mascara, duracion, n=40, separacion=20.0):
    """Momentos donde la voz sube marcadamente sobre su nivel habitual."""
    k = min(len(db), len(mascara))
    db, mascara = db[:k], mascara[:k]
    suave = np.convolve(db, np.ones(20) / 20, mode="same")          # 2 s
    base = np.convolve(db, np.ones(1200) / 1200, mode="same")       # 2 min
    exceso = np.where(mascara > 0.5, suave - base, -99.0)
    orden = np.argsort(exceso)[::-1]
    usados = np.zeros(k, bool)
    sep = int(separacion * RES)
    out = []
    for i in orden:
        if exceso[i] < 2.0 or usados[max(0, i - sep):i + sep].any():
            continue
        out.append(dict(t=round(i / RES, 2), exceso=round(float(exceso[i]), 2)))
        usados[max(0, i - sep):i + sep] = True
        if len(out) >= n:
            break
    return sorted(out, key=lambda p: p["t"])
