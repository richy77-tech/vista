"""Le regole del desk B sono dichiarate prima di guardare il risultato: qui si
verifica solo che facciano quello che dicono, senza rete e senza modello."""
from tn import rules_desk as rd


def _s(trend, ch, rsi):
    return {"sym": "X", "trend": trend, "change": ch, "rsi": rsi}


def test_long_solo_con_trend_su_e_movimento_positivo():
    assert rd._side(_s("su", 0.5, 50)) == "long"
    assert rd._side(_s("giu", 0.5, 50)) is None
    assert rd._side(_s("su", -0.5, 50)) is None


def test_short_solo_con_trend_giu_e_movimento_negativo():
    assert rd._side(_s("giu", -0.5, 50)) == "short"
    assert rd._side(_s("su", -0.5, 50)) is None
    assert rd._side(_s("giu", 0.5, 50)) is None


def test_trend_piatto_non_opera_mai():
    assert rd._side(_s("piatto", 2.0, 50)) is None
    assert rd._side(_s("piatto", -2.0, 50)) is None


def test_niente_entrate_in_estremo_di_rsi():
    assert rd._side(_s("su", 0.5, 75)) is None
    assert rd._side(_s("giu", -0.5, 25)) is None


def test_sotto_la_soglia_di_movimento_non_e_un_segnale():
    assert rd._side(_s("su", 0.01, 50)) is None


def test_registro_separato():
    from tn import paper
    assert rd.STATE != paper.STATE
    assert rd.STATE.endswith("paper_state_rules.json")