# -*- coding: utf-8 -*-
"""Tests del servidor local.

El de aca tiene una trampa: lo que se prueba es que algo NO se imprima. Si el
filtro se pasa de listo y se come un error de verdad, no falla nada, no se
rompe nada, y el dia que el pipeline explote la ventana no va a decir nada.

Correr con:  .venv\\Scripts\\python.exe -m pytest tests -q
"""
import asyncio
import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


class _Espia(logging.Handler):
    """Se queda con lo que asyncio manda al log, mensaje y traza incluidos."""

    def __init__(self):
        super().__init__()
        self.registros = []

    def emit(self, r):
        txt = r.getMessage()
        if r.exc_info:
            txt += "\n" + "".join(traceback.format_exception(*r.exc_info))
        self.registros.append(txt)

CORTE = dict(
    message="Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)",
    exception=ConnectionResetError(10054, "corte del navegador"))
DE_VERDAD = dict(message="algo se rompio de verdad",
                 exception=ValueError("no me tapes"))


def test_solo_se_callan_los_cortes_del_navegador():
    vistos = []
    manejador = app._callar_cortes(lambda bucle, ctx: vistos.append(ctx))

    manejador(None, dict(CORTE))
    manejador(None, dict(message="x", exception=ConnectionAbortedError()))
    assert vistos == [], "los cortes del navegador no tienen que pasar"

    manejador(None, dict(DE_VERDAD))
    manejador(None, dict(message="sin excepcion"))          # ej: tarea sin await
    manejador(None, dict(message="y", exception=OSError("disco lleno")))
    assert [c["message"] for c in vistos] == [
        "algo se rompio de verdad", "sin excepcion", "y"]


def test_sin_manejador_anterior_delega_en_el_de_fabrica():
    """Si no habia ninguno, tiene que caer en el de asyncio, no perderse."""
    llamados = []

    class BucleFalso:
        def default_exception_handler(self, ctx):
            llamados.append(ctx)

    app._callar_cortes(None)(BucleFalso(), dict(DE_VERDAD))
    app._callar_cortes(None)(BucleFalso(), dict(CORTE))
    assert len(llamados) == 1


def test_el_lifespan_instala_el_filtro_y_no_tapa_los_errores():
    """De punta a punta sobre el bucle de verdad.

    `call_exception_handler` es el mismo camino por el que asyncio imprime el
    "Exception in callback ...", asi que mandarle las dos cosas por ahi dice
    exactamente que se ve y que no en la ventana del CMD.
    """
    async def correr(espia):
        bucle = asyncio.get_running_loop()
        # se usa el lifespan QUE TIENE LA APP, no `_vida` directo: si alguien
        # saca el `lifespan=_vida` del FastAPI(), el filtro no se instala nunca
        # y probando `_vida` a mano no se notaria
        async with app.app.router.lifespan_context(app.app):
            assert bucle.get_exception_handler() is not None, "no se instalo"
            bucle.call_exception_handler(dict(CORTE))
            bucle.call_exception_handler(dict(DE_VERDAD))
            await asyncio.sleep(0.1)
            con = list(espia.registros)
            espia.registros.clear()

            bucle.set_exception_handler(None)          # el de fabrica
            bucle.call_exception_handler(dict(CORTE))
            await asyncio.sleep(0.1)
        return con, list(espia.registros)

    # asyncio no escribe a stderr: lo manda por `logging`, asi que se escucha ahi
    # (con redirect_stderr el test pasa siempre y no prueba nada)
    espia = _Espia()
    log = logging.getLogger("asyncio")
    log.addHandler(espia)
    nivel, propaga = log.level, log.propagate
    log.setLevel(logging.DEBUG)
    log.propagate = False
    try:
        con, sin = asyncio.run(correr(espia))
    finally:
        log.removeHandler(espia)
        log.setLevel(nivel)
        log.propagate = propaga

    con, sin = "\n".join(con), "\n".join(sin)
    assert "ConnectionResetError" not in con, "el corte del navegador tiene que callarse"
    assert "no me tapes" in con, "un error de verdad NO se puede tapar"
    assert "ConnectionResetError" in sin, "sin filtro el ruido sale (si no, no prueba nada)"


def test_la_app_usa_su_propio_lifespan():
    """Que el `lifespan=_vida` siga puesto en el FastAPI()."""
    import inspect
    fuente = inspect.getsource(app)
    assert "lifespan=_vida" in fuente
