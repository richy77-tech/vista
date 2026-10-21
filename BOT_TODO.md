# BOT PRIVATO — lista di lavoro (checkpoint)

Aggiornata: 21/10 10:10 CEST.
Regola: ogni voce fatta si cancella da "Da fare" e finisce in "Fatte" con la prova.

## Da fare (in ordine)

1. **Archivio notizie.** Salvare ogni news con ora e impatto, cosi' la regola
   news diventa testabile. Adesso non lo e'.
2. **Rimisurare l'agente AI.** Dopo il fix del POST, confermare in un giro reale
   che parla: `last_reply` dentro `private_state.json`.
3. **Regola d'ingresso alternativa.** La rottura non ha edge (vedi verdetto).
   Provare il rientro (pullback) dentro il trend, SEMPRE con walk-forward prima
   di accenderla.
4. **Ragionamento.** La spiegazione dell'agente deve citare gli indicatori
   (regime, RSI, ATR) e il perche' dell'uscita, non solo il prezzo.
5. **News engine.** Dare al modello il contesto indicatori, non solo il titolo.

## Fatte (eliminate, con prova)

- [x] **Parametri in un posto solo** -> `tn/tunables.py`. Prima erano numeri
  sparsi nelle funzioni, impossibili da confrontare.
- [x] **Indicatori nuovi** -> `tn/indicators.py`: EMA, pendenza, ATR%, regime
  (su / giu' / piatto). Fonte una sola, riusa rsi/ma di marketdata.
- [x] **Campo "reason" vuoto** sulle operazioni aperte -> ora scritto
  all'apertura (rottura + trend + RSI + volatilita'); l'uscita ha il campo suo
  `exit_reason` (stop / target / time).
- [x] **Misure vere** -> `report()` porta expectancy, max drawdown, uscite sul
  tempo; la schermata mostra il "perche'" di ogni posizione aperta.
- [x] **Riga di test fuori campione** -> `tn/backtest.py`,
  comando `python -m tn.backtest`. Nessun ordine, nessun soldo.
- [x] **Verdetto onesto** sul filtro d'ingresso -> non aiuta (sotto).

## Verdetto del test (21/10, 5 anni, split 70/30)

| variante | OOS tot | op | exp |
|---|---|---|---|
| base (rottura, target 3xATR, 5 barre) | -17,1R | 860 | -0,020 |
| + filtro trend | -13,6R | 471 | -0,029 |
| target 1,5xATR | -3,0R | 931 | -0,003 |
| filtro + 15 barre | -1,6R | 315 | -0,005 |

Uscite sul tempo: 62% con 5 barre, 26% con 15. Il time stop e' una perdita, ma
non e' la causa: nessuna variante supera zero fuori campione.
**Conclusione: questa regola non ha vantaggio. Su questo non si arma nessuna
chiave.** Il filtro resta nel codice ma spento: non lo giustifica una prova.
