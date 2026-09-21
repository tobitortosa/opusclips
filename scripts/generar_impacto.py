# -*- coding: utf-8 -*-
"""Genera assets/impacto.wav: el golpe que suena en el corte del cold open.

Se corre una sola vez; el .wav queda versionado. Esta aca para que el sonido se
pueda volver a fabricar o retocar sin depender de un archivo suelto que nadie
sabe de donde salio.

Son tres capas, que es como se arma cualquier impacto de trailer:

  1. SUB-BOOM  un barrido de 150 a 42 Hz que decae en 100 ms. Es el golpe en el
     pecho; sin esto suena a click y no a impacto.
  2. CUERPO    ruido filtrado pasa-bajos, cortisimo (160 ms). Da el "toc" que
     hace que el golpe se ubique en el tiempo con precision.
  3. COLA      un siseo agudo que ENTRA antes del golpe y crece. Es lo que hace
     que el corte se sienta anticipado en vez de repentino.

Al final una saturacion suave (tanh) para que pegue sin pasarse de pico.

    .venv\\Scripts\\python.exe scripts\\generar_impacto.py
"""
import wave
from pathlib import Path

import numpy as np

SR = 48000
DESTINO = Path(__file__).resolve().parent.parent / "assets" / "impacto.wav"


def _envolvente(n, ataque, caida, forma=2.0):
    t = np.arange(n) / SR
    return np.where(t < ataque, t / max(ataque, 1e-6),
                    ((1 - (t - ataque) / max(caida, 1e-6)).clip(0)) ** forma).clip(0)


def construir():
    rng = np.random.default_rng(7)
    n = int(0.55 * SR)
    t = np.arange(n) / SR

    # 1) sub-boom: la frecuencia cae exponencialmente de 150 a 42 Hz
    f = 150 * np.exp(-t / 0.10) + 42
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * _envolvente(n, 0.002, 0.52, 2.4) * 0.95

    # 2) cuerpo: ruido pasa-bajos (un polo, ~900 Hz) con caida muy rapida
    ruido, filtrado, acc = rng.standard_normal(n), np.zeros(n), 0.0
    for i in range(n):
        acc += (ruido[i] - acc) * 0.11
        filtrado[i] = acc
    cuerpo = filtrado / np.abs(filtrado).max() * _envolvente(n, 0.001, 0.16, 3.0) * 0.45

    # 3) cola de aire: entra 220 ms ANTES del golpe y crece hacia el
    na = int(0.22 * SR)
    aire, alto, acc = rng.standard_normal(na), np.zeros(na), 0.0
    for i in range(na):
        acc += (aire[i] - acc) * 0.35
        alto[i] = aire[i] - acc                      # pasa-altos = señal - pasa-bajos
    cola = alto / np.abs(alto).max() * (np.arange(na) / na) ** 2.2 * 0.22

    x = boom + cuerpo
    x[:na] += cola
    x = np.tanh(x * 1.35)
    return x / (np.abs(x).max() * 1.02)


def main():
    x = construir()
    estereo = (np.stack([x, x], 1) * 32767).astype("<i2").tobytes()
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(DESTINO), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(estereo)
    print(f"{DESTINO}  {len(estereo) / 4 / SR:.2f} s")


if __name__ == "__main__":
    main()
