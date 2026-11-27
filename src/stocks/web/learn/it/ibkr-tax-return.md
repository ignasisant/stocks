---
id: ibkr-tax-return
path: tax-es
title: Interactive Brokers e la dichiarazione spagnola
minutes: 5
as_of: 2026-11-27
terms: tax_return, fx_conversion, withholding_tax, form_720, fifo
app: import
slug: dichiarare-interactive-brokers-spagna
description: Quale report chiedere a Interactive Brokers, come convertire ogni operazione in euro, dove vedere la ritenuta sui dividendi e quando serve il modello 720.
---
Interactive Brokers (IBKR) ti dà più dati di quasi ogni altro broker, ma non nel formato che serve alla dichiarazione spagnola. Ecco i passaggi.

## Cosa scaricare
Nel Client Portal, in Performance e report, genera un **Activity Statement** dell'intero periodo, o una **Flex Query** con operazioni, dividendi e ritenute, in CSV. Chiedi dal primo acquisto: il **FIFO** ha bisogno del prezzo di ogni acquisto per sapere quali azioni hai venduto.

IBKR non è un broker spagnolo e non comunica al fisco al posto tuo: **dichiari tu**.

## Cosa il report non fa per te
- **Più valute.** Opererai in dollari, euro o sterline secondo il mercato. Ogni acquisto e vendita va convertito in euro al **cambio della sua data**, non a quello di fine anno. IBKR mostra anche un risultato nella valuta base del conto: non è quello che dichiari.
- **Dividendi e ritenute separati.** Il report separa il dividendo lordo dalla ritenuta alla fonte. Nella dichiarazione va il **lordo**, e quanto trattenuto all'estero si recupera con la **deduzione per doppia imposizione**, entro il limite della convenzione di ciascun paese.
- **Il metodo di costo.** Il report riassume i risultati con criteri propri. In Spagna le azioni si vendono per **FIFO**, e la **regola dei due mesi** può bloccare perdite che il report dà per buone.
- **Commissioni.** Si sommano al costo di acquisto e si sottraggono al valore di vendita.

## Un esempio
Compri 10 azioni a 150 $ (1.500 $) con l'euro a 1,10: ti costano **1.363,64 €**. Le vendi a 165 $ (1.650 $) con l'euro a 1,20: incassi **1.375,00 €**. La plusvalenza che dichiari è **11,36 €**, non il 10 % che vedi in dollari.

## Il modello 720
I tuoi titoli sono custoditi fuori dalla Spagna. Se il loro valore, sommato agli altri conti e beni all'estero, supera i **50.000 €** al 31 dicembre, presenta il **modello 720** entro il 31 marzo.

## L'errore tipico
Copiare il risultato realizzato in valuta base del report, o il totale dei dividendi netti. Nessuna delle due cifre è quella richiesta dal fisco.

MyBrainStock importa il report di IBKR e fa questi calcoli: FIFO, euro al cambio di ogni data, la regola dei due mesi e il lordo di ogni dividendo con la sua ritenuta. Aiuta a preparare la dichiarazione, non è consulenza fiscale: se il tuo caso è complesso, rivolgiti a un consulente.
