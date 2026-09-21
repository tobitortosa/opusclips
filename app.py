# -*- coding: utf-8 -*-
"""Servidor local. Un solo proceso: sirve la UI y corre el pipeline."""
import json
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config
from core.pipeline import Trabajo

app = FastAPI(title="Maquina de clips")
TRABAJOS = {}
LOCK = threading.Lock()


# --------------------------------------------------------------- modelos
class NuevoTrabajo(BaseModel):
    pantalla: str
    camara: str | None = None
    n_clips: int = 10
    estilo: str = "anton"
    cortar_silencios: bool = True
    nivel_silencio: str = "maximo"
    gancho: bool = True


class Cues(BaseModel):
    cues: list


class Ruta(BaseModel):
    ruta: str


# --------------------------------------------------------------- utilidades
def _id_desde(ruta):
    s = Path(ruta).stem.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:60] or "stream")


def _buscar_pareja(pantalla):
    """Si el archivo se llama '... PANTALLASOLA.mp4', busca su 'CAMARASOLA.mp4'."""
    p = Path(pantalla)
    if not p.exists():
        return None
    nombre = p.name
    for a, b in (("PANTALLA", "CAMARA"), ("pantalla", "camara"),
                 ("SCREEN", "CAM"), ("screen", "cam"), ("GAMEPLAY", "CAMARA")):
        if a in nombre:
            cand = p.with_name(nombre.replace(a, b))
            if cand.exists():
                return str(cand)
    return None


def _videos_cerca():
    """Videos en la carpeta del proyecto y en las carpetas habituales."""
    vistos, out = set(), []
    carpetas = [config.RAIZ, Path.home() / "Videos", Path.home() / "Desktop",
                Path.home() / "Escritorio"]
    for c in carpetas:
        if not c.exists():
            continue
        try:
            for f in sorted(c.glob("*.mp4"), key=lambda x: -x.stat().st_mtime)[:25]:
                if f.resolve() in vistos:
                    continue
                vistos.add(f.resolve())
                out.append(dict(ruta=str(f), nombre=f.name, carpeta=str(c),
                                gb=round(f.stat().st_size / 1024 ** 3, 2)))
        except OSError:
            pass
    return out[:40]


# --------------------------------------------------------------- API
@app.get("/api/inicio")
def inicio():
    falta = [n for n, p in (("ffmpeg", config.FFMPEG), ("ffprobe", config.FFPROBE))
             if not Path(p).exists()]
    return dict(
        api_key=config.key_visible(),
        var_key=config.VAR_KEY,
        falta=falta,
        videos=_videos_cerca(),
        estilos=list(config.ESTILOS_SUB.keys()),
        trabajos=sorted([d.name for d in config.TRABAJO.iterdir() if d.is_dir()]),
    )


@app.post("/api/elegir")
def elegir(que: str = "pantalla"):
    """Abre el explorador de archivos nativo de Windows.

    `que` puede ser "pantalla" o "camara": solo cambia el titulo del dialogo y
    si se intenta adivinar el archivo companero.
    """
    titulo = ("Elegi el video del gameplay" if que == "pantalla"
              else "Elegi el video de la camara")
    codigo = (
        "import tkinter as tk;from tkinter import filedialog;"
        "r=tk.Tk();r.withdraw();r.attributes('-topmost',True);"
        f"p=filedialog.askopenfilename(title={titulo!r},"
        "filetypes=[('Videos','*.mp4 *.mkv *.mov *.flv *.ts'),('Todos','*.*')]);"
        "print(p or '')"
    )
    try:
        r = subprocess.run([sys.executable, "-c", codigo], capture_output=True,
                           text=True, timeout=300)
        ruta = (r.stdout or "").strip()
    except Exception as e:
        raise HTTPException(500, f"No pude abrir el explorador: {e}")
    if not ruta:
        return dict(ruta=None)
    return dict(ruta=ruta,
                pareja=_buscar_pareja(ruta) if que == "pantalla" else None)


