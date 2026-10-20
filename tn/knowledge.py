"""Enciclopedia del trading per il bot privato.

Perche' esiste: Richy vuole che l'agente risponda su qualsiasi cosa di trading,
come una Wikipedia. Senza una chiave di un modello, l'unico modo onesto di
rispondere bene e' avere in testa le voci. Qui stanno scritte, in italiano,
asciutte. Niente numeri inventati e niente consigli: definizioni e meccanica.

`lookup(text)` cerca la voce (o le voci) pertinenti e restituisce un blocco
HTML, oppure None se non sa nulla.
"""
import re

# chiave -> (titolo, spiegazione)
ENTRIES = {
    "atr": ("ATR (Average True Range)",
            "Misura quanto si muove un mercato in media per barra, includendo i gap. "
            "Non dice la direzione, dice l'ampiezza. Serve a dimensionare lo stop, "
            "non a decidere l'ingresso."),
    "rsi": ("RSI (Relative Strength Index)",
            "Oscillatore 0-100 su quanto sale vs quanto scende negli ultimi periodi. "
            "Sopra 70 = spinto su, sotto 30 = spinto giu'. In trend forti resta "
            "estremo a lungo: da solo non e' un segnale."),
    "macd": ("MACD",
             "Differenza tra due medie mobili esponenziali, con una linea di segnale "
             "piu' lenta. Misura il momentum: incroci sopra lo zero = spinta su, "
             "sotto = giu'. Ritarda per costruzione."),
    "vwap": ("VWAP (prezzo medio ponderato per volume)",
             "Prezzo medio di giornata pesato per i volumi. I grandi operatori lo "
             "usano come riferimento: sopra = compratori in controllo, sotto = "
             "venditori."),
    "media mobile": ("Media mobile (MA)",
                     "Prezzo medio degli ultimi N periodi. SMA = semplice, EMA = pesa "
                     "di piu' il recente. Dice la tendenza, non il punto d'ingresso."),
    "volume": ("Volume",
               "Quanto e' stato scambiato. Un movimento con volume alto e' credibile, "
               "uno con volume basso e' spesso rumore."),
    "supporto": ("Supporto",
                 "Zona dove le vendite si sono fermate piu' volte. Non e' una linea "
                 "esatta ma un'area: si rompe quando il prezzo chiude sotto, non "
                 "quando la tocca."),
    "resistenza": ("Resistenza",
                   "Zona dove le salite si sono fermate piu' volte. Specchio del "
                   "supporto: area, non linea."),
    "trend": ("Trend",
              "Direzione dominante: massimi e minimi crescenti = su, decrescenti = "
              "giu', laterali = range. Operare contro il trend costa di piu'."),
    "breakout": ("Breakout",
                 "Uscita decisa da una zona di supporto/resistenza o da un range. "
                 "Vale se accompagnato da volume; senza volume e' spesso un falso "
                 "breakout."),
    "falso breakout": ("Falso breakout",
                       "Il prezzo esce dalla zona e rientra subito. Punisce chi "
                       "insegue. Per questo si aspetta la conferma, non il tocco."),
    "liquidita": ("Liquidita'",
                  "Quanto e' facile comprare o vendere senza muovere il prezzo. "
                  "Molta liquidita' = spread stretti e poca slippage. Poca = salti "
                  "e costi."),
    "spread": ("Spread",
               "Differenza tra prezzo di acquisto (bid) e di vendita (ask). E' il "
               "costo base di ogni operazione."),
    "slippage": ("Slippage",
                 "Differenza tra il prezzo che ti aspettavi e quello che ottieni "
                 "davvero. Sale quando il mercato corre o la liquidita' e' poca."),
    "leva": ("Leva (leverage)",
             "Moltiplica l'esposizione rispetto al capitale. Non moltiplica solo i "
             "guadagni: moltiplica anche le perdite e avvicina la liquidazione. Va "
             "usata dopo aver capito la size, non prima."),
    "margine": ("Margine",
                "Capitale che devi tenere bloccato per tenere aperta una posizione "
                "a leva. Se scende sotto la soglia scatta il margin call."),
    "margin call": ("Margin call",
                    "La piattaforma ti chiede di aggiungere margine perche' la "
                    "posizione sta andando contro. Se non lo fai, la posizione viene "
                    "chiusa forzatamente."),
    "liquidazione": ("Liquidazione (liq.)",
                     "Chiusura forzata di una posizione a leva quando il margine non "
                     "basta piu'. E' la ragione per cui la size piccola e lo stop "
                     "prima di entrare contano piu' di ogni previsione."),
    "stop loss": ("Stop loss",
                  "Ordine che chiude la posizione a una perdita decisa prima di "
                  "entrare. E' la cosa che ti tiene in gioco: si mette sempre, non "
                  "dopo."),
    "take profit": ("Take profit (target)",
                    "Livello dove chiudi in profitto. Anche questo deciso prima, "
                    "altrimenti lo decide l'emozione del momento."),
    "risk reward": ("Rischio/rendimento (R)",
                    "Quanto rischi rispetto a quanto puoi guadagnare. 1R = la perdita "
                    "fino allo stop. Se rischi 1 per farne 3, il rapporto e' 3:1."),
    "expectancy": ("Expectancy (valore atteso)",
                   "Guadagno medio per operazione espresso in R. Positiva = sistema "
                   "che, su tante operazioni, guadagna. Si calcola fuori campione, "
                   "non sulla serie che hai usato per costruirlo."),
    "drawdown": ("Drawdown",
                 "Calo dal picco di capitale al minimo successivo. Dice quanto fa "
                 "male una serie negativa. Il numero che decide se una strategia "
                 "e' vivibile."),
    "win rate": ("Win rate",
                 "Percentuale di operazioni vincenti. Da solo non dice nulla: puoi "
                 "vincere 9 su 10 e perdere tutto su una, o vincere 3 su 10 e "
                 "guadagnare se i vincenti pagano molto."),
    "position sizing": ("Position sizing",
                        "Quanto metti per operazione. Si decide dal rischio, non "
                        "dall'idea: se rischi l'1% del capitale e lo stop e' a "
                        "1.5xATR, la size esce da li'."),
    "backtest": ("Backtest",
                 "Prova una regola sul passato. Utile per scartare, non per "
                 "convincere: se non regge fuori campione, non regge."),
    "overfitting": ("Overfitting",
                    "Quando la regola e' cucita sul passato (troppi parametri, troppe "
                    "condizioni) e smette di funzionare sul futuro. I numeri "
                    "in-sample belli sono spesso questo."),
    "fuori campione": ("Fuori campione (out-of-sample)",
                       "Dati che la strategia non ha visto mentre la costruivi. E' "
                       "l'unico numero che conta davvero."),
    "paper trading": ("Paper trading",
                      "Operazioni simulate su prezzi reali, senza soldi veri. Serve "
                      "a testare regole ed esecuzione prima di rischiare capitale."),
    "futures": ("Futures",
                "Contratto a scadenza su una merce, un indice o una valuta. Prezzo "
                "di oggi per una consegna futura. Usati con margine, quindi a leva."),
    "perpetui": ("Perpetual (perp)",
                 "Future senza scadenza, tipico delle cripto. Il prezzo resta "
                 "agganciato allo spot dal funding rate."),
    "funding rate": ("Funding rate",
                     "Pagamento periodico tra long e short nei perpetui, per tenere "
                     "il prezzo vicino allo spot. Positivo = i long pagano gli short. "
                     "E' anche un termometro di quanto il mercato e' sbilanciato."),
    "spot": ("Spot",
             "Compravendita a pronti: compri la cosa e la possiedi subito, senza "
             "scadenza ne' leva."),
    "opzioni": ("Opzioni",
                "Contratto che da' il diritto (non l'obbligo) di comprare o vendere "
                "a un prezzo deciso, entro o a una scadenza. Paghi un premio."),
    "call": ("Call",
             "Opzione che da' il diritto di comprare a un prezzo stabilito. Scommette "
             "sul rialzo."),
    "put": ("Put",
            "Opzione che da' il diritto di vendere a un prezzo stabilito. Scommette "
            "sul ribasso o copre un portafoglio."),
    "strike": ("Strike",
               "Il prezzo deciso a cui l'opzione puo' essere esercitata."),
    "short": ("Short (vendita allo scoperto)",
              "Scommetti sul ribasso: vendi ora per ricomprare piu' in basso. "
              "Perdita teoricamente illimitata, per questo lo stop e' obbligatorio."),
    "long": ("Long",
             "Scommetti sul rialzo: compri ora per vendere piu' in alto. Perdita "
             "limitata a quanto hai messo, senza leva."),
    "volatilita": ("Volatilita'",
                   "Quanto oscilla un prezzo. Alta = movimenti ampi, stop piu' "
                   "larghi, size piu' piccola. Bassa = tutto piu' lento."),
    "vix": ("VIX",
            "Indice della paura: volatilita' attesa sull'S&P 500. Sale quando il "
            "mercato trema, scende quando e' tranquillo."),
    "indice": ("Indice",
               "Panieri che misurano un mercato: S&P 500 e Dow le azioni USA, "
               "Nasdaq la tecnologia, DAX la Germania, FTSE MIB l'Italia."),
    "etf": ("ETF",
            "Fondo quotato in borsa come un'azione: replica un indice o un settore, "
            "costi bassi, si compra e vende in tempo reale."),
    "dividendo": ("Dividendo",
                  "Parte dell'utile che la societa' distribuisce agli azionisti. "
                  "Il titolo stacca il dividendo: il prezzo si aggiusta."),
    "obbligazioni": ("Obbligazioni (bond)",
                     "Prestiti che fai a uno Stato o a un'azienda in cambio di "
                     "interessi. Il prezzo si muove inverso ai tassi."),
    "rendimento": ("Rendimento (yield)",
                   "Interesse che un'obbligazione paga. Quando i tassi salgono, i "
                   "prezzi dei bond scendono e i rendimenti salgono."),
    "curva dei rendimenti": ("Curva dei rendimenti",
                             "Rendimenti dei bond per scadenza. Normalmente sale nel "
                             "tempo. Se si inverte (breve sopra lungo) e' un classico "
                             "segnale di rallentamento."),
    "inflazione": ("Inflazione",
                   "Quanto salgono i prezzi nel tempo. Erode il potere d'acquisto. "
                   "Le banche centrali la combattono alzando i tassi."),
    "cpi": ("CPI (inflazione USA)",
            "Indice dei prezzi al consumo americano. Esce ogni mese ed e' uno dei "
            "dati che muove di piu' i mercati."),
    "tassi": ("Tassi d'interesse",
              "Il costo del denaro deciso dalle banche centrali. Tassi su = denaro "
              "caro, prezzi sotto pressione; tassi giu' = il contrario."),
    "fed": ("Fed (Federal Reserve)",
            "La banca centrale americana. Decide i tassi USA e muove il dollaro e "
            "tutto il resto."),
    "fomc": ("FOMC",
             "Il comitato della Fed che decide i tassi. Le sue riunioni sono eventi "
             "ad alta volatilita'."),
    "bce": ("BCE (ECB)",
            "La banca centrale europea. Decide i tassi dell'euro."),
    "hawkish": ("Hawkish",
                "Tono da falco: la banca centrale e' pronta ad alzare i tassi o a "
                "tenerli alti. Di solito rafforza la valuta."),
    "dovish": ("Dovish",
               "Tono da colomba: la banca centrale propende per tagliare i tassi. "
               "Di solito indebolisce la valuta."),
    "nfp": ("NFP (Non-Farm Payrolls)",
            "Posti di lavoro creati negli USA fuori dall'agricoltura. Esce il primo "
            "venerdi' del mese, muove dollaro e indici."),
    "pil": ("PIL (GDP)",
            "Valore di tutto cio' che un Paese produce. Misura la crescita."),
    "carry trade": ("Carry trade",
                    "Prendi a prestito una valuta a tassi bassi e investi in una a "
                    "tassi alti, incassando la differenza. Funziona finche' il cambio "
                    "non si muove contro."),
    "correlazione": ("Correlazione",
                     "Quanto due mercati si muovono insieme, da -1 a +1. Serve a non "
                     "riempire il portafoglio di cose che sono la stessa scommessa."),
    "beta": ("Beta",
             "Quanto un titolo si muove rispetto al mercato. Beta 2 = si muove il "
             "doppio, in su e in giu'."),
    "sharpe": ("Sharpe ratio",
               "Rendimento in piu' per unita' di rischio. Piu' alto = meglio, ma "
               "solo se calcolato fuori campione."),
    "kelly": ("Criterio di Kelly",
              "Formula che dice quanto puntare in base a probabilita' e vincita. "
              "Nel trading si usa dimezzato: la versione piena e' troppo aggressiva."),
    "ordine a mercato": ("Ordine a mercato",
                         "Compri o vendi subito al miglior prezzo disponibile. "
                         "Certo l'esecuzione, incerto il prezzo."),
    "ordine limite": ("Ordine limite",
                      "Compri o vendi solo a un prezzo che scegli tu o meglio. Certo "
                      "il prezzo, incerto se verra' eseguito."),
    "stop order": ("Ordine stop",
                   "Diventa un ordine a mercato quando il prezzo tocca una soglia. "
                   "E' come si mettono gli stop."),
    "time stop": ("Time stop",
                  "Chiudi se l'idea non si realizza entro un tempo deciso. Serve a "
                  "non tenere fermo capitale in una tesi morta."),
    "notizie": ("Come si usano le notizie",
                "Una notizia conta se ha impatto alto e il prezzo conferma nella "
                "stessa direzione entro una finestra. La notizia apre, il mercato "
                "chiude: se il prezzo non conferma, non si entra."),
}

