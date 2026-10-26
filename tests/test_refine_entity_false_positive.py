"""T364: ``ambiguous_entity`` tek bir varlığı işaret etmeyen soruya şık sormaz (PLAN R7-12).

Eşik "soruda tekil zamir ve bir varlık sözcüğü geçiyor"a bakıyordu; o yüzden "Bu ay hangi ürün en
çok satıldı?" ve "Bu yıl müşteri sayısı?" - ikisi de kendi başına eksiksiz bir soru, oradaki "bu"
dönemi söylüyor - ve çoğul "Bu carilerin toplam faturası ne kadar?" şık yiyordu: kullanıcı kendi
kendine yeten sorusunun cevabını vermemiş, sorguya çekilmiş oluyordu. Burada tek tur elle kurulur -
veritabanı yok, model yok, eşik tek başına sınanır.
"""

import pytest

from nl2sql.agent import refine


def answered_turn():
    """``ambiguous_entity``nin okuduğu alanlar: yanıtlanmış bir turun sql'i ve summary'si."""
    return {
        "sql": "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT",
        "status": "answered",
        "summary": {
            "columns": ["CARI_KOD", "CARI_ISIM"],
            "rows": [["K001", "Anadolu Gıda"], ["K002", "Marmara Market"]],
        },
    }


@pytest.mark.parametrize(
    "question",
    [
        "Bu ay hangi ürün en çok satıldı?",
        "Bu yıl müşteri sayısı?",
        "Bu carilerin toplam faturası ne kadar?",
        "Bu müşterilerin hepsi",
        "Cari yıl hangi müşteri en çok aldı",
    ],
)
def test_a_question_that_points_at_no_single_entity_is_answered_as_it_stands(question):
    assert refine.ambiguous_entity(question, [answered_turn()], None) is None


def test_a_singular_marker_holding_the_entity_still_asks():
    asked = refine.ambiguous_entity("Bu müşteriye başka ne sattık?", [answered_turn()], None)

    assert asked["question"] == "Hangi müşteriyi kastediyorsunuz?"
    assert asked["column"] == "CARI_KOD"
    assert asked["options"] == ["K001 (Anadolu Gıda)", "K002 (Marmara Market)"]