@app.post("/api/elegir-pareja")
def elegir_pareja(r: Ruta):
    return dict(pareja=_buscar_pareja(r.ruta))


@app.post("/api/trabajo")
def crear(t: NuevoTrabajo):
    if not Path(t.pantalla).exists():
        raise HTTPException(400, "No encuentro el archivo de gameplay.")
    if t.camara and not Path(t.camara).exists():
        raise HTTPException(400, "No encuentro el archivo de camara.")
    if not config.api_key():
        raise HTTPException(400, f"Falta la API key. Crea un .env con {config.VAR_KEY}=sk-ant-...")

    tid = _id_desde(t.pantalla)
    with LOCK:
        viejo = TRABAJOS.get(tid)
        if viejo and viejo.estado.get("fase") == "corriendo":
            raise HTTPException(409, "Ese stream ya se esta procesando.")
        trabajo = Trabajo(tid, t.pantalla, t.camara, t.n_clips, t.estilo,
                          cortar_silencios=t.cortar_silencios,
                          nivel_silencio=t.nivel_silencio, gancho=t.gancho)
        trabajo.estado.update(n_clips=t.n_clips, estilo=t.estilo,
                              pantalla=t.pantalla, camara=t.camara,
                              cortar_silencios=t.cortar_silencios,
                              nivel_silencio=t.nivel_silencio, gancho=t.gancho)
        trabajo.n_clips, trabajo.estilo = t.n_clips, t.estilo
        TRABAJOS[tid] = trabajo
    threading.Thread(target=trabajo.correr, daemon=True).start()
    return dict(id=tid)


def _obtener(tid):
    with LOCK:
        t = TRABAJOS.get(tid)
        if t is None:
            if not (config.TRABAJO / tid / "estado.json").exists():
                raise HTTPException(404, "No existe ese trabajo.")
            d = json.loads((config.TRABAJO / tid / "estado.json").read_text(encoding="utf-8"))
            t = Trabajo(tid, d["pantalla"], d.get("camara"), d.get("n_clips", 10),
                        d.get("estilo", "anton"))
            TRABAJOS[tid] = t
        return t


@app.get("/api/estado/{tid}")
def estado(tid: str):
    e = dict(_obtener(tid).estado)
    for c in e.get("clips", []):
        c.pop("cues", None)          # no hace falta en la lista
    return e


@app.get("/api/clip/{tid}/{n}")
def clip(tid: str, n: int):
    t = _obtener(tid)
    c = next((x for x in t.estado.get("clips", []) if x["n"] == n), None)
    if not c:
        raise HTTPException(404, "No existe ese clip.")
    return c


@app.post("/api/clip/{tid}/{n}")
def editar(tid: str, n: int, cuerpo: Cues):
    t = _obtener(tid)
    try:
        c = t.rehacer_clip(n, cuerpo.cues)
    except Exception as e:
        raise HTTPException(500, str(e))
    return c


@app.post("/api/cancelar/{tid}")
def cancelar(tid: str):
    _obtener(tid).cancelar()
    return dict(ok=True)


@app.get("/api/video/{tid}/{nombre}")
def video(tid: str, nombre: str):
    f = config.SALIDA / tid / nombre
    if not f.exists() or ".." in nombre:
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/miniatura/{tid}/{nombre}")
def miniatura(tid: str, nombre: str):
    """Vive en trabajo/, no en salida/: la carpeta de clips queda solo con mp4."""
    f = config.TRABAJO / tid / nombre
    if not f.exists() or ".." in nombre:
        raise HTTPException(404)
    return FileResponse(f)


@app.post("/api/abrir/{tid}")
def abrir(tid: str):
    d = config.SALIDA / tid
    d.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(d)])
    return dict(ok=True)


app.mount("/", StaticFiles(directory=str(config.WEB), html=True), name="web")


def main():
    import uvicorn
    puerto = 8420
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{puerto}")).start()
    print(f"\n  Maquina de clips -> http://127.0.0.1:{puerto}\n  (cerra esta ventana para apagarla)\n")
    uvicorn.run(app, host="127.0.0.1", port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
