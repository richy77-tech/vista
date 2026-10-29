"""Parametri del bot privato, in un posto solo.

Perche' qui e non sparsi nel codice: un numero nascosto dentro una funzione
non si confronta. Qui si legge, si cambia, si testa. Ogni voce dichiarata.
"""

PARAMS = {
    # --- rischio e gestione posizione ---
    "atr_n": 14,        # barre dell'ATR (volatilita' media)
    "stop_atr": 1.5,    # stop = 1,5 x ATR contro
    "target_atr": 3.0,  # target = 3 x ATR (rapporto 1:2)
    "max_bars": 5,      # time stop: esce al close dopo N barre

    # --- denaro (solo simulazione: nessun conto collegato) ---
    # Il capitale e il rischio per operazione sono due cose diverse. Chi legge
    # "rischio 100 euro a operazione" e lo confonde col capitale crede di aver
    # perso piu' di quello che ha. Il rischio a operazione si calcola SEMPRE dal
    # capitale: 1% di 100 euro = 1 euro a testa, non 100.
    "capital_eur": 100.0,   # capitale simulato di partenza
    "risk_pct": 1.0,        # % del capitale rischiata a operazione
    "max_risk_pct": 5.0,    # tetto: sopra questo la size e' insensata, la taglio

    # --- filtro d'ingresso (provato, non aiuta: vedi BOT_TODO.md) ---
    # walk-forward 21/10: filtro OOS -13,6R su 471 op (exp -0,029) contro base
    # -17,1R su 860 op (exp -0,020). Meno operazioni, stesso problema per
    # operazione. Resta spegnibile, ma di default NON e' acceso: non ha una
    # prova fuori campione che lo giustifichi.
    # 29/10: riacceso. Era spento per un confronto walk-forward del 21/10, ma
    # quel confronto era sporco: il ruolo 3 chiudeva comunque ogni posizione
    # contro trend sulla stessa candela, quindi il "senza filtro" pagava solo
    # l'ingresso e non arrivava mai allo stop. Con il filtro spento, 99 delle
    # ultime 120 chiusure erano "tesi invalidata" a barre 0: stessa operazione
    # aperta e chiusa ogni 5 minuti. Ora chi apre e chi sorveglia usano la
    # stessa regola, e il registro misura la regola che resta.
    "trend_filter": True,      # richiede accordo col trend, spegnibile per confronto
    "ema_fast": 50,
    "ema_slow": 200,
    "slope_n": 10,             # barre per la pendenza dell'EMA veloce
    "min_atr_pct": 0.10,       # sotto questo l'ATR e' piatto: niente ingresso

    # --- news ---
    "news_min_impact": "HIGH",
    "news_min_move_pct": 0.35,
    "news_ttl_h": 6,
    "news_cache_min": 45,      # quanto a lungo vale una lettura AI della stessa news
}


def p(key, default=None):
    return PARAMS.get(key, default)
