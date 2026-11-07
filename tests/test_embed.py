# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Embedder sözleşmesi: deterministik sahte vektörler, toplara bölünen sıralı istekler, erişilemeyen endpoint.

Ölçümün kendisi tekrarlanabilir olmalı: sahte embedder aynı metne her çalıştırmada aynı vektörü
vermeli (indeks dosyası bir sonraki çalıştırmada anlamsızlaşmasın), gerçek istemci ise 70 metni
32'lik üç isteğe bölüp sırayı korumalı. Sıra bir kez bozulursa doküman ile vektör kayar ve
arama sessizce yanlış tabloyu bulur; bu yüzden sırayı hem toplar arası hem sunucunun kendi
`index` alanı üzerinden sınan. Kapalı uç nokta traceback değil, URL'i söyleyen bir EmbedError.
"""

import math
import socket
import types

import pytest
from openai import APIStatusError

from bilgin import config
from bilgin.index.embed import (
    Embedder,
    EmbedError,
    FakeEmbedder,
    OpenAIEmbedder,
    make_embedder,
)

BASE_URL = "http://127.0.0.1:9/v1"
STUB = config.EmbedSettings(base_url=BASE_URL, model="stub-embed", api_key="test")

TABLE = "stok hareketleri satış faturası depo kodu"
NEAR = "stok hareketleri satış iade faturası"
FAR = "döviz kuru çevrimiçi gösterge tarihi"


def ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def cosine(left: list[float], right: list[float]) -> float:
    """İki vektör de normalize edildiği için nokta çarpımı doğrudan kosinüs benzerliğidir."""
    return sum(a * b for a, b in zip(left, right))


def one_hot(text: str, dim: int = 8) -> list[float]:
    """Her metnin kendi birim vektörü: dönüş sırası buradan okunuyor."""
    vector = [0.0] * dim
    vector[int(text.split("-")[1]) % dim] = 1.0
    return vector


class StubSDK:
    """embeddings.create yerine geçen nesne; istenen topları tutar, verileri isterse ters sıralar."""

    def __init__(self, vector=one_hot, error=None, reverse=False):
        self.vector = vector
        self.error = error
        self.reverse = reverse
        self.calls: list[list[str]] = []
        self.models: list[str] = []
        self.embeddings = ns(create=self._create)

    def _create(self, model, input):
        self.calls.append(list(input))
        self.models.append(model)
        if self.error is not None:
            raise self.error
        data = [ns(index=i, embedding=self.vector(text)) for i, text in enumerate(input)]
        return ns(data=list(reversed(data)) if self.reverse else data)


def stub_embedder(vector=one_hot, batch=config.EMBED_BATCH, reverse=True):
    instance = OpenAIEmbedder(settings=STUB, batch=batch)
    instance._sdk = StubSDK(vector, reverse=reverse)
    return instance


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_error(status=400):
    body = {"error": {"message": "model yok"}}
    response = ns(request=ns(), status_code=status, headers={})
    return APIStatusError("embedding sunucusu hata döndürdü", response=response, body=body)


# ------------------------------------------------------------------ fake embedder

def test_the_same_text_always_gets_the_same_vector():
    embedder = FakeEmbedder()
    first = embedder.embed([TABLE, NEAR])
    assert first == FakeEmbedder().embed([TABLE, NEAR]) == embedder.embed([TABLE, NEAR])
    assert (embedder.id, embedder.dim) == (f"fake:{config.FAKE_EMBED_DIM}", config.FAKE_EMBED_DIM)


def test_moved_words_still_land_in_the_same_buckets():
    """Hash kovaları kelime sırasına bakmaz; torba modelin asıl sırrı bu."""
    assert FakeEmbedder().embed(["cari kod adı"])[0] == FakeEmbedder().embed(["adı kod cari"])[0]


def test_nonempty_vectors_have_unit_length():
    vector = FakeEmbedder(dim=64).embed([TABLE])[0]
    assert len(vector) == 64
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)


def test_text_without_tokens_is_the_zero_vector():
    empty, spaces = FakeEmbedder().embed(["", "   ,.;  "])
    assert set(empty) == {0.0}
    assert all(value == 0.0 for value in spaces)
    assert cosine(empty, FakeEmbedder().embed([TABLE])[0]) == 0.0


def test_shared_words_score_closer_than_unrelated_text():
    embedder = FakeEmbedder()
    table, near, far = embedder.embed([TABLE, NEAR, FAR])
    assert cosine(table, near) > 0.4
    assert cosine(table, far) < 0.1
    assert cosine(table, near) > cosine(table, far)


def test_both_embedders_follow_the_protocol():
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(OpenAIEmbedder(settings=STUB), Embedder)


# ------------------------------------------------------------------ openai embedder

def test_seventy_texts_become_three_requests_in_the_given_order():
    texts = [f"metin-{i}" for i in range(70)]
    instance = stub_embedder()
    vectors = instance.embed(texts)
    assert [len(call) for call in instance._sdk.calls] == [32, 32, 6]
    assert instance._sdk.calls[0] == texts[:32]
    assert instance._sdk.calls[2] == texts[64:]
    assert vectors == [one_hot(text) for text in texts], "vektörler girdi sırasıyla dönmeli"


def test_the_request_carries_the_model_and_the_batch_as_input():
    instance = stub_embedder(batch=4)
    instance.embed([f"metin-{i}" for i in range(5)])
    assert instance._sdk.models == ["stub-embed", "stub-embed"]
    assert instance._sdk.calls[1] == ["metin-4"]
    assert instance.id == "openai:stub-embed"


def test_server_vectors_are_normalized_and_set_the_dim():
    instance = stub_embedder(vector=lambda text: [3.0, 4.0])
    assert instance.embed(["bir metin"]) == [[0.6, 0.8]]
    assert instance.dim == 2


def test_text_list_without_entries_makes_no_request():
    instance = stub_embedder()
    assert instance.embed([]) == []
    assert instance._sdk.calls == []


def test_short_answer_is_an_error_naming_the_url():
    instance = stub_embedder()
    instance._sdk.embeddings = ns(create=lambda model, input: ns(data=[ns(index=0, embedding=[1.0])]))
    with pytest.raises(EmbedError) as caught:
        instance.embed(["metin-0", "metin-1"])
    assert BASE_URL in str(caught.value)


def test_closed_port_is_an_embed_error_naming_the_url():
    url = f"http://127.0.0.1:{closed_port()}/v1"
    instance = OpenAIEmbedder(settings=config.EmbedSettings(url, "stub", "test"))
    with pytest.raises(EmbedError) as caught:
        instance.embed(["stok hareketleri"])
    message = str(caught.value)
    assert "127.0.0.1:" in message and "/v1" in message
    assert "BILGIN_EMBED_BASE_URL" in message


def test_http_error_becomes_an_embed_error_with_the_status():
    instance = OpenAIEmbedder(settings=STUB)
    instance._sdk = StubSDK(error=http_error(400))
    with pytest.raises(EmbedError) as caught:
        instance.embed(["stok hareketleri"])
    assert BASE_URL in str(caught.value)


# ------------------------------------------------------------------ make_embedder

def test_make_embedder_reads_kind_and_id():
    assert make_embedder("fake").id == f"fake:{config.FAKE_EMBED_DIM}"
    assert make_embedder("fake:128").id == "fake:128"
    assert make_embedder("fake:128").dim == 128
    assert make_embedder("openai").id == f"openai:{config.embed_settings().model}"
    assert make_embedder("openai:bge-m3").id == "openai:bge-m3"
    assert make_embedder("openai:bge-m3").model == "bge-m3"


def test_an_unknown_embedder_names_what_is_allowed():
    with pytest.raises(ValueError) as caught:
        make_embedder("claude")
    assert "openai:<model>" in str(caught.value)
    with pytest.raises(ValueError):
        make_embedder("fake:iri")
