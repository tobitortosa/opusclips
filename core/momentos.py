# -*- coding: utf-8 -*-
"""Seleccion de los mejores momentos para clips, con Claude Sonnet 5.

EL PARAMETRO QUE IMPORTA: effort (medido, no supuesto)
------------------------------------------------------
Sonnet 5 razona por defecto, y a effort="high" -que tambien es el default-
razona "casi siempre". Ese razonamiento se descuenta de max_tokens. Con la
transcripcion entera paso esto, dos veces:

    max_tokens=16000 -> stop_reason="max_tokens", content=[thinking], texto vacio
    max_tokens=32000 -> stop_reason="max_tokens", content=[thinking], texto vacio

O sea: se comio el presupuesto entero pensando y nunca escribio la respuesta.
Subirle el techo solo lo hace mas caro. Lo que lo arregla es effort="medium".
El JSON Schema no ayuda: restringe el bloque de TEXTO, que se emite DESPUES
del razonamiento, asi que no acota el razonamiento en absoluto.

Camino principal: el stream ENTERO en una sola llamada, para que el modelo
compare todos los momentos entre si. Partirlo en tramos impone una cuota fija
por tramo, y eso es una suposicion falsa: un stream puede tener 15 momentos
buenos en la primera hora y 2 en la ultima.

Plan B (solo si la llamada unica se queda sin presupuesto, o si el stream es
tan largo que no entra): mapa por tramos con solape + una pasada de rankeo
global sobre los candidatos.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .config import (CLIP_MAX, CLIP_MIN, DENSIDAD_CLIP, EFFORT_LLM, MAX_PALABRAS_UNA_LLAMADA,
                     MAX_TOKENS_BLOQUE, MAX_TOKENS_LLM, MAX_TOKENS_RANKEO,
                     MINUTOS_POR_BLOQUE, MODELO_LLM, SEPARACION_MINIMA, SOLAPE_BLOQUE,
                     VAR_KEY, api_key)

CRITERIOS = """Sos un editor de clips virales para streamers de gaming de habla rioplatense (Argentina). Encontras los momentos que funcionan como clips independientes en TikTok, Reels y Shorts.

QUE HACE BUENO A UN CLIP:
- GANCHO: los primeros 2 segundos deciden todo. El clip ARRANCA en la frase que engancha, no en la previa. Nada de empezar en "eeeh", "bueno", "a ver", ni a mitad de una explicacion.
- SE ENTIENDE SOLO: el que lo ve no vio el resto del stream. Si hace falta contexto previo para entender el chiste, no sirve.
- REMATE: termina en el punto alto (la reaccion, el remate, la frase final). No cortado al medio ni arrastrandose despues de que ya paso lo bueno.
- EMOCION REAL: risa, bronca, sorpresa, verguenza ajena, drama con otros jugadores, una puteada con timing. La informacion neutra no funciona.
- RITMO: habla continua, sin pausas largas.

QUE NO SIRVE: charla logistica ("esperame", "voy a la base", coordinacion aburrida), explicaciones sin remate, momentos que dependen de ver algo que la transcripcion no muestra, saludos, lectura de chat sin reaccion."""

CAMPOS = """- `inicio` y `fin`: SEGUNDOS desde el comienzo del stream, con un decimal. `inicio` cae exactamente donde arranca la frase-gancho.
- Cada clip dura entre {min:.0f} y {max:.0f} segundos. Ideal 22-45.
- `titulo`: listo para subir, en espanol argentino, 3 a 8 palabras, sin hashtags ni comillas.
- `frase_inicial`: la frase textual con la que arranca el clip. Maximo 15 palabras.
- `por_que`: una frase corta explicando por que funciona. Maximo 18 palabras.
- `puntaje`: 1 a 100. Usa todo el rango; reserva mas de 85 para lo verdaderamente bueno.
- `categoria`: gracioso, drama, reaccion, logro, fail, interaccion u opinion."""

PROMPT_BLOQUE = """{criterios}

