# Máquina de clips

Convierte un stream de horas en clips verticales listos para TikTok, Reels y Shorts.
Todo corre en esta máquina; lo único que sale a internet es el texto de la transcripción.

## Para usarla

**Doble clic en `INICIAR.bat`.** Se abre el navegador solo.

1. Elegís el video del gameplay (si el de cámara se llama igual pero con `CAMARASOLA`, lo encuentra solo).
2. Movés el slider para decir cuántos clips querés.
3. Botón **Generar clips**.

Los clips terminados quedan en `salida\<nombre-del-stream>\`, con el título en el nombre
del archivo para que sepas cuál es cuál al subirlos.

## Lo que hace, paso a paso

| Paso | Qué hace | Cuánto tarda (stream de 2h38m) |
|---|---|---|
| Revisar | Lee resolución, fps y audio de los archivos | 1 s |
| Sincronizar | Mide el desfase entre pantalla y cámara por correlación de audio | 2 s |
| Audio | Extrae la pista para analizar | 5 s |
| Voz | Detecta dónde hablás de verdad (no por volumen: el juego engaña) | 60 s |
| Transcribir | Whisper large-v3 en la GPU | 100 s |
| Elegir | Claude Sonnet 5 lee el stream entero y elige los mejores momentos | 90 s |
| Gancho | Claude Opus 5 elige el cold open de cada clip y le escribe el cartel | 30 s |
| Generar | Compone, corta pausas, quema subtítulos y exporta | 30 s por clip |

**Total: unos 10 minutos** para un stream de dos horas y media.

## Lo que cuesta

Sólo los dos pasos de IA usan internet y consumen crédito. Medido sobre un stream
de 2h38m: **$0,23** elegir los momentos (Sonnet 5) + **$0,09** el gancho (Opus 5)
= **$0,32 por stream**. Con $5 de crédito te alcanza para unos 15 streams.
El gancho va con el modelo más caro a propósito: es una llamada chica —sólo los
clips ya elegidos, no la transcripción entera— y es la decisión que más define si
el video se ve o no. Todo lo demás (transcripción, detección de voz, render) corre
gratis en tu GPU.

La API key va en el archivo `.env`:

```
CLIPS_API_KEY=sk-ant-...
```

Se lee **sólo de ahí**, nunca de una variable del sistema, así que no hay forma
de que use otra cuenta por accidente. La app te muestra arriba a la derecha los
últimos dígitos de la que está usando.

## Cómo salen los clips

- **1080x1920 a 60 fps**, H.264 CRF 16 (calidad máxima), audio AAC 256k a −14 LUFS.
- **Cámara arriba (1/3), gameplay abajo (2/3).** La cámara se ve completa, sin zoom.
- **Subtítulos karaoke**: frase en blanco, la palabra que estás diciendo en verde.
- **Cold open**: el clip arranca con un adelanto de 2 a 3,5 segundos del momento más
  llamativo que va a pasar, con un **cartel grande** encima, corta seco con un
  **golpe de sonido**, y recién ahí empieza. Es el avance de una película comprimido:
  el que scrollea ve el pico antes de decidir si se queda.

  **Lo elige Claude Opus 5**, y de una forma que importa: no le pedimos que invente
  tiempos, le damos una **lista de fragmentos ya recortados** —cada uno con la
  duración justa y cortado en frontera de frase— y elige el número de uno. Antes
  devolvía segundos, que sólo podía deducir de los timestamps de las palabras, así
  que por construcción **le era imposible elegir una risa o un grito**. Y medido
  sobre un stream de 2 horas: de los 30 picos de voz más fuertes, **10 no tienen
  ninguna palabra transcrita** (Whisper escribe "jaj*" una sola vez en todo el
  stream). Un tercio del mejor material le era invisible. Ahora esos tramos —el
  detector de voz oye a alguien, el transcriptor no escribió nada— entran a la
  lista marcados como REACCIÓN, con lo que se dice justo antes para que se entienda
  de qué se ríe.

  Si el mejor fragmento del clip no llega a 55 de 100 de "fuerza", **el clip va sin
  adelanto**: uno flojo es peor que ninguno, porque le roba los primeros segundos.

  **El cartel existe por una medición**: se sacaron frames de la webcam en los 8
  momentos de mayor energía del stream y en los 8 la cara está neutra, mirando al
  monitor, en un cuarto oscuro. O sea que el canal visual del cold open está vacío.
  Si la imagen no gancha sola, el gancho hay que **escribirlo**: Claude devuelve 3 a
  6 palabras que van en letras grandes justo debajo de la cámara (arriba de todo
  tapaba la cara cuando estás sentado derecho). Es lo que se usa hoy en TikTok.

  **Por qué no se detecta con audio**: se probaron tres enfoques y los tres se
  descartaron midiendo, porque el audio es un mix (tu voz + Minecraft + los otros
  por Discord). Volumen: no distingue un grito de una explosión. Clasificador
  entrenado en AudioSet: 0,040 de probabilidad máxima para "grito" en 158 minutos.
  Tono + periodicidad: 14 eventos en 121 minutos, casi todos charla normal y dos de
  22 segundos. El gancho no se detecta: se elige leyendo, y se construye.

  El adelanto va con un acercamiento propio, más marcado, para que se lea como
  adelanto.

- **Sin tiempos muertos**, con cuatro intensidades:

| Nivel | Cómo funciona | Saca hasta |
|---|---|---|
| Suave | Saca pausas de más de 0,70 s | 25% |
| Normal | Saca pausas de más de 0,45 s | 45% |
| Frenético | Saca pausas de más de 0,26 s | 70% |
| **Sin respiro** (por defecto) | **Pega solo los tramos con voz** | **92%** |

  Los primeros tres restan pausas del clip, y por eso tienen un techo: siempre queda
  algo de aire. **Sin respiro funciona al revés**: no resta nada, arma el clip pegando
  únicamente los tramos donde hay voz, con 20 ms de respiro a cada lado, y corta
  incluso las micro-pausas de adentro de una frase. El silencio queda en cero por
  construcción, no por umbral.

  **La duración no se protege.** Un clip de 40 s puede quedarte en 12 s, y está bien:
  vale más un clip corto que no para, que uno largo con baches.

  Cuenta como voz la unión de lo que transcribió el ASR **y** lo que detectó el VAD:
  si mirara solo la transcripción se perderían las risas y los gritos, que Whisper no
  transcribe y que suelen ser lo mejor del clip.

  En cada empalme mete un fundido de audio de 12 ms. Imperceptible como fundido, pero
  sin él, con 30 cortes, se escucharía un chasquido en cada uno. El video se corta
  seco, que es el jump cut que se busca.

- **Zoom a saltos sobre el gameplay.** El encuadre del juego salta entre dos o tres
  distancias durante todo el clip: se queda un rato en un plano, **tac**, está en otro,
  se queda, vuelve. La cámara no se toca: tu cara queda quieta.

| Modo | Qué hace |
|---|---|
| Sin zoom | Encuadre fijo |
| Simple | Salta un 8%, cada 2 s más o menos |
| **Mediano** (por defecto) | **Salta un 15%, cada 1,4 s más o menos** |
| Extremo | Salta un 22%, cada segundo. Se come la barra de items |

  **Ninguno tiene transición**, a propósito. Un zoom que se desliza el ojo lo predice y
  deja de mirarlo; el salto seco no se puede anticipar y cada uno vuelve a pedir
  atención. Es la misma lógica del jump cut duro que el video ya usa en cada empalme.

  **Sólo el gameplay.** Zoomear el cuadro entero acerca también la webcam, y la cara no
  aguanta el tironeo: se lee como que se mueve la persona, no la edición.

  **Los tiempos entre saltos no son parejos.** Un salto cada exactamente 1,5 segundos se
  siente como un metrónomo y el ojo lo empieza a anticipar. La variación es
  pseudoaleatoria pero determinista —sembrada con el número de clip—, así que rehacer un
  clip da exactamente el mismo montaje, no otro.

  **Y son tres planos, no dos.** Con dos, el vaivén se vuelve un interruptor y se predice
  después de tres saltos. El del medio rompe el patrón sin costar nada.

  El salto va **después de pegar los trozos** (ahí el reloj ya es el del clip terminado;
  si fuera antes, un salto programado para el segundo 10 caería en cualquier lado, o se
  perdería si ese pedazo se cortó) y **antes de quemar los subtítulos** (si no, el texto
  saltaría de tamaño con la imagen). Cuesta 2 segundos por clip.

  **El punch-in se apaga solo cuando hay saltos.** Hacían el mismo trabajo y encimados
  los dos zooms se multiplican.

## Si algo no te gusta

- **Los subtítulos escucharon mal una palabra** → botón *Subtítulos* en el clip. Las
  palabras que la IA escuchó con poca confianza vienen resaltadas en amarillo. Corregís
  y se rehace sólo ese clip.
- **Querés otra tipografía** → el desplegable de estilo: Anton (condensada, más impacto),
  Montserrat (el look de Opus Clip) o Poppins.
- **Te da menos clips de los que pediste** → es a propósito. Hay un filtro que descarta
  los que arrancan con silencio o duran poco. Prefiere darte 7 buenos que 10 con 3 flojos.
- **Un clip salió sin cartel ni adelanto** → es que ninguno de sus fragmentos llegó a
  55 de fuerza. Pasa con los clips de charla tranquila y está bien que pase.
- **El golpe de sonido te resulta fuerte o flojo** → `IMPACTO_VOLUMEN` en
  `core/config.py`.

## Estructura

```
app.py              servidor local (FastAPI) y API
core/
  config.py         todo lo ajustable: layout, calidad, umbrales
  ff.py             ffmpeg y ffprobe
  sync.py           desfase entre pantalla y cámara
  audio.py          detección de voz y densidad de habla
  asr.py            transcripción
  reparar.py        arregla timestamps rotos de Whisper
  momentos.py       elección de los mejores momentos (Claude)
  silencios.py      corte de pausas y mapa de tiempos
  zoom.py           zoom a saltos sobre el gameplay
  subtitulos.py     generación del karaoke en formato ASS
  render.py         composición y exportación
  pipeline.py       orquestación de todo
web/                la interfaz
tests/              tests del mapa de tiempos y la reparación
trabajo/            intermedios por proyecto (se puede borrar)
salida/             los clips terminados
```

Para correr los tests: `.venv\Scripts\python.exe tests\test_tiempos.py`
