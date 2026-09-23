# ⚡ TRADING NEWS AI — REAL-TIME MARKET INTELLIGENCE

Hub automatico per news + market data + calendario economico + sentiment + alert su
Telegram, e una dashboard web (Vista). Solo fonti gratuite, nessun dato inventato.

- Canale Telegram: https://t.me/tradingnewsbot_richy
- Dashboard: https://richy77-tech.github.io/vista/

## Cosa fa

- **News engine** — 13 feed RSS reali (Fed, ECB, WSJ, MarketWatch, CNBC, Yahoo,
  Investing, Cointelegraph, CoinDesk, Decrypt + 3 IT). Catena: ingestion → filtro →
  dedup → categoria → asset → impatto → sentiment → Telegram.
- **Impact engine** — LOW / MEDIUM / HIGH / CRITICAL con parole-chiave e tier della
  fonte. Le pubblicazioni di routine (atti Fed, survey) restano LOW.
- **Market data** — cripto (CoinGecko) + oro, argento, petrolio, forex (EUR/USD,
  GBP/USD, USD/JPY, DXY), indici (S&P 500, NASDAQ, VIX) e azioni via Yahoo Finance.
- **Calendario economico** — feed settimanale ForexFactory (gratis, senza chiave),
  filtrato su USA/EU/UK/JP/CH/CN.
- **Alert Telegram** — breaking news, alert di prezzo (soglia %), alert pre-evento
  (30 minuti a eventi MEDIUM/HIGH).
- **Daily market brief** — report giornaliero con dati, eventi, sentiment, rischi.
- **Comandi** — /start /help /news /breaking /btc /crypto /gold /forex /stocks
  /macro /calendar /alerts /sentiment /status /settings
- **Storico** — SQLite (`data/history.db`, locale) + snapshot JSON
  (`data/news_history.json`, committabile).

## Fatto vs interpretazione

Sempre separati, e dichiarati:
- **FACT / MARKET DATA** — titolo, link, prezzo, numeri. Solo da fonti reali.
- **AI INTERPRETATION** — categoria, impatto, sentiment. Se manca `AI_API_KEY` si usa
  un motore a regole deterministico. Mai presentato come fatto, mai consiglio di
  acquisto/vendita.

## Uso

```bash
cp .env.example .env      # riempi TELEGRAM_BOT_TOKEN (e AI_API_KEY se vuoi)
export TG_TOKEN=...       # oppure via .env
python3 newsbot.py it              # stampa il digest
python3 newsbot.py --send          # pubblica digest + icone
python3 newsbot.py --auto          # ciclo completo (digest/news/breaking/alert/comandi)
python3 newsbot.py --brief         # daily market brief
python3 newsbot.py --breaking      # solo notizie alto impatto
python3 newsbot.py --calendar      # eventi di oggi
python3 newsbot.py --commands      # risponde ai comandi pendenti
python3 tests/test_engine.py       # test offline
```

## Struttura

```
newsbot.py        orchestratore + composizione messaggi
tn/http.py        GET con retry/backoff
tn/newsengine.py  ingestion feed + pipeline
tn/ai.py          classificazione/impatto/sentiment (regole + hook LLM)
tn/marketdata.py  multi-asset Yahoo + crypto
tn/calendar.py    calendario economico
tn/store.py       storico SQLite + snapshot JSON
tn/commands.py    comandi Telegram
```

## Limiti noti (onesti)

- La sandbox è effimera: `--auto` gira quando viene lanciato, non è un demone 24/7.
  Per un servizio sempre acceso serve un host (VPS) con cron.
- Il percorso AI (LLM) è implementato ma **non testato** senza una chiave: in assenza
  si usa il motore a regole.
- Nessuna previsione di prezzo, nessuna garanzia di profitto.

## Disclaimer

Informazioni a scopo informativo ed educativo. Non costituiscono consulenza
finanziaria né raccomandazione di investimento. I mercati finanziari comportano rischi.
