---
id: fifo
path: tax-es
title: FIFO: qué acciones se consideran vendidas
minutes: 4
as_of: 2026-10-25
terms: fifo, cost_basis, lot
app: portfolio?tab=tax
---
Compraste la misma acción varias veces a precios distintos. Cuando vendes solo una parte, ¿cuál de esas compras estás vendiendo? De la respuesta depende cuánto tributas.

## La idea
Cada compra es un **lote**: un número de acciones con su propio precio. Si compras 10 acciones hoy y 10 el mes que viene, tienes dos lotes.

En España, para valores homogéneos (los de una misma empresa) la ley obliga a usar **FIFO** (*first in, first out*): se consideran vendidas primero las acciones más antiguas. No puedes elegir el lote más conveniente.

El **coste de adquisición** (*cost basis*) es lo que te costó cada lote **incluyendo las comisiones de compra**. Al vender, las comisiones de venta restan del importe recibido. Así, las comisiones reducen tu ganancia imponible.

## Un ejemplo
- Compra 1: 10 acciones a 100 € + 5 € de comisión = **1.005 €** de coste.
- Compra 2: 10 acciones a 120 € + 5 € de comisión = **1.205 €** de coste.
- Venta: 15 acciones a 130 € = 1.950 €, menos 6 € de comisión = **1.944 €** netos.

Con FIFO, la venta consume el lote 1 entero (10 acciones) y 5 del lote 2:

- Coste lote 1: 1.005 €
- Coste de 5 acciones del lote 2: 1.205 € × 5 / 10 = 602,50 €
- Coste total: 1.607,50 €

Ganancia: 1.944 − 1.607,50 = **336,50 €**.

Te quedan 5 acciones con un coste de 602,50 € (120,50 € cada una). Cuando las vendas, partirás de ese coste, no del precio medio.

## El error típico
Calcular con el **precio medio**. Aquí saldría 2.210 / 20 = 110,50 € por acción, un coste de 1.657,50 € para 15 acciones y una ganancia de 286,50 €. Parece más cómodo, pero en España no es válido para valores: Hacienda exige FIFO.

Otro fallo: usar solo el precio de las acciones y olvidar las comisiones. Y si operas en varios brókeres, FIFO se aplica sobre todas tus acciones de esa empresa juntas, no broker por broker.
