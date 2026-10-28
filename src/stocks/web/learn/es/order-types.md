---
id: order-types
path: start
title: Tipos de orden: mercado, limitada y stop
minutes: 4
as_of: 2026-10-25
terms: market_order, limit_order, stop_order, bid_ask_spread, liquidity
app: ticker
---
Al comprar o vender no solo eliges qué y cuánto: también eliges cómo. El tipo de orden decide a qué precio puedes acabar operando.

## La idea
Todo valor tiene dos precios a la vez: el **bid** (lo que alguien paga ahora) y el **ask** (lo que alguien pide ahora). La diferencia es la **horquilla** o *spread*. En valores muy negociados es de céntimos; en los poco negociados, grande.

La **liquidez** es la facilidad de comprar o vender sin mover el precio. Con mucho volumen, la horquilla es estrecha. Con poco, es ancha.

Tres órdenes básicas:

- **A mercado**: compras o vendes ya, al mejor precio disponible. Se ejecuta casi seguro, pero el precio no está garantizado.
- **Limitada**: fijas un precio máximo al comprar o mínimo al vender. Controlas el precio, pero puede no ejecutarse.
- **Stop** (stop-loss): una orden que se activa cuando el precio toca un nivel. Se usa para limitar pérdidas. Al activarse suele convertirse en una orden a mercado.

## Un ejemplo
Un valor cotiza con bid 9,98 € y ask 10,02 €.

- La horquilla es 10,02 € − 9,98 € = **0,04 €**, un 0,4 % sobre 10,00 €.
- Si compras a mercado pagas 10,02 €. Si vendes a mercado justo después, recibes 9,98 €. Ese 0,4 % es un coste de entrada y salida.

Ahora un valor poco líquido con ask 10,02 € pero solo 100 acciones disponibles a ese precio. Quieres 1.000. Una orden a mercado seguiría comprando a precios más altos hasta completarse. Una **limitada a 10,05 €** compra solo hasta ese precio: te quedas con menos acciones, pero nunca pagas más de lo previsto.

## El error típico
Usar órdenes a mercado en valores poco líquidos o fuera de horario. El precio que ves no es el que obtienes.

Con el stop, un error frecuente es ponerlo demasiado cerca: una oscilación normal lo activa y vendes antes de tiempo. Y si hay un salto de precio (*gap*), un stop puede ejecutarse bastante peor que el nivel fijado.
