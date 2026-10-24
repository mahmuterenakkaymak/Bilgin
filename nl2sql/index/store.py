"""İndeksin diske yazılıp okunması ve bayatlığın reddedilmesi (PLAN R2-9).

Bir indeks iki parçalı: dokümanlar ve onlarla aynı sıradaki vektörler. Sıra bozulursa skor
yanlış dokümana bağlanır, bu yüzden vektör sayısı doküman sayısına eşit olmak zorunda. Bayatlık
ise sessizce tolere edilmez: şema değişmişken eski vektörlerle arama yapmak, bulunamayan tabloyu
modelin hatası gibi gösterir. O yüzden yükleyici beklenen imzayı ister ve tutmazsa yükseltir.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from nl2sql import config
from nl2sql.index.docs import COLLECTIONS, Doc

DOCS_FILE = "docs.json"
VECTORS_FILE = "vectors.json"
META_FILE = "meta.json"

# R4-14: küme söylenmişse çözümü söyleyen komut da o kümeyi hedefler; adsız hali sentetik dünyanın
# indeksini kurar, yani `--dataset wwi` ile çalışan birine hiçbir şey kazandırmaz.
MISSING = "İndeks bulunamadı: {path}. Önce `python -m nl2sql build-index{ds}` çalıştırın."
STALE = "İndeks eski: `python -m nl2sql build-index{ds}` çalıştırın."
# R4-8: indeks hangi veri kümesinin şemasını vektörlediğini meta'da taşır. Uyuşmazlık bayatlıktan daha
# spesifik bir arıza, ama çözümü aynı komutun bir hali; o yüzden mesajı kendi, sınıfı StaleIndexError.
FOREIGN = (
    "İndeks başka veri kümesine ait: {stored} (istenen {wanted}); "
    "`python -m nl2sql build-index --dataset {wanted}` çalıştırın."
)
# ASSUMPTION: sayı uyuşmazlığı bozuk değil bayat bir indeks işaretidir; çözümü aynı komut olduğu
# için ayrı bir hata sınıfı yerine StaleIndexError'ın kendi mesajıyla yükseltiliyor.
COUNTS = (
    "İndeks bozuk: {docs} dokümana karşılık {vectors} vektör var. "
    "`python -m nl2sql build-index` çalıştırın."
)


def dataset_arg(dataset: str | None) -> str:
    """Kurtarma cümlesindeki komutun `--dataset AD` eklentisi; küme söylenmediyse boş (R4-14)."""
    return f" --dataset {dataset}" if dataset else ""


class MissingIndexError(RuntimeError):
    """İndeks dosyaları diskte yok; mesaj hangi komutun ürettiğini söylüyor."""


class StaleIndexError(RuntimeError):
    """İndeks içindekilerden (veya vektör sırasından) eski; yeniden kurulmalı."""


class ForeignIndexError(StaleIndexError):
    """İndeks başka bir veri kümesi için kurulmuş; kendi kümesinin yerine yüklenmemeli."""


@dataclass
class StoredIndex:
    """Diskten okunan üçlünün birlikte taşınması: vektörler `docs` sırasıyla aynı indekstedir."""

    docs: list[Doc]
    vectors: list[list[float]]
    meta: dict = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """İndeksi bir yere yazıp oradan okuyan şey; `meta` içeriğin imzasını ve embedder'ı taşır."""

    def save(
        self, docs: list[Doc], vectors: list[list[float]], meta: dict | None = None
    ) -> None: ...

    def load(self) -> StoredIndex: ...