ALIASES = {
    "media mobile": ["sma", "ema", "moving average"],
    "stop loss": ["stop-loss", "stoploss", "stop di protezione"],
    "take profit": ["target", "tp"],
    "risk reward": ["r multiple", "rapporto rischio", "rischio rendimento"],
    "position sizing": ["size", "quanto puntare", "sizing", "dimensione posizione"],
    "drawdown": ["dd"],
    "leva": ["leverage", "marginale"],
    "liquidita": ["liquidità", "liquidity"],
    "volatilita": ["volatilità", "volatility"],
    "tassi": ["tasso", "interest rate", "tassi d'interesse", "tassi di interesse"],
    "bce": ["ecb"],
    "obbligazioni": ["bond", "obbligazione"],
    "rendimento": ["yield"],
    "pil": ["gdp"],
    "perpetui": ["perpetual", "perp"],
    "ordine a mercato": ["market order"],
    "ordine limite": ["limit order"],
    "opzioni": ["option", "opzione"],
    "supporto": ["support"],
    "resistenza": ["resistance"],
    "breakout": ["rottura"],
    "inflazione": ["inflation"],
}

_PHRASES = ["cos'e", "cos e", "cosa e", "che cos'e", "che significa", "significa",
            "spiegami", "spiega", "come funziona", "definizione", "differenza tra",
            "cosa vuol dire", "che vuol dire", "parlami di", "dimmi di"]

