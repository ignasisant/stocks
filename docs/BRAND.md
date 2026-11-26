# MyBrainStock — voz y bio

## Tono de voz

- **Corto y directo.** Una idea por frase. Si cabe en 120 caracteres, no usa 200.
- **Cercano, sin jerga.** "Tu cartera", "te lo calculo", no "optimice su exposición".
- **Concreto.** Un número o un ejemplo antes que un adjetivo. Cifras con su moneda.
- **Educativo, nunca consejo.** Explicamos cómo se calcula o cómo se declara. No decimos "compra X". Nunca prometemos rentabilidad.
- **Honesto con los límites.** Si la IA no sabe algo, lo dice. Si un dato falta, se ve el hueco.
- **Fundador técnico, en primera persona.** "Lo construí porque…", sin plural mayestático.
- Sin emojis como adorno ni signos de exclamación en cadena. Español de España por defecto.

Aviso legal en bio, guías y vídeos: *Contenido educativo, no es asesoramiento financiero.*

## Bio única

> Tu cartera, leída por una IA. Impuestos españoles hechos.

Con aviso (cuando la red lo permita): *Educativo, no es asesoramiento financiero.*

## Enlace por red

Un `utm_source` distinto en cada una, para ver en `stocks logs funnel` qué red trae gente.

En la bio va la **dirección corta**: redirige a la home con el enlace completo
(`src/stocks/web/shortlinks.py`), así el perfil enseña `mybrainstock.com/ig` y
no una URL con parámetros. Una red nueva se añade a `shortlinks.SOURCES`.

| Red | Dirección corta (la de la bio) | Enlace completo |
|---|---|---|
| Instagram | mybrainstock.com/ig | https://mybrainstock.com/?utm_source=instagram&utm_medium=bio |
| TikTok | mybrainstock.com/tiktok | https://mybrainstock.com/?utm_source=tiktok&utm_medium=bio |
| X | mybrainstock.com/x | https://mybrainstock.com/?utm_source=x&utm_medium=bio |
| LinkedIn | mybrainstock.com/li | https://mybrainstock.com/?utm_source=linkedin&utm_medium=bio |
| YouTube | mybrainstock.com/yt | https://mybrainstock.com/?utm_source=youtube&utm_medium=bio |
| Threads | mybrainstock.com/threads | https://mybrainstock.com/?utm_source=threads&utm_medium=bio |
| Bluesky | mybrainstock.com/bsky | https://mybrainstock.com/?utm_source=bluesky&utm_medium=bio |
| Reddit | mybrainstock.com/reddit | https://mybrainstock.com/?utm_source=reddit&utm_medium=bio |

La landing enseña en el pie los perfiles que ya existen (`landing.SOCIALS`).
Se añade uno cuando su cuenta está creada, no antes.

## Marca visual

Colores y tipografía los del sistema Aguait (ver `frontend/app` tokens y `theme.ts`). Acento `#A98EF7` sobre superficie oscura; foco de teclado 2 px en el acento.