Este es un tramo del stream ({desde} a {hasta}). Cada linea arranca con el segundo en que empieza.

{pistas}
TRANSCRIPCION DEL TRAMO:
{texto}

Elegi los mejores momentos de ESTE TRAMO para clip. Como maximo {n}, pero devolve MENOS si no hay tantos buenos: un clip mediocre hace mas daño que no publicarlo. Si el tramo entero es aburrido, devolve una lista vacia.

{campos}"""

PROMPT_RANKEO = """{criterios}

Ya se analizaron todos los tramos de un stream de {duracion:.0f} minutos y estos son los candidatos que salieron. Cada uno viene con su transcripcion textual.

CANDIDATOS:
{candidatos}

Tu tarea es elegir los {n} MEJORES para publicar, comparandolos entre si. Criterios de desempate, en orden:
1. Cual engancha mas en los primeros 2 segundos.
2. Cual se entiende mejor sin conocer el resto del stream.
3. Variedad: mejor 5 clips distintos entre si que 5 del mismo chiste. Si dos candidatos son del mismo momento o cuentan lo mismo, quedate con uno solo.

Devolve los elegidos con `inicio` y `fin` ajustados si te parece que el corte se puede mejorar (podes mover los bordes unos segundos), y volve a puntuarlos comparandolos entre si, no en abstracto. Si no hay {n} que valgan la pena, devolve menos."""


def esquema_clips():
    from pydantic import BaseModel, ConfigDict, Field

    # extra="forbid" -> el JSON Schema sale con additionalProperties: false,
    # que la API exige para structured outputs.
    class Clip(BaseModel):
        model_config = ConfigDict(extra="forbid")
        inicio: float = Field(description="Segundo donde arranca el clip")
        fin: float = Field(description="Segundo donde termina el clip")
        titulo: str
        # OJO: se llama `frase_inicial`, no `gancho`. El campo `gancho` del clip
        # lo ocupa despues el cold open (un dict con desde/hasta/cartel), y
        # cuando los dos se llamaban igual el cold open pisaba esta frase en
        # silencio: se pagaban los tokens de pedirla y no se usaba nunca.
        frase_inicial: str
        por_que: str
        puntaje: int
        categoria: str

    class Respuesta(BaseModel):
        model_config = ConfigDict(extra="forbid")
        clips: list[Clip]

    return Respuesta


def texto_con_tiempos(palabras, por_linea=14):
    """Transcripcion en lineas cortas con marca de tiempo, para que el modelo
    pueda elegir limites con precision de unos pocos segundos."""
    out = []
    for i in range(0, len(palabras), por_linea):
        g = palabras[i:i + por_linea]
        out.append(f"[{g[0]['a']:.0f}] " + " ".join(w["t"] for w in g))
    return "\n".join(out)


def _fmt_t(s):
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}"


def partir_en_bloques(palabras, duracion, minutos=MINUTOS_POR_BLOQUE, solape=SOLAPE_BLOQUE):
    """Divide el stream en tramos con solape.

    El solape existe para que un clip que cae justo en el borde de dos bloques
    no se pierda: aparece entero en al menos uno de los dos.
    """
    largo = minutos * 60.0
    if duracion <= largo * 1.35:
        return [(0.0, duracion, palabras)]
    bloques, t = [], 0.0
    while t < duracion:
        fin = min(duracion, t + largo)
        a, b = max(0.0, t - (solape if t else 0)), min(duracion, fin + solape)
        dentro = [w for w in palabras if w["b"] > a and w["a"] < b]
        if len(dentro) > 40:
            bloques.append((a, b, dentro))
        t = fin
    return bloques


def _pistas(zonas, picos):
    """Las señales locales que se le pasan al modelo como ayuda, no como orden."""
    partes = []
    if zonas:
        lineas = "\n".join(f"  {_fmt_t(z['inicio'])} a {_fmt_t(z['fin'])}"
                           f" ({z['densidad']*100:.0f}%)" for z in zonas)
        partes.append("Zonas donde habla mas seguido:\n" + lineas)
    if picos:
        partes.append("Momentos donde la voz sube marcadamente (gritos, reacciones):\n  " +
                      ", ".join(_fmt_t(p["t"]) for p in picos))
    partes.append("Son pistas, no ordenes: decidi por el CONTENIDO.")
    return "\n\n".join(partes) + "\n\n"


def _llamar(cliente, modelo, prompt, max_tokens, esquema):
    """Una llamada con salida estructurada. Devuelve (clips, uso)."""
    with cliente.messages.stream(
        model=modelo,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": EFFORT_LLM,
                       "format": {"type": "json_schema",
                                  "schema": esquema.model_json_schema()}},
    ) as flujo:
        r = flujo.get_final_message()

    uso = dict(entrada=r.usage.input_tokens, salida=r.usage.output_tokens)
    if r.stop_reason == "refusal":
        raise RuntimeError("El modelo rechazo la peticion.")
    txt = "".join(b.text for b in r.content if b.type == "text").strip()
    if not txt:
        raise RuntimeError(
            f"El modelo no devolvio texto (stop_reason={r.stop_reason}, "
            f"{r.usage.salida if hasattr(r.usage,'salida') else r.usage.output_tokens} tokens de salida). "
            f"Se quedo sin presupuesto razonando: baja EFFORT_LLM o MINUTOS_POR_BLOQUE.")
    return esquema.model_validate_json(txt).model_dump()["clips"], uso


def seleccionar(transcripcion, zonas, picos, n=10, cb=None, modelo=None, mascara=None):
    """Elige los mejores momentos. Devuelve (clips, uso)."""
    import anthropic

    key = api_key()
    if not key:
        raise RuntimeError(
            f"Falta la API key. Crea un archivo .env en la carpeta del proyecto con:\n"
            f"{VAR_KEY}=sk-ant-...\n"
            f"(Usa la cuenta que quieras que pague estos analisis.)")

    palabras = transcripcion["palabras"]
    duracion = transcripcion["duracion"]
    if not palabras:
        return [], dict(entrada=0, salida=0)

    cliente = anthropic.Anthropic(api_key=key, max_retries=3)
    modelo = modelo or MODELO_LLM
    Esquema = esquema_clips()
    campos = CAMPOS.format(min=CLIP_MIN, max=CLIP_MAX)
    pedidos = min(int(n * 1.8) + 3, 40)

    # ------------------------------------------------- CAMINO PRINCIPAL
    # El stream entero en UNA llamada: asi el modelo compara todos los momentos
    # entre si en vez de cumplir una cuota por tramo.
    if len(palabras) <= MAX_PALABRAS_UNA_LLAMADA:
        if cb:
            cb("Leyendo el stream completo y eligiendo los mejores momentos...", 0.36)
        pistas = _pistas(zonas[:40], picos[:24])
        prompt = PROMPT_BLOQUE.format(
            criterios=CRITERIOS, desde=_fmt_t(0), hasta=_fmt_t(duracion), pistas=pistas,
            texto=texto_con_tiempos(palabras), n=pedidos, campos=campos)
        try:
            crudos, uso = _llamar(cliente, modelo, prompt, MAX_TOKENS_LLM, Esquema)
            finales, rechazos = _depurar(crudos, palabras, duracion, n, mascara)
            if cb:
                cb(f"{len(finales)} clips pasaron el filtro de calidad", 0.54)
            return finales, dict(uso, llamadas=1, candidatos=len(crudos),
                                 rechazados=rechazos[:12],
                                 costo_usd=round(uso["entrada"] / 1e6 * 2 +
                                                 uso["salida"] / 1e6 * 10, 4))
        except RuntimeError as e:
            if "presupuesto" not in str(e):
                raise
            # se quedo sin presupuesto razonando: se cae al plan B
            if cb:
                cb("El stream es largo; lo analizo por tramos...", 0.36)

    # ------------------------------------------------- PLAN B: por tramos
    bloques = partir_en_bloques(palabras, duracion)
    por_bloque = max(4, int(n * 1.6 / max(1, len(bloques))) + 2)

    # ---------------------------------------------------------------- MAPA
    if cb:
        cb(f"Analizando el stream en {len(bloques)} tramos...", 0.36)

    def analizar(idx_bloque):
        i, (a, b, pals) = idx_bloque
        pistas = ""
        zz = [z for z in zonas if z["fin"] > a and z["inicio"] < b][:14]
        pp = [p for p in picos if a <= p["t"] <= b][:12]
        if zz:
            pistas += ("Zonas de este tramo donde habla mas seguido:\n" +
                       "\n".join(f"  {_fmt_t(z['inicio'])} a {_fmt_t(z['fin'])}"
                                 f" ({z['densidad']*100:.0f}%)" for z in zz) + "\n\n")
        if pp:
            pistas += ("Momentos donde la voz sube marcadamente (gritos, reacciones):\n  " +
                       ", ".join(_fmt_t(p["t"]) for p in pp) + "\n\n")
        pistas += "Son pistas, no ordenes: decidi por el CONTENIDO.\n\n"

        prompt = PROMPT_BLOQUE.format(
            criterios=CRITERIOS, desde=_fmt_t(a), hasta=_fmt_t(b), pistas=pistas,
            texto=texto_con_tiempos(pals), n=por_bloque, campos=campos)
        return _llamar(cliente, modelo, prompt, MAX_TOKENS_BLOQUE, Esquema)

    candidatos, uso_total = [], dict(entrada=0, salida=0, llamadas=0)
    with ThreadPoolExecutor(max_workers=min(4, len(bloques))) as pool:
        for clips, uso in pool.map(analizar, list(enumerate(bloques))):
            candidatos.extend(clips)
            uso_total["entrada"] += uso["entrada"]
            uso_total["salida"] += uso["salida"]
            uso_total["llamadas"] += 1

    if cb:
        cb(f"{len(candidatos)} momentos candidatos encontrados", 0.46)
    if not candidatos:
        return [], uso_total

    # quitar duplicados del solape: dos candidatos que arrancan casi igual
    candidatos.sort(key=lambda c: (-c.get("puntaje", 0)))
    unicos = []
    for c in candidatos:
        if any(abs(c["inicio"] - u["inicio"]) < 12 for u in unicos):
            continue
        unicos.append(c)

    # ---------------------------------------------------------------- REDUCE
    elegidos = unicos
    if len(unicos) > n:
        if cb:
            cb(f"Eligiendo los {n} mejores entre {len(unicos)}...", 0.50)
        from .asr import palabras_en
        lineas = []
        for i, c in enumerate(sorted(unicos, key=lambda x: x["inicio"]), 1):
            pal = palabras_en(palabras, c["inicio"], c["fin"])
            texto = " ".join(w["t"] for w in pal)[:700]
            lineas.append(
                f"--- candidato {i} | {_fmt_t(c['inicio'])} a {_fmt_t(c['fin'])} "
                f"({c['fin']-c['inicio']:.0f}s) | puntaje previo {c.get('puntaje')} "
                f"| {c.get('categoria','')}\n"
                f"    titulo propuesto: {c.get('titulo','')}\n"
                f"    inicio={c['inicio']:.1f}  fin={c['fin']:.1f}\n"
                f"    transcripcion: {texto}")
        prompt = PROMPT_RANKEO.format(
            criterios=CRITERIOS, duracion=duracion / 60,
            candidatos="\n\n".join(lineas), n=n) + "\n\n" + campos
        try:
            elegidos, uso = _llamar(cliente, modelo, prompt, MAX_TOKENS_RANKEO, Esquema)
            uso_total["entrada"] += uso["entrada"]
            uso_total["salida"] += uso["salida"]
            uso_total["llamadas"] += 1
        except Exception as e:
            # si el rankeo falla, se sigue con los del mapa ordenados por puntaje:
            # es peor devolver un error que devolver clips un poco peor elegidos
            uso_total["aviso_rankeo"] = str(e)[:200]
            elegidos = unicos

    finales, rechazos = _depurar(elegidos, palabras, duracion, n, mascara)
    if cb:
        cb(f"{len(finales)} clips pasaron el filtro de calidad", 0.54)
    uso_total["candidatos"] = len(candidatos)
    uso_total["rechazados"] = rechazos[:12]
    uso_total["costo_usd"] = round(uso_total["entrada"] / 1e6 * 2 +
                                   uso_total["salida"] / 1e6 * 10, 4)
    return finales, uso_total


def _depurar(clips, palabras, duracion, n, mascara=None):
    """Valida, ajusta a fronteras de palabra, saca solapados y recorta a n.

    Aplica un GATE DE RECHAZO: un candidato que no cumple las reglas duras se
    descarta y entra el siguiente. El usuario pidio explicitamente que nunca se
    rellene con material mediocre, asi que es preferible devolver 6 clips buenos
    que 10 con 4 flojos.
    """
    from .asr import ajustar_a_palabras, palabras_en

    limpios, rechazos = [], []
    for c in clips:
        a, b = float(c.get("inicio", 0)), float(c.get("fin", 0))
        if b <= a:
            continue
        a, b = max(0.0, a), min(duracion, b)
        if b - a < 8:
            continue
        # recortar si el modelo se paso de largo, conservando el arranque (el gancho)
        if b - a > CLIP_MAX:
            b = a + CLIP_MAX
        a, b = ajustar_a_palabras(palabras, a, b)

        motivo = None
        pal = palabras_en(palabras, a, b)
        if b - a < CLIP_MIN or b - a > CLIP_MAX + 6:
            motivo = f"dura {b-a:.0f}s (fuera de {CLIP_MIN:.0f}-{CLIP_MAX:.0f})"
        elif len(pal) < 12:
            motivo = f"solo {len(pal)} palabras"
        # GANCHO: el clip no puede empezar con silencio. No se cuentan palabras
        # (en castellano una sola palabra larga puede ser un gancho perfecto),
        # se exige que la voz ya este sonando casi desde el frame uno.
        elif pal[0]["a"] - a > 0.55:
            motivo = f"arranca con {pal[0]['a']-a:.1f}s de silencio antes de la primera palabra"
        elif len([w for w in pal if w["a"] < a + 2.5]) < 2:
            motivo = "arranca flojo (una sola palabra en los primeros 2,5 s)"
        elif mascara is not None:
            from .audio import densidad
            d = densidad(mascara, a, b)
            if d < DENSIDAD_CLIP:
                motivo = f"solo habla el {d*100:.0f}% del clip (minimo {DENSIDAD_CLIP*100:.0f}%)"
            else:
                c = dict(c, densidad=round(d, 3))
        if motivo:
            rechazos.append(dict(inicio=round(a, 1), titulo=c.get("titulo", ""), motivo=motivo))
            continue

        c = dict(c)
        c["inicio"], c["fin"] = round(a, 2), round(b, 2)
        c["duracion"] = round(b - a, 2)
        c["texto"] = " ".join(w["t"] for w in pal)
        c["puntaje"] = int(max(1, min(100, c.get("puntaje", 50))))
        limpios.append(c)

    # ranking + separacion minima (que no salgan 5 clips del mismo minuto)
    limpios.sort(key=lambda c: -c["puntaje"])
    elegidos = []
    for c in limpios:
        if any(not (c["fin"] + SEPARACION_MINIMA <= e["inicio"]
                    or c["inicio"] >= e["fin"] + SEPARACION_MINIMA) for e in elegidos):
            continue
        elegidos.append(c)
        if len(elegidos) >= n:
            break

    elegidos.sort(key=lambda c: c["inicio"])
    for i, c in enumerate(elegidos, 1):
        c["n"] = i
        c["archivo"] = f"{i:02d}_{_slug(c.get('titulo') or 'clip')}.mp4"
    return elegidos, rechazos


def _slug(s):
    s = (s or "").lower()
    for a, b in zip("áéíóúüñ", "aeiouun"):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s[:48] or "clip").rstrip("-")
