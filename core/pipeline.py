# -*- coding: utf-8 -*-
"""Orquestacion: de los archivos crudos a los clips terminados.

Cada etapa guarda su resultado en trabajo/<proyecto>/. Si algo falla o se
cancela, al volver a correr se reusa lo ya hecho en vez de empezar de cero
(transcribir de nuevo son minutos tirados).
"""
import json
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import asr, audio, ff, gancho, momentos, render, silencios, subtitulos, sync, zoom
from .config import (CLIP_MAX, DENSIDAD_MINIMA, DURACION_MINIMA_FINAL, SALIDA, TRABAJO)

# Version del formato del cold open. Si sube, los ganchos guardados se recalculan
# en vez de reusarse: es lo que evita que un proyecto viejo se quede para siempre
# con ganchos del formato anterior.
VERSION_GANCHO = 2


def _gancho_de(clip):
    """El cold open del clip, o None si no hay uno del formato actual.

    Hay que comprobar el TIPO, no solo la version: en el formato viejo
    `momentos.py` devolvia un campo `gancho` que era un string (la frase de
    arranque), y un proyecto guardado de esa epoca hacia explotar todo lo que
    esperaba un dict.
    """
    g = clip.get("gancho")
    if isinstance(g, dict) and g.get("version") == VERSION_GANCHO:
        return g
    return None

ETAPAS = [
    ("revisar", "Revisando los archivos", 0.02),
    ("sincronizar", "Sincronizando camara", 0.06),
    ("audio", "Extrayendo audio", 0.10),
    ("voz", "Detectando donde hablas", 0.18),
    ("transcribir", "Transcribiendo", 0.45),
    ("elegir", "Eligiendo los mejores momentos", 0.55),
    ("renderizar", "Generando los clips", 1.00),
]