class FileStore:
    """`index/` altına docs.json, vectors.json, meta.json yazan depo.

    Her dosya önce yanında bir geçici dosyaya yazılıp sonra üzerine taşınır (os.replace atomik):
    yarı yazılmış bir indeks, boş bir indeksten daha tehlikelidir.
    """

    def __init__(self, directory: str | Path = config.INDEX_DIR) -> None:
        self.directory = Path(directory)

    def save(
        self, docs: list[Doc], vectors: list[list[float]], meta: dict | None = None
    ) -> None:
        """Üç dosyayı yazar; vektör sayısı doküman sayısından farklıysa hiçbir şey yazılmaz."""
        _check_counts(docs, vectors)
        self.directory.mkdir(parents=True, exist_ok=True)
        _write(self.directory / DOCS_FILE, [asdict(doc) for doc in docs])
        _write(self.directory / VECTORS_FILE, [[float(v) for v in vector] for vector in vectors])
        _write(self.directory / META_FILE, _meta(docs, meta or {}))

    def load(self, dataset: str | None = None) -> StoredIndex:
        """Üç dosyayı okur; eksikse MissingIndexError, sıra bozuksa StaleIndexError.

        `dataset` içeriği değiştirmez, yalnız eksiklik cümlesinin önereceği komuta girer (R4-14).
        """
        docs = [
            Doc(
                id=item["id"],
                collection=item["collection"],
                title=item["title"],
                text=item["text"],
                meta=item.get("meta") or {},
            )
            for item in self._read(DOCS_FILE, dataset)
        ]
        vectors = [[float(v) for v in vector] for vector in self._read(VECTORS_FILE, dataset)]
        meta = self._read(META_FILE, dataset)
        _check_counts(docs, vectors)
        return StoredIndex(docs=docs, vectors=vectors, meta=meta)

    def load_checked(self, expected_hash: str, dataset: str | None = None) -> StoredIndex:
        """Yükle ve imzayı doğrula: şema veya kurallar değişmişse yüklenmiş sayılmaz (R2-9).

        `dataset` verildiğinde aidiyet de doğrulanır (R4-8): başka bir kümenin şemasıyla vektörlenmiş
        indeks, imzası uyuşsa bile yanlış tablolarla aramak demektir. Anahtarsız eski meta tek küme
        devrinin ürünüdür, yani `synthetic_erp`.
        """
        # ASSUMPTION: dataset=None aidiyetin sorgulanmadığı anlamına gelir; --dataset'i henüz
        # taşımayan çağrılar eski davranışla devam etsin diye.
        index = self.load(dataset)
        stored = index.meta.get("dataset") or config.DEFAULT_DATASET
        if dataset is not None and stored != dataset:
            raise ForeignIndexError(FOREIGN.format(stored=stored, wanted=dataset))
        found = index.meta.get("content_hash", "")
        if found != expected_hash:
            raise StaleIndexError(STALE.format(ds=dataset_arg(dataset)))
        return index

    def _read(self, name: str, dataset: str | None = None) -> list | dict:
        path = self.directory / name
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise MissingIndexError(
                MISSING.format(path=path, ds=dataset_arg(dataset))
            ) from exc


def content_hash(schema: dict, rules: list[dict]) -> str:
    """Şema + kuralların kanonik JSON'unun sha256'sı; anahtar sırası ve biçim imzayı değiştirmez."""
    canonical = json.dumps(
        {"schema": schema, "rules": rules},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _meta(docs: list[Doc], meta: dict) -> dict:
    """Verilen imzayı korur; eksik kalan built_at ve koleksiyon sayılarını dokümanlardan doldurur."""
    filled = dict(meta)
    filled.setdefault(
        "built_at", datetime.now().astimezone().isoformat(timespec="seconds")
    )
    filled.setdefault(
        "counts",
        {name: sum(1 for doc in docs if doc.collection == name) for name in COLLECTIONS},
    )
    return filled


def _check_counts(docs: list[Doc], vectors: list[list[float]]) -> None:
    if len(docs) != len(vectors):
        raise StaleIndexError(COUNTS.format(docs=len(docs), vectors=len(vectors)))


def _write(path: Path, data) -> None:
    """JSON'u önce .tmp'ye yaz, süpür, sonra gerçek dosyanın üzerine taş."""
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
