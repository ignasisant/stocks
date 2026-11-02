---
id: value-at-risk
path: returns
title: Value at risk (VaR): una brutta giornata "normale"
minutes: 3
as_of: 2026-10-25
terms: var, confidence_level
app: portfolio?tab=risk
---
Quanto posso perdere in una brutta giornata? Il value at risk (VaR) risponde con un unico numero, a patto di ricordare cosa quel numero non copre.

## L'idea
Il **VaR storico a 1 giorno al 95 %** si calcola dai rendimenti giornalieri reali del passato. Vengono ordinati dal peggiore al migliore, e si trova il punto che lascia sotto di sé il 5 % dei giorni peggiori.

Si legge così: **"19 giorni su 20 non perdi più di X"**. E il ventesimo giorno può andare peggio.

Il **livello di confidenza** (qui 95 %) è la quota di giorni che il VaR copre. Al 99 % il valore sarebbe più grande, perché copre più giorni negativi. È "storico" perché non assume alcuna formula: usa ciò che è successo davvero.

Serve abbastanza storia per essere affidabile: con pochi giorni il dato è instabile.

## Un esempio
Il tuo portafoglio vale 20.000 € e il suo VaR a 1 giorno al 95 % è del 2 %.

- VaR in euro: 20.000 × 2 % = **400 €**.
- Lettura: in 19 giorni su 20 non dovresti perdere più di 400 €.
- Un anno ha circa 250 giorni di borsa aperta. Il 5 % sono circa 12 o 13 giorni in cui la perdita **supera** i 400 €.

Quei giorni esistono, e il VaR non dice quanto si perde.

## Cosa non ti dice il VaR
- **Non è il caso peggiore.** È la soglia del peggior 5 %, non il minimo. La brutta giornata può essere il doppio o il triplo.
- **Ignora le code.** Le crisi (marzo 2020, per esempio) concentrano perdite estreme che una storia tranquilla non mostra.
- **È una fotografia del passato.** Se cambiano il portafoglio o il mercato, cambia il numero.
- **Copre un solo giorno.** Non dice quanto puoi perdere in un mese.

## L'errore comune
Leggere "95 %" come "sicuro". Misura una brutta giornata ordinaria, non una crisi. Usalo per tarare il battito quotidiano del tuo portafoglio, e abbinalo al drawdown massimo per vedere cosa può far male davvero.