class Trabajo:
    def __init__(self, id_, pantalla, camara=None, n_clips=10, estilo="anton",
                 cortar_silencios=True, nivel_silencio=None, gancho=True,
                 nivel_zoom=None):
        self.id = id_
        self.pantalla = str(pantalla)
        self.camara = str(camara) if camara else None
        self.n_clips = int(n_clips)
        self.estilo = estilo
        self.cortar_silencios = cortar_silencios
        self.nivel_silencio = nivel_silencio or silencios.NIVEL_DEFECTO
        self.gancho = gancho
        self.nivel_zoom = nivel_zoom or zoom.NIVEL_DEFECTO
        self.dir = TRABAJO / id_
        self.dir.mkdir(parents=True, exist_ok=True)
        self.salida = SALIDA / id_
        self.salida.mkdir(parents=True, exist_ok=True)
        self._cancelar = threading.Event()
        self.estado = self._cargar() or dict(
            id=id_, creado=datetime.now().isoformat(timespec="seconds"),
            pantalla=self.pantalla, camara=self.camara, n_clips=self.n_clips,
            estilo=estilo, nivel_zoom=self.nivel_zoom,
            fase="listo", mensaje="Esperando", progreso=0.0,
            clips=[], error=None, info={}, uso_llm=None,
        )

    # ------------------------------------------------------------ estado
    @property
    def _f_estado(self):
        return self.dir / "estado.json"

    def _cargar(self):
        if self._f_estado.exists():
            try:
                return json.loads(self._f_estado.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def guardar(self):
        tmp = self._f_estado.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._f_estado)

    def _avisar(self, mensaje=None, prog=None, fase=None):
        if mensaje:
            self.estado["mensaje"] = mensaje
        if prog is not None:
            self.estado["progreso"] = round(max(0.0, min(1.0, prog)), 4)
        if fase:
            self.estado["fase"] = fase
        self.guardar()

    def cancelar(self):
        self._cancelar.set()

    @property
    def cancelado(self):
        return self._cancelar.is_set()

    def _chequear(self):
        if self.cancelado:
            raise Cancelado()

    # ------------------------------------------------------------ cache
    def _json(self, nombre, generar, mensaje=None):
        f = self.dir / nombre
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        if mensaje:
            self._avisar(mensaje)
        d = generar()
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return d

    # ------------------------------------------------------------ etapas
    def correr(self):
        try:
            self.estado["error"] = None
            self._avisar("Arrancando...", 0.0, "corriendo")
            self._revisar()
            self._sincronizar()
            self._analizar_audio()
            self._transcribir()
            self._elegir()
            self._renderizar()
            self._avisar(f"Listo: {len(self.estado['clips'])} clips", 1.0, "terminado")
        except Cancelado:
            self._avisar("Cancelado", None, "cancelado")
        except Exception as e:
            self.estado["error"] = f"{type(e).__name__}: {e}"
            self.estado["traza"] = traceback.format_exc()[-3000:]
            self._avisar(f"Error: {e}", None, "error")
        finally:
            asr.liberar()

    def _revisar(self):
        self._chequear()
        self._avisar("Revisando los archivos...", 0.01)
        info = dict(pantalla=ff.sondear(self.pantalla))
        if self.camara:
            info["camara"] = ff.sondear(self.camara)
            if not info["camara"]["tiene_audio"]:
                info["camara_sin_audio"] = True
            dp, dc = info["pantalla"]["duracion"], info["camara"]["duracion"]
            if abs(dp - dc) > 30:
                info["aviso"] = (f"Los dos archivos duran muy distinto "
                                 f"({dp/60:.0f} vs {dc/60:.0f} min). Reviso igual, "
                                 f"pero fijate que sean del mismo stream.")
        if info["pantalla"]["vfr"]:
            info["aviso_vfr"] = "El video tiene fps variable; puede haber leve deriva."
        self.estado["info"] = info
        self.estado["duracion"] = info["pantalla"]["duracion"]
        self._avisar(f"{info['pantalla']['duracion']/60:.0f} minutos de stream", 0.02)

    def _sincronizar(self):
        self._chequear()
        if not self.camara:
            self.estado["offset_camara"] = 0.0
            return
        d = self._json("sync.json", lambda: sync.medir_desfase(
            self.pantalla, self.camara, self.estado["duracion"],
            cb=lambda m, p: self._avisar(m, 0.02 + 0.04 * p)))
        self.estado["offset_camara"] = d["offset"]
        self.estado["sync"] = d
        signo = "adelantada" if d["offset"] > 0 else "atrasada"
        self._avisar(f"Camara {signo} {abs(d['offset'])*1000:.0f} ms", 0.06)

    def _analizar_audio(self):
        self._chequear()
        wav = self.dir / "audio.wav"
        if not wav.exists():
            self._avisar("Extrayendo audio...", 0.07)
            ff.extraer_wav(self.pantalla, wav)
        self._chequear()

        d = self._json("voz.json", lambda: _vad(wav, self._avisar),
                       "Detectando donde hablas...")
        self.estado["habla_pct"] = d["habla_pct"]
        self._avisar(f"Hablas el {d['habla_pct']:.0f}% del stream", 0.18)

    def _transcribir(self):
        self._chequear()
        f = self.dir / "transcripcion.json"
        if f.exists():
            self.estado["n_palabras"] = json.loads(f.read_text(encoding="utf-8"))["n_palabras"]
            self._avisar("Transcripcion ya hecha", 0.45)
            return
        t = asr.transcribir(
            self.dir / "audio.wav", self.estado["duracion"],
            cb=lambda m, p: (self._chequear(), self._avisar(m, 0.18 + 0.27 * p)))
        f.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
        self.estado["n_palabras"] = t["n_palabras"]
        self._avisar(f"{t['n_palabras']} palabras transcritas", 0.45)

    def _elegir(self):
        self._chequear()
        f = self.dir / "clips.json"
        rehacer = True
        if f.exists():
            prev = json.loads(f.read_text(encoding="utf-8"))
            if len(prev.get("clips", [])) >= self.n_clips:
                self.estado["clips"] = _recortar(prev["clips"], self.n_clips)
                self.estado["uso_llm"] = prev.get("uso")
                rehacer = False
        if rehacer:
            t = json.loads((self.dir / "transcripcion.json").read_text(encoding="utf-8"))
            v = json.loads((self.dir / "voz.json").read_text(encoding="utf-8"))
            mask = audio.mascara_habla(v["tramos"], v["duracion"])
            clips, uso = momentos.seleccionar(
                t, v["zonas"], v["picos"], n=self.n_clips, mascara=mask,
                cb=lambda m, p: self._avisar(m, p))
            f.write_text(json.dumps(dict(clips=clips, uso=uso), ensure_ascii=False),
                         encoding="utf-8")
            self.estado["clips"] = clips
            self.estado["uso_llm"] = uso
        for c in self.estado["clips"]:
            c.setdefault("estado", "pendiente")
        self._avisar(f"{len(self.estado['clips'])} momentos elegidos", 0.52)
        self._elegir_ganchos()

    def _elegir_ganchos(self):
        """El cold open de cada clip y su cartel, elegidos por Claude.

        Dos cosas que ya fallaron y por eso estan asi:

        - SE COMPRUEBA LA VERSION. Antes alcanzaba con que el clip tuviera
          cualquier cosa en `gancho` para no recalcular. Resultado: proyectos
          viejos se quedaron con ganchos del formato anterior -de 0,9 s, con el
          texto cortado al medio- y el selector nuevo no corria nunca.
        - NO SE CACHEA UN RESULTADO VACIO. Si la llamada falla, se avisa y se
          sigue sin gancho ESTA vez; antes se escribia `{}` en ganchos.json y ese
          stream quedaba sin cold open para siempre, en silencio.
        """
        if not self.gancho or not self.estado["clips"]:
            return
        if all(_gancho_de(c) for c in self.estado["clips"]):
            return
        self._chequear()
        f = self.dir / "ganchos.json"
        datos = None
        if f.exists():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                if d.get("version") == VERSION_GANCHO and d.get("ganchos"):
                    datos = d
            except Exception:
                datos = None
        if datos is None:
            t = json.loads((self.dir / "transcripcion.json").read_text(encoding="utf-8"))
            v = json.loads((self.dir / "voz.json").read_text(encoding="utf-8"))
            pcm, _ = audio.leer_wav(self.dir / "audio.wav")
            try:
                datos = gancho.elegir(self.estado["clips"], t["palabras"], v["tramos"], pcm,
                                      cb=lambda m, p: self._avisar(m, 0.53))
            except Exception as e:
                self.estado["aviso_gancho"] = f"No pude elegir los ganchos: {e}"
                self._avisar("Sigo sin cold open: " + str(e)[:120], 0.55)
                return
            if datos.get("ganchos"):
                datos["version"] = VERSION_GANCHO
                f.write_text(json.dumps(
                    dict(version=VERSION_GANCHO, ganchos=datos["ganchos"], uso=datos.get("uso")),
                    ensure_ascii=False), encoding="utf-8")
        self.estado.pop("aviso_gancho", None)
        g_todos = datos.get("ganchos") or {}
        for c in self.estado["clips"]:
            g = g_todos.get(str(c["n"])) or g_todos.get(c["n"])
            c["gancho"] = g if g else None
        self.estado["uso_gancho"] = datos.get("uso")
        n = sum(1 for c in self.estado["clips"] if c.get("gancho"))
        self._avisar(f"{n} de {len(self.estado['clips'])} clips con gancho", 0.55)

    # ------------------------------------------------------------ render
    def _material(self):
        """Todo lo que hace falta para componer un clip, cargado una sola vez."""
        if getattr(self, "_mat", None) is None:
            t = json.loads((self.dir / "transcripcion.json").read_text(encoding="utf-8"))
            v = json.loads((self.dir / "voz.json").read_text(encoding="utf-8"))
            pcm, _ = audio.leer_wav(self.dir / "audio.wav") if self.cortar_silencios else (None, 0)
            self._mat = (t["palabras"], v["tramos"], pcm)
        return self._mat

    def _plan_clip(self, c, palabras, tramos, pcm):
        """Arma el montaje de un clip: que tramos quedan, con cold open y todo.

        Devuelve (mapa, palabras_remapeadas, t0_subtitulos, punch_in, zoom_gancho,
        impacto_en). `mapa` es None si el clip va entero, sin cortes.
        """
        pal = [w for w in palabras if w["b"] > c["inicio"] and w["a"] < c["fin"]]
        if not self.cortar_silencios:
            return None, pal, c["inicio"], False, None, None

        # Si al cortar fuerte el clip queda demasiado corto para publicar, se
        # afloja un escalon y se vuelve a intentar. Asi el modo frenetico no
        # convierte un buen momento en un clip de 8 segundos.
        escalones = {"maximo": ["maximo", "frenetico", "normal"],
                     "frenetico": ["frenetico", "normal", "suave"],
                     "normal": ["normal", "suave"],
                     "suave": ["suave"]}.get(self.nivel_silencio, [self.nivel_silencio])
        m = informe = None
        for nivel in escalones:
            conservar, informe = silencios.planificar(
                pal, tramos, pcm, c["inicio"], c["fin"], nivel=nivel)
            m = silencios.MapaTiempos(conservar)
            informe["nivel"] = nivel
            if m.duracion >= DURACION_MINIMA_FINAL or nivel == escalones[-1]:
                break
        c["silencios"] = informe
        conservar = list(m.tramos)

        # COLD OPEN: el pedacito mas llamativo, pegado al principio. Lo eligio
        # Claude en la etapa anterior, de un menu de fragmentos ya recortados.
        zoom_gancho = impacto_en = None
        g = _gancho_de(c)
        if self.gancho and g and len(conservar) > 1:
            conservar = [(g["desde"], g["hasta"])] + conservar
            zoom_gancho = gancho.ZOOM_GANCHO
            impacto_en = round(g["hasta"] - g["desde"], 3)

        m = silencios.MapaTiempos(conservar)
        if not m.hay_cortes:
            return None, pal, c["inicio"], False, None, None
        # El punch-in da un escalon fijo por trozo; el vaiven mueve el encuadre
        # todo el tiempo. Encimados los dos zooms se MULTIPLICAN (1,12 x 1,075 =
        # 1,20 en el pico) y el movimiento se vuelve inestable, asi que cuando
        # hay vaiven el punch-in se apaga: ya no hace falta que el ojo registre
        # el corte, porque el encuadre nunca esta quieto.
        punch = (not zoom.NIVELES.get(self.nivel_zoom)) and bool(
            silencios.NIVELES.get(informe.get("nivel", self.nivel_silencio),
                                  {}).get("punch_in"))
        c["duracion_final"] = round(m.duracion, 2)
        return m, m.mapear_palabras(pal), 0.0, punch, zoom_gancho, impacto_en

    def _render_clip(self, c, cues=None, cb=None):
        """Compone y exporta UN clip. Lo usan el render normal y el rehacer.

        Van por el mismo camino a proposito: antes `rehacer_clip` re-renderizaba
        el clip crudo, asi que corregir una palabra del subtitulo te devolvia un
        clip sin cold open, sin corte de silencios y sin punch-in -otro video-.
        """
        palabras, tramos, pcm = self._material()
        mapa, pal, t0_sub, punch, zoom_g, impacto = self._plan_clip(c, palabras, tramos, pcm)

        if cues is not None:
            c["cues"] = cues
        cues = c.get("cues") or subtitulos.armar_cues(pal, self.estilo)
        c["cues"] = cues

        g = _gancho_de(c) or {}
        ass = self.dir / f"clip_{c['n']:02d}.ass"
        subtitulos.escribir_ass(cues, ass, self.estilo, t0=t0_sub,
                                cartel=g.get("cartel") if mapa is not None else None,
                                cartel_hasta=impacto or 0.0)

        destino = self.salida / c["archivo"]
        render.renderizar(
            self.pantalla, self.camara, self.estado.get("offset_camara", 0.0),
            c["inicio"], c["duracion"], ass, destino, mapa=mapa, punch_in=punch,
            zoom_gancho=zoom_g, impacto_en=impacto, nivel_zoom=self.nivel_zoom,
            semilla=c["n"], cb=cb, cancelado=lambda: self.cancelado)
        render.miniatura(destino, self.dir / f"{destino.stem}.jpg")
        c["estado"] = "listo"
        c["ruta"] = str(destino)
        c["peso_mb"] = round(destino.stat().st_size / 1024 ** 2, 1)
        return c

    def _renderizar(self):
        clips = self.estado["clips"]
        n = len(clips) or 1
        for i, c in enumerate(clips):
            self._chequear()
            base, tramo = 0.55, 0.45 / n
            if c.get("estado") == "listo" and (self.salida / c["archivo"]).exists():
                continue
            self._avisar(f"Clip {i+1} de {n}: {c.get('titulo','')}", base + tramo * i)
            try:
                self._render_clip(c, cb=lambda p, i=i: self._avisar(None, base + tramo * (i + p)))
            except Cancelado:
                raise
            except Exception as e:
                # un clip que falla no tira abajo los otros
                c["estado"] = "error"
                c["error"] = str(e)[:400]
            self.guardar()

    def rehacer_clip(self, n, cues=None):
        """Re-renderiza un solo clip, opcionalmente con los subtitulos editados."""
        c = next((x for x in self.estado["clips"] if x["n"] == n), None)
        if c is None:
            raise ValueError(f"No existe el clip {n}")
        self._avisar(f"Rehaciendo el clip {n}...", None, "corriendo")
        self._render_clip(c, cues=cues)
        self._avisar("Clip actualizado", None, "terminado")
        return c



class Cancelado(Exception):
    pass


def _vad(wav, avisar):
    tramos, dur = audio.detectar_voz(wav, cb=lambda m, p: avisar(m, 0.10 + 0.06 * p))
    mask = audio.mascara_habla(tramos, dur)
    vent = audio.ventanas_candidatas(mask, dur, minimo=DENSIDAD_MINIMA)
    zonas = audio.fusionar(vent)
    db = audio.energia(wav)
    picos = audio.picos_energia(db, mask, dur)
    return dict(duracion=dur, tramos=tramos, zonas=zonas, picos=picos,
                habla_pct=round(100 * float(mask.mean()), 1))


def _recortar(clips, n):
    orden = sorted(clips, key=lambda c: -c.get("puntaje", 0))[:n]
    orden.sort(key=lambda c: c["inicio"])
    return orden