STOP = {"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "del", "della", "che",
        "e", "è", "cosa", "come", "perche", "perché", "mi", "spieghi", "spiega",
        "significa", "vuol", "dire", "cos", "e'", "the", "a", "of", "is", "what"}


def _norm(s):
    s = s.lower().replace("’", "'")
    s = re.sub(r"[^a-zàèéìòù0-9' ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s):
    return {w for w in _norm(s).split() if w and w not in STOP and len(w) > 2}


def _match_score(text, phrase):
    t = _norm(text)
    p = _norm(phrase)
    if not p:
        return 0
    if p in t:
        return 100 + len(p)
    pt = _tokens(p)
    if not pt:
        return 0
    tt = _tokens(t)
    if not tt:
        return 0
    if pt <= tt:
        return 40 + len(pt)
    return 0


def lookup(text, limit=2):
    """Voci pertinenti, o None."""
    if not text:
        return None
    norm = _norm(text)
    hits = []
    for key, (title, body) in ENTRIES.items():
        score = _match_score(norm, key)
        for a in ALIASES.get(key, []):
            score = max(score, _match_score(norm, a))
        if score:
            hits.append((score, title, body))
    if not hits:
        return None
    hits.sort(key=lambda x: -x[0])
    seen, out = set(), []
    for _, title, body in hits:
        if title in seen:
            continue
        seen.add(title)
        out.append(f"<b>{title}</b>\n{body}")
        if len(out) >= limit:
            break
    return "\n\n".join(out)


def index_line():
    return ", ".join(sorted({t.split(" (")[0] for t, _ in ENTRIES.values()}))
