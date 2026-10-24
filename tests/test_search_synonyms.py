"""R3-9 eş anlamlı genişletmesi: kullanıcının dediği kelime ile tablonun dediği kelime aynı değil.

İddia aramanın isabeti değil (o test_search.py'de) genişletmenin davranışı: sorgudaki iş terimi
kuralının eş anlamlılarını getirir, bunlar yalnız sözcük bacağına girer, kapalıyken arama bugünkü
skorlarının ta kendisidir ve vektör bacağı ham sorguyu görmeye devam eder. Genişletmenin ölçüsü
elle kurulmuş bir korpus: hedef tablo eş anlamlıyla yazılmışsa ham "ciro" onu bulamaz, genişletme
bulur - gerçek şemada bu iki kelime zaten aynı metinde durduğu için kanıt burada ince kalırdı.
"""

from nl2sql import config
from nl2sql.index.docs import Doc
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import HybridSearch, synonym_query
from nl2sql.index.text import fold
from nl2sql.schema_map.rules import load_rules

RULES = load_rules()
CIRO = next(rule for rule in RULES if rule["id"] == "ciro")
QUERY = "ciro"

# Elle korpus: TBLAYLIK iş teriminin kendisini hiç söylemez, yalnız eş anlamlılarını söyler;
# TBLFATUIRS terimin kendisini söyler ki genişletme onu bulurken yenisi de arkadan gelsin;
# TBLDEPO hiçbirini söylemez - genişletmenin saçmaması onun üzerinden ölçülür.
INVOICE = Doc(
    id="table:TBLFATUIRS",
    collection="tables",
    title="TBLFATUIRS",
    text="TBLFATUIRS [satış] Fatura başlıkları\nGENELTOPLAM — KDV dahil ciro",
)
SUMMARY = Doc(
    id="table:TBLAYLIK",
    collection="tables",
    title="TBLAYLIK",
    text="TBLAYLIK [rapor] Aylık satış geliri ve satış hasılatı özeti\nTUTAR — tutar",
)
DEPOT = Doc(
    id="table:TBLDEPO",
    collection="tables",
    title="TBLDEPO",
    text="TBLDEPO [stok] Depo tanımları\nDEPO_KODU — depo kodu",
)
CORPUS = [INVOICE, SUMMARY, DEPOT]


class Recorder:
    """Sorgu tarafının embedder'a gerçekten ne gönderdiğini tutan sarmalayıcı."""

    def __init__(self, inner: FakeEmbedder) -> None:
        self.inner = inner
        self.sent: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.sent.extend(texts)
        return self.inner.embed(texts)


def search(embedder=None) -> HybridSearch:
    embedder = embedder or FakeEmbedder()
    return HybridSearch(CORPUS, embedder.embed([doc.text for doc in CORPUS]), embedder, RULES)


def without_rules() -> HybridSearch:
    embedder = FakeEmbedder()
    return HybridSearch(CORPUS, embedder.embed([doc.text for doc in CORPUS]), embedder)


def ids(hits) -> list[str]:
    return [hit.doc_id for hit in hits]


# ------------------------------------------------------------------ sorgunun kendisi


def test_the_word_ciro_bring_its_own_rule_synonyms():
    asked = fold(synonym_query(QUERY, RULES))
    assert asked.startswith(fold(QUERY))
    for synonym in CIRO["synonyms"]:
        assert fold(synonym) in asked


def test_a_rule_the_query_never_said_stays_out():
    asked = fold(synonym_query(QUERY, RULES))
    assert "tedarikçi" not in asked and "plasiyer" not in asked


def test_a_word_form_of_the_term_still_lights_the_rule():
    asked = fold(synonym_query("Geçen ayın cirosu ne kadar?", RULES))
    assert fold("satış hasılatı") in asked


def test_a_synonym_already_asked_is_not_counted_twice():
    asked = fold(synonym_query("Bu bölgenin satış geliri ne kadar?", RULES))
    assert asked.count(fold("satış geliri")) == 1


def test_a_query_without_a_business_term_is_untouched():
    assert synonym_query("kaç satır var", RULES) == "kaç satır var"


# ------------------------------------------------------------------ sözcük bacağı


def test_the_base_bm25_leg_misses_the_table_written_with_the_synonym():
    assert ids(search().search(QUERY, method="bm25", rewrite=False)) == ["table:TBLFATUIRS"]


def test_the_rewrite_lifts_that_table_into_the_bm25_leg():
    assert "table:TBLAYLIK" in ids(search().search(QUERY, method="bm25", rewrite=True))


def test_the_rewrite_reaches_the_hybrid_leg_too():
    assert "table:TBLAYLIK" in ids(search().search(QUERY, method="hybrid", rewrite=True))


def test_the_rewrite_does_not_drag_in_an_unrelated_table():
    for method in ("bm25", "hybrid"):
        assert "table:TBLDEPO" not in ids(search().search(QUERY, method=method, rewrite=True))


# ------------------------------------------------------------------ kapalı hali


def test_the_gate_off_is_the_rules_less_search():
    assert search().search(QUERY, method="bm25", rewrite=False) == without_rules().search(
        QUERY, method="bm25"
    )


def test_the_default_follows_the_config_flag():
    assert search().search(QUERY, method="bm25") == search().search(
        QUERY, method="bm25", rewrite=config.SYNONYM_REWRITE
    )


# ------------------------------------------------------------------ vektör bacağı


def test_the_dense_leg_answers_the_same_whatever_the_gate_says():
    leg = search()
    assert leg.search(QUERY, method="dense", rewrite=True) == leg.search(
        QUERY, method="dense", rewrite=False
    )


def test_the_dense_leg_never_sees_the_synonyms():
    embedder = Recorder(FakeEmbedder())
    index = search(embedder)
    embedder.sent.clear()  # korpusun vektörleri sorgu tarafı değil
    index.search(QUERY, method="dense", rewrite=True)
    assert embedder.sent == [QUERY]


def test_the_hybrid_vector_leg_still_asks_the_raw_query():
    embedder = Recorder(FakeEmbedder())
    index = search(embedder)
    embedder.sent.clear()
    index.search(QUERY, method="hybrid", rewrite=True)
    assert embedder.sent == [QUERY]
