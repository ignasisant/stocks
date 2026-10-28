---
id: volatility-and-drawdown
path: returns
title: Volatilidad y caída máxima: cuánto se mueve y cuánto duele
minutes: 4
as_of: 2026-10-25
terms: volatility, standard_deviation, drawdown
app: portfolio?tab=risk
---
Dos activos pueden dar un 8 % anual y ofrecer experiencias muy distintas: uno sube sin sobresaltos y el otro te hace pasar por caídas del 40 %. Dos medidas capturan esa diferencia.

## La idea
La **volatilidad** mide cuánto se mueve el precio. Técnicamente es la **desviación estándar** de los rendimientos: cuánto se alejan, de media, de su promedio. Se calcula con rendimientos diarios y se anualiza multiplicando por la raíz de 252, los días de mercado que tiene un año.

Más volatilidad significa un camino más irregular, no necesariamente peor resultado.

La **caída máxima** (*drawdown*) es el peor descenso desde un máximo hasta el mínimo posterior. Responde a "¿cuánto habría llegado a perder si hubiera comprado en el peor momento?". Es lo que de verdad se siente.

## Un ejemplo
Un fondo tiene una volatilidad diaria del 1 %. Anualizada: 1 % × √252 ≈ 1 % × 15,9 = **15,9 %**. Un año normal suele moverse dentro de ese orden de magnitud respecto a su media.

Ahora la caída. Tu cartera de 10.000 € baja a 7.000 €: una caída del 30 %. Para volver a 10.000 € necesitas 10.000 / 7.000 − 1 ≈ **+42,9 %**, no un 30 %.

Esta asimetría crece rápido:

- −10 % necesita +11,1 %.
- −20 % necesita +25 %.
- −50 % necesita **+100 %**: 100 € que caen a 50 € tienen que duplicarse.

## Volatilidad no es pérdida permanente
Una caída solo es pérdida si vendes. Si el negocio sigue sano, el precio puede recuperarse, aunque a veces tarde años. Y a veces no se recupera: una empresa que quiebra no vuelve. Por eso la volatilidad dice cómo es el viaje, no a dónde llegas.

## El error típico
Equiparar volatilidad con riesgo y ya está. El riesgo real depende de tu horizonte y de si podrás aguantar sin vender. Quien necesita el dinero en un año no puede esperar la recuperación; quien invierte para 20 años, sí.

Otro error: fijarse solo en la volatilidad y no en el drawdown. Una cartera de volatilidad moderada puede tener una caída profunda si todo cae a la vez. Conviene mirar ambas, y preguntarte si soportarías ver tu cartera −40 % sin tocar nada.
