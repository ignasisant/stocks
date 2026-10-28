---
id: value-at-risk
path: returns
title: Valor en riesgo (VaR): un mal día "normal"
minutes: 3
as_of: 2026-10-25
terms: var, confidence_level
app: portfolio?tab=risk
---
¿Cuánto puedo perder en un mal día? El valor en riesgo (VaR) responde con un solo número, siempre que recuerdes lo que ese número no cubre.

## La idea
El **VaR histórico a 1 día al 95 %** se calcula mirando los rendimientos diarios reales del pasado. Se ordenan del peor al mejor y se busca el punto que deja al 5 % de los días peores por debajo.

Se lee así: **"19 de cada 20 días no pierdes más de X"**. Y el día 20 sí puede ser peor.

El **nivel de confianza** (aquí 95 %) es la proporción de días que el VaR cubre. Con 99 % la cifra sería mayor, porque cubre más días malos. Es "histórico" porque no asume ninguna fórmula: usa lo que de verdad ocurrió.

Necesita suficiente historia para ser fiable: con pocos días, la cifra es poco fiable.

## Un ejemplo
Tu cartera vale 20.000 € y su VaR a 1 día al 95 % es del 2 %.

- VaR en euros: 20.000 × 2 % = **400 €**.
- Lectura: en 19 de cada 20 días no deberías perder más de 400 €.
- Un año tiene unos 250 días de mercado. El 5 % son unos 12 o 13 días en los que la pérdida **sí** supera los 400 €.

Esos días existen, y el VaR no dice cuánto se pierden.

## Lo que el VaR no dice
- **No es el peor caso.** Es el umbral del 5 % peor, no el suelo. El día malo puede ser el doble o el triple.
- **Ignora las colas.** Las crisis (marzo de 2020, por ejemplo) concentran pérdidas extremas que un historial tranquilo no muestra.
- **Es una foto del pasado.** Si la cartera o el mercado cambian, el número cambia.
- **Es de un solo día.** No dice cuánto puedes perder en un mes.

## El error típico
Entender "95 %" como "seguro". Es una medida de un mal día corriente, no de una crisis. Úsala para calibrar el pulso diario de tu cartera, y combínala con la caída máxima para ver lo que puede doler de verdad.
