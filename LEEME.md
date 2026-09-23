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
| Memes | Claude Opus 5 lee cada clip ya montado y decide qué meme va en qué segundo | 30 s |
| Generar | Compone, corta pausas, pega los memes, quema subtítulos y exporta | 30 s por clip |

**Total: unos 11 minutos** para un stream de dos horas y media.

## Lo que cuesta

Sólo los tres pasos de IA usan internet y consumen crédito. Medido sobre un stream
de 2h38m: **$0,23** elegir los momentos (Sonnet 5) + **$0,09** el gancho (Opus 5)
+ **$0,13** los memes (Opus 5) = **$0,45 por stream**.
Con $5 de crédito te alcanza para unos 11 streams.

El gancho y los memes van con el modelo más caro a propósito: son llamadas chicas
—sólo los clips ya elegidos, no la transcripción entera— y son las dos decisiones
que más definen si el video se ve o no. Todo lo demás (transcripción, detección de
voz, render) corre gratis en tu GPU. Las imágenes y los sonidos de los memes **nunca
se suben**: lo único que viaja es el texto.

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

  **Cómo se ve el cartel**, que es lo primero que ve el que scrollea:

  - **Placa blanca opaca con el texto casi negro**, no texto con contorno. El contorno
    funciona mientras el fondo sea oscuro; sobre un cielo o una pared de arenisca el
    texto blanco se empasta. Probado sobre los dos extremos del material —una cueva a
    oscuras y una pared al sol—: la placa negra se empasta con la cueva, la blanca
    revienta en las dos. También se probó la placa verde de la marca: llama más pero se
    lee más barata y choca con el verde de la palabra activa del karaoke.
  - **Sombra dura verde** (#00E676) corrida abajo a la derecha, que le da el borde de
    póster y lo separa de cualquier fondo.
  - **Fuente propia**: Montserrat Black, distinta de la del karaoke. Con la misma
    tipografía el cartel se lee como "un subtítulo más grande" y no como un cartel.
  - **Entra en tres tiempos**: el texto se descubre de izquierda a derecha en 160 ms,
    después cae la sombra verde, y recién ahí queda quieto hasta el corte. Son tres
    golpes de atención en el medio segundo que decide si el que scrollea se queda.
  - Se **escala para llenar el ancho**: un cartel corto como "QUE HICISTE" ocupaba antes
    media pantalla y se leía como un subtítulo más.

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

- **Memes sobre el gameplay.** Cada tanto aparece de golpe un sticker de meme sobre el
  juego —nunca sobre tu cara ni sobre los subtítulos—, se queda un segundo y pico, y se
  va. Muchos traen su sonido.

| Nivel | Qué hace |
|---|---|
| Sin memes | Nada |
| Poquitos | Uno o dos por clip, sólo en el momento más fuerte |
| **Medio** (por defecto) | **Dos o tres por clip, en los mejores momentos** |
| Bastantes | Uno cada 5 o 6 s, hasta 6 por clip |

  Son pocos a propósito. Un meme cada dos segundos deja de ser un chiste y pasa a ser
  ruido de fondo: lo que hace reír es que aparezca **uno**, enorme, justo donde tiene
  que aparecer.

  **Los elige Claude, leyendo.** No hay ningún detector: lo que hace gracioso a un meme
  es *cultural*. El perro mirando el atardecer no significa "perro", significa "estamos
  en el horno"; el señor levantando la piedra no significa "piedra", significa "nadie te
  hizo esto, te lo hiciste solo". Eso no sale de un clasificador. Cada meme de la carpeta
  `stickers` tiene escrita su ficha —qué se ve, qué significa hoy y en qué momento se
  usa— y el modelo elige con eso a la vista.

### Cómo se ven: crudo o sticker

| Estilo | Cómo queda |
|---|---|
| **Crudo** (por defecto) | **La foto sola, gigante, tapando el gameplay entero. Sin marco, sin sombra, sin inclinación y sin animación: aparece y desaparece de golpe** |
| Sticker | Chiquito en una esquina, con marco blanco, sombra, inclinado y entrando con un rebote |

  El `sticker` fue el primero y **ése es justamente el problema**: queda prolijo, y lo
  prolijo le saca la gracia. Es la misma lógica por la que el zoom va a saltos secos y
  los empalmes son jump cuts duros: lo que da risa hoy es que se vea **mal editado**. Un
  sticker con sombra y rebote se lee como plantilla de editor; una foto enorme tirada
  encima del gameplay se lee como que alguien la pegó ahí a mano.

  En `crudo` el meme puede tapar el gameplay completo y también los subtítulos —no pasa
  nada, dura un segundo—. Lo único que no tapa nunca, en ninguno de los dos estilos, es
  **tu cara**. Encima sale más barato de renderizar: sin animación, el tamaño no hay que
  recalcularlo en cada frame.

  **Se colocan sobre el clip ya montado**, no sobre el stream. Cuando el clip se arma, un
  segundo del original puede haber desaparecido, o aparecer dos veces (el cold open
  repite un pedazo al principio). Si el meme se ubicara antes del montaje, el que estaba
  pensado para un remate caería en cualquier lado.

  **Caen en el remate, no antes.** El sticker aparece justo cuando se escucha la palabra
  que lo justifica. Adelantado spoilea el chiste; atrasado ya no lo ve nadie.

  **Van rotando de lugar** entre seis posiciones (arriba y abajo, por izquierda, centro y
  derecha), con un empujoncito aleatorio para que no se lea como una grilla. En `crudo`
  la posición casi no se nota, porque el meme ocupa media pantalla igual.

  **Todos llevan sonido, siempre** —salvo que marques *Memes sin sonido*, que los deja
  aparecer sin ruido ninguno y se escucha sólo el audio del clip. Ese interruptor no
  cambia el plan de memes, así que prenderlo o apagarlo **no le vuelve a pagar a la IA**:
  sólo se rehace el video.

  Un meme mudo no se registra: la gente mira estos videos por el ruido. Y el sonido tiene que *pegar* con el meme —una música tétrica
  debajo de una cara feliz no da risa, da confusión—, así que cada sonido está
  clasificado por **tono** (risa, travieso, grito, tétrico, dramático, triste) y cada
  meme declara qué tonos le quedan bien. Si la IA elige uno fuera de tono, se reemplaza
  solo por el del meme.

  Dos sonidos estaban mal identificados por el nombre del archivo y se corrigieron
  buscando el origen de cada uno:

  - *"AUGGHH AHHHHH"* **no es un grito de agonía: es un ronquido exagerado** (el "goofy
    ahh" de TikTok, sacado de un guardia que se durmió sobre un altavoz). Se ve en la
    envolvente: dos golpes con silencio en el medio, que son la inhalación y la
    exhalación. Estaba puesto en el meme del manicomio, donde no pegaba nada; ahora va
    con el perro durmiendo, que es donde tiene gracia.
  - *"Plankton Groan"* no es un quejido de dibujito: es el gemido grave y fantasmal del
    **Cursed Plankton**, que es tétrico, no cómico.

  **El sonido se recorta.** Varios duran 6 o 10 segundos y traen silencio adelante, cola
  de reverb o dos golpes separados; de cada uno se usa sólo el tramo útil, medido sobre
  su envolvente de energía. Se mezclan antes de la cadena de audio, igual que el golpe
  del cold open, para que el loudnorm los mida y el clip siga saliendo a −14 LUFS.

  **Los archivos son fotos rectangulares y opacas** (los 12, medido). En `crudo` se usan
  tal cual; en `sticker` se les fabrica el marco blanco, las esquinas redondeadas, la
  sombra y la inclinación una sola vez con Pillow, y queda cacheado.

  El costo de render es bajo: quince memes le sumaban un 25% (medido: 6,8 s → 8,5 s en un
  clip de 25 s), y ahora son dos o tres.

## Si algo falla de verdad

La ventana negra ya **no** escupe tracebacks de `ConnectionResetError`. Ese error era
ruido de Windows —el navegador corta la conexión de una preview de video y el sistema
avisa—, pero llenaba la pantalla de rojo y un error de verdad quedaba enterrado ahí
adentro. Ahora se filtran **sólo** esos dos cortes de conexión; cualquier otra cosa
sigue saliendo.

Así que si ves rojo en la ventana, ahora sí importa. Los errores del procesamiento
además aparecen en la página:

- **Falla todo el stream** → banda roja arriba, con el mensaje. La traza completa
  queda en `trabajo\<stream>\estado.json`, en el campo `traza`.
- **Falla un clip suelto** → ese clip sale en gris con el motivo, y los demás siguen.
- **No se pudo elegir el gancho o los memes** → aviso amarillo, y el stream sale sin
  eso en vez de cortarse. Al volver a correrlo lo reintenta.

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
  `core/config.py`. El de los memes, `MEMES_VOLUMEN`.
- **Los memes te quedan chicos o muy prolijos** → el selector *Cómo se ven*: **Crudo**
  (gigante, sin marco, sin animación) o **Sticker** (chico y prolijo).
- **Los ruidos de los memes te molestan** → tilde en *Memes sin sonido*: siguen
  apareciendo, pero mudos.
- **Un meme cae en un momento que no da, o con un sonido que no pega** → decime cuál y
  en qué clip, y le corrijo la ficha o el tono en `core/memes.py`. La ficha es lo que lee el modelo: si está mal escrita, el
  meme cae mal por más bueno que sea todo lo demás.
- **Querés sumar un meme nuevo** → una carpeta dentro de `stickers` con su PNG (y su MP3
  si tiene sonido propio), y avisame para escribirle la ficha. Sin ficha el modelo no lo
  puede usar; la app avisa sola si encuentra una carpeta sin ficha.

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
  gancho.py         cold open y cartel de cada clip (Claude)
  memes.py          catálogo de memes y dónde va cada uno (Claude)
  silencios.py      corte de pausas y mapa de tiempos
  zoom.py           zoom a saltos sobre el gameplay
  subtitulos.py     generación del karaoke en formato ASS
  render.py         composición y exportación
  pipeline.py       orquestación de todo
web/                la interfaz
stickers/           la biblioteca de memes: una carpeta por meme, con su PNG y su MP3
tests/              tests del mapa de tiempos, la reparación y los memes
trabajo/            intermedios por proyecto (se puede borrar)
salida/             los clips terminados
```

Para correr los tests: `.venv\Scripts\python.exe tests\test_tiempos.py`
