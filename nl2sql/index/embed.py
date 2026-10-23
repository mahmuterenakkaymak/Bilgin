"""Metni vektöre çeviren iki kurulum: deterministik sahte embedder ve OpenAI uyumlu endpoint.

Aramanın işe yarayıp yaramadığı ölçülecekse aynı kod hem ağa hiç dokunmadan hem de gerçek bir
embedding sunucusuyla çalışabilmeli; bu yüzden sözleşme tek, kurulum iki. İkisi de L2-normalize
vektör döndürür, böylece aramadaki kosinüs benzerliği bölme işi olmadan nokta çarpımıdır.
Sahte taraf `hash()` yerine md5 kullanır: Python'un `hash()` değeri süreç arasında değiştiği
için indeks dosyası bir sonraki çalıştırmada anlamsızlaşırdı.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from typing import Protocol, runtime_checkable

from openai import APIConnectionError, APIError, OpenAI

from nl2sql import config
from nl2sql.index import text

UNREACHABLE = (
    "Embedding endpoint'ine ulaşılamadı: {url}. Embedding sunucusunun açık olup olmadığına "
    "bakın, gerekirse NL2SQL_EMBED_BASE_URL ile doğru adresi verin."
)
FAILED = "Embedding endpoint'i hatası: {url} ({error})"
SHORT_REPLY = (
    "Embedding endpoint'i eksik yanıt verdi: {url} ({want} metne karşılık {got} vektör)."
)


class EmbedError(RuntimeError):
    """Embedding sunucusu çalışmadı ya da yanıtı çözülemedi; mesaj URL'i ve çözümü söyler."""


@runtime_checkable
class Embedder(Protocol):
    """Metin listesini L2-normalize vektörlere çeviren şey; `id` vektörlerin kimin olduğunu yazar."""

    id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """Ağ yapmayan deterministik embedder: token'ların md5 ile kovalanmış torba modeli (R2-8)."""

    def __init__(self, dim: int = config.FAKE_EMBED_DIM) -> None:
        if dim <= 0:
            raise ValueError(f"dim pozitif bir tam sayı olmalı; verilen: {dim}")
        self.dim = dim
        self.id = f"fake:{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_counts(value, self.dim)) for value in texts]


class OpenAIEmbedder:
    """`/v1/embeddings` (llama.cpp, vLLM, Strata): uzun listeler toplara bölünerek gönderilir."""

    def __init__(
        self,
        settings: config.EmbedSettings | None = None,
        batch: int = config.EMBED_BATCH,
    ) -> None:
        settings = settings or config.embed_settings()
        if batch <= 0:
            raise ValueError(f"batch pozitif bir tam sayı olmalı; verilen: {batch}")
        self.settings = settings
        self.base_url = settings.base_url
        self.model = settings.model
        self.batch = batch
        self.id = f"openai:{settings.model}"
        # ASSUMPTION: genişlik sunucudan gelen ilk vektörden anlaşılır; embed() ilk kez
        # çağrılana kadar dim 0'dır, çünkü istemcide sabit bir genişlik bilgisi yok.
        self._dim = 0
        self._sdk = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=config.EMBED_TIMEOUT_S,
        )

    @property
    def dim(self) -> int:
        """Yanıt vektörlerinin genişliği; ilk istekten önce bilinmiyor."""
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Hepsini döndürür; girdi sırası vektörlerin `index` alanıyla korunur."""
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self.batch):
                vectors.extend(self._create(texts[start:start + self.batch]))
        except APIConnectionError as exc:
            raise EmbedError(UNREACHABLE.format(url=self.base_url)) from exc
        except APIError as exc:
            raise EmbedError(FAILED.format(url=self.base_url, error=exc)) from exc
        if vectors:
            self._dim = len(vectors[0])
        return [_normalize(vector) for vector in vectors]

    def _create(self, chunk: list[str]) -> list[list[float]]:
        response = self._sdk.embeddings.create(model=self.model, input=list(chunk))
        data = list(getattr(response, "data", None) or [])
        if len(data) != len(chunk):
            raise EmbedError(SHORT_REPLY.format(url=self.base_url, want=len(chunk), got=len(data)))
        # index alanı yoksa (yerel sunucuların bazıları) sırasına bırakılıyor.
        ordered = sorted(enumerate(data), key=lambda pair: getattr(pair[1], "index", pair[0]))
        return [list(getattr(item, "embedding", None) or []) for _, item in ordered]


def make_embedder(kind_or_id: str) -> Embedder:
    """'fake', 'fake:256', 'openai' ya da 'openai:<model>' yazan bir metinden embedder kurar.

    Aynı metin `meta.json`'daki `embedder` alanından da gelir; böylece sorgu tarafı indeksle
    aynı vektör uzayını kullandığını yazılımın kendisinden öğrenir.
    """
    kind, _, rest = kind_or_id.partition(":")
    kind = kind.strip().lower()
    rest = rest.strip()
    if kind == "fake":
        if rest and not rest.isdigit():
            raise ValueError(f"Embedding boyutu sayı olmalı: '{kind_or_id}'")
        return FakeEmbedder(int(rest) if rest else config.FAKE_EMBED_DIM)
    if kind == "openai":
        settings = config.embed_settings()
        return OpenAIEmbedder(replace(settings, model=rest) if rest else settings)
    raise ValueError(
        f"Bilinmeyen embedder: '{kind_or_id}'. Geçerli olanlar: fake, fake:<dim>, openai, openai:<model>."
    )


def _counts(value: str, dim: int) -> list[float]:
    """Token başına bir sayı; aynı token hep aynı kovaya düşer."""
    vector = [0.0] * dim
    for token in text.tokens(value):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        vector[int.from_bytes(digest, "big") % dim] += 1.0
    return vector


def _normalize(vector: list[float]) -> list[float]:
    """Uzunluğu 1'e indirir; boş metnin sıfır vektörü olduğu gibi kalır."""
    norm = math.sqrt(sum(value * value for value in vector))
    return vector if norm == 0 else [value / norm for value in vector]
