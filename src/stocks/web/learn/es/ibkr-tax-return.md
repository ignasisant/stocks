---
id: ibkr-tax-return
path: tax-es
title: Cómo declarar Interactive Brokers en la renta
minutes: 5
as_of: 2026-11-27
terms: tax_return, fx_conversion, withholding_tax, form_720, fifo
app: import
slug: declarar-interactive-brokers-renta
description: Qué informe pedir a Interactive Brokers, cómo pasar cada operación a euros, dónde ver la retención de los dividendos y cuándo toca el modelo 720. Con ejemplo.
---
Interactive Brokers (IBKR) te da más datos que casi cualquier otro bróker, pero no los entrega en el formato de la renta española. Estos son los pasos.

## Qué descargar
En el Portal del cliente, en Rendimiento e informes, genera un **Activity Statement** de todo el periodo, o una **Flex Query** con operaciones, dividendos y retenciones, en CSV. Pide desde tu primera compra: **FIFO** necesita el precio de cada compra para saber qué acciones vendes.

IBKR no es un bróker español y no informa por ti a Hacienda: **tú declaras**.

## Lo que el informe no te da hecho
- **Varias monedas.** Operarás en dólares, euros o libras según el mercado. Cada compra y cada venta se pasa a euros con el **tipo de cambio de su fecha**, no con el de fin de año. IBKR muestra además un resultado en la moneda base de la cuenta: no es el que declaras.
- **Dividendos y retenciones aparte.** El informe separa el dividendo bruto y la retención en origen. En la renta va el **bruto**, y lo retenido fuera se recupera con la **deducción por doble imposición**, con el límite que fija el convenio de cada país.
- **El método de coste.** El informe resume resultados con sus propios criterios. En España las acciones se venden por **FIFO**, y la **regla de los dos meses** puede bloquear pérdidas que el informe da por buenas.
- **Comisiones.** Suman al coste de la compra y restan al valor de la venta.

## Un ejemplo
Compras 10 acciones a 150 $ (1.500 $) con el euro a 1,10 $: te cuestan **1.363,64 €**. Las vendes a 165 $ (1.650 $) con el euro a 1,20 $: recibes **1.375,00 €**. La ganancia que declaras es de **11,36 €**, no el 10 % que ves en dólares.

## El modelo 720
Tus valores están custodiados fuera de España. Si su valor, sumado al de otras cuentas y bienes en el extranjero, supera los **50.000 €** a 31 de diciembre, presenta el **modelo 720** antes del 31 de marzo.

## El error típico
Copiar el resultado realizado en moneda base del informe, o el total de dividendos netos. Ninguna de las dos cifras es la que pide Hacienda.

MyBrainStock importa el informe de IBKR y hace estos cálculos: FIFO, euros al cambio de cada fecha, la regla de los dos meses y el bruto de cada dividendo con su retención. Es una ayuda para preparar la declaración, no asesoramiento fiscal: si tu caso es complejo, consulta a un asesor.
