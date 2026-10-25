"""R2-16: indeks dokümanı altın soruyu tekrar edemez - kaçaklı bir retrieval'ın skoru yalandır.

Dokümanın kendisi de iki iddia taşır: şema ve kural dosyalarındaki her şey bir dokümandır (83 tablo
+ 15 kural), ve hiçbir doküman hangi tablonun dolgu olduğunu söyleyen `kind` bayrağını sızdırmaz.
"""

from nl2sql.eval.runner import load_golden
from nl2sql.index import text
from nl2sql.index.docs import COLLECTIONS, Doc, build_documents, leaks
from nl2sql.schema_map.doc import load_schema
from nl2sql.schema_map.rules import load_rules

SCHEMA = load_schema()
RULES = load_rules()
DOCS = build_documents(SCHEMA, RULES)
GOLDEN = load_golden()

PLANTED = Doc(
    id="table:FATURA",
    collection="tables",
    title="FATURA",
    text="Fatura başlıkları. İptal edilmemiş satış faturalarının toplam tutarı ciro olarak hesaplanır.",
)


def test_one_doc_per_table_and_rule():
    assert len(DOCS) == len(SCHEMA["tables"]) + len(RULES)
    assert [doc.id for doc in DOCS] == [f"table:{t['name']}" for t in SCHEMA["tables"]] + [
        f"rule:{rule['id']}" for rule in RULES
    ]


def test_examples_collection_exists_but_stays_empty():
    # summaries since T190
    assert COLLECTIONS == ("tables", "rules", "summaries", "examples")
    assert {doc.collection for doc in DOCS} == {"tables", "rules"}


def test_meta_follows_the_contract_per_collection():
    tables = [doc for doc in DOCS if doc.collection == "tables"]
    rules = [doc for doc in DOCS if doc.collection == "rules"]
    assert all(set(doc.meta) == {"table", "module"} for doc in tables)
    assert all(set(doc.meta) == {"term", "tables"} for doc in rules)
    assert tables[0].title == tables[0].meta["table"]
    assert rules[0].title == rules[0].meta["term"]


def test_leaks_finds_a_question_copied_verbatim():
    question = {"id": "X01", "question": "İptal edilmemiş satış faturalarının toplam tutarı ciro olarak hesaplanır"}
    assert leaks([PLANTED], [question]) == [("X01", "table:FATURA")]


def test_leaks_finds_a_shared_six_token_window_inside_a_longer_sentence():
    question = {"id": "X02", "question": "Şöyle bir şey var: iptal edilmemiş satış faturalarının toplam tutarı ne kadar"}
    assert leaks([PLANTED], [question]) == [("X02", "table:FATURA")]


def test_a_question_sharing_nothing_is_not_a_leak():
    assert leaks([PLANTED], [{"id": "X03", "question": "Ankara'daki alıcı cariler hangileri"}]) == []


def test_the_real_golden_set_leaks_nothing_into_the_real_index():
    assert leaks(DOCS, GOLDEN) == []
