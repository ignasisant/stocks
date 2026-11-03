---
id: order-types
path: start
title: Tipi di ordine: a mercato, limite e stop
minutes: 4
as_of: 2026-10-25
terms: market_order, limit_order, stop_order, bid_ask_spread, liquidity
app: ticker
---
Quando compri o vendi scegli non solo cosa e quanto, ma anche come. Il tipo di ordine decide il prezzo a cui puoi finire per operare.

## L'idea
Ogni titolo ha due prezzi contemporaneamente: il **bid** o denaro (quanto qualcuno è disposto a pagare ora) e l'**ask** o lettera (quanto qualcuno chiede ora). La differenza è lo **spread**. Per i titoli molto scambiati sono centesimi; per quelli poco scambiati, grande.

La **liquidità** è la facilità con cui puoi comprare o vendere senza muovere il prezzo. Con volumi alti lo spread è stretto. Con volumi bassi è ampio.

Tre ordini di base:

- **A mercato**: compra o vendi subito, al miglior prezzo disponibile. Si esegue quasi di sicuro, ma il prezzo non è garantito.
- **Limite**: fissi un prezzo massimo per comprare o minimo per vendere. Controlli il prezzo, ma potrebbe non essere eseguito.
- **Stop** (stop-loss): un ordine che si attiva quando il prezzo tocca un livello. Serve a limitare le perdite. Una volta attivato di solito diventa un ordine a mercato.

## Un esempio
Un titolo quota con bid 9,98 € e ask 10,02 €.

- Lo spread è 10,02 € − 9,98 € = **0,04 €**, lo 0,4 % di 10,00 €.
- Se compri a mercato paghi 10,02 €. Se subito dopo vendi a mercato, ottieni 9,98 €. Quello 0,4 % è un costo per entrare e uscire.

Ora un titolo poco scambiato con ask a 10,02 € ma solo 100 azioni disponibili a quel prezzo. Tu ne vuoi 1.000. Un ordine a mercato continuerebbe a comprare a prezzi più alti finché non è completato. Un **limite a 10,05 €** compra solo fino a quel prezzo: finisci con meno azioni, ma non paghi mai più del previsto.

## L'errore comune
Usare ordini a mercato su titoli illiquidi o fuori dall'orario di negoziazione. Il prezzo che vedi non è il prezzo che ottieni.

Con gli stop, un errore frequente è metterli troppo vicini: il normale movimento li attiva e vendi troppo presto. E se il prezzo salta (un *gap*), uno stop può essere eseguito ben sotto il livello che avevi fissato.
