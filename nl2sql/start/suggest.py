"""Önerilen hazır sorular: model roller soru yazar, ajanın cevaplattıkları onaysız yatar (PLAN R7-20).

Hazır sorunun normal yolu bir yöneticinin onayıdır; öneri ise adaydır. Model şemayı ve iş
kurallarını okuyup her iş rolü için birkaç soru cümlesi yazar, iş parçacığı da her cümleyi
``ask_payload``dan geçirir: cevaplananların SQL'i satıra yazılır, cevaplanmayanlar düşer. Böylece
satırda yürümeyen bir cümle durmaz - onaylayan yönetici yalnız kartın rolüne ve biçimine karar
verir, cümlenin yürüyüp yürümeyeceğini denemez.

İş R6-16'nınki gibi bellektekoşan bir iş parçacıdır: bir düzine koşumu bir HTTP isteği
beklemez. İş kendi oturumunu kendi kurar, yani uygulamanın etkin kümesi işin ortasında değişse
(R6-10) öneri o geçişin üstüne yazmaz.
"""

from __future__ import annotations

import json
import re
import threading
import uuid

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.llm import LLMError
from nl2sql.app.ask import ask_payload
from nl2sql.schema_map import doc
from nl2sql.start.ready import suggest_display

# Öneri koşumunun denetim satırının başı: soru günlüğünde cümleyi modelin yazdığı buradan okunur.
SOURCE = "suggest"
NOT_JSON = "Model önerileri yazmadı: yanıt bir JSON nesnesi değildi."
TOO_FEW = "Model hiçbir iş rolü için yeterli soru yazmadı."

# Modelin sözü sözlüktür, sayısı değil: SUGGEST_PER_ROLEın sınırı koddan kurulur, ısrardan değil.
SYSTEM = f"""Sen bir ERP veritabanı için hazır sorular yazan bir asistansın. Sana iş rolleri, \
tablolar ve iş kuralları veriliyor; sen her rolün panosuna konacak soruları yazıyorsun.

KURALLAR
1. Yalnızca tek bir JSON nesnesi döndür: anahtarlar verilen iş rollerinin kodları, değerleri o \
rolün soracağı Türkçe soru cümlelerinin listesi.
2. Her role en az {config.SUGGEST_PER_ROLE[0]}, en çok {config.SUGGEST_PER_ROLE[1]} soru.
3. Her soru tek cümle ve tek soru işareti taşısun; cevabı kısa bir sayı, bir sıralama ya da kısa \
bir liste olsun - bir karta sığacak kadar.
4. Yalnızca verilen tablo ve kurallarda karşılığı olan şeyleri sor: tablo, kolon ya da terim uydurma.
5. Aynı soruyu iki role yazma.
6. JSON dışında hiçbir şey yazma: açıklama, başlık, madde işareti ve kod bloğu yok.
"""

# Yerel modeller JSONu sık sık bir kabuğun içine koyar; kabuk atılır, içi çöpse red yine reddir.
_FENCE = re.compile(r"^```[a-z]*\s*|\s*```$", re.MULTILINE)


class SuggestError(Exception):
    """Önerinin kurulamadığı yer: cümlesi işin ``message``ı olarak ekrana çıkar."""


def suggest_texts(schema: dict, rules: list, llm) -> dict[str, list[str]]:
    """Tek model çağrısıyla roller için soru cümleleri: ``{rol kodu: [soru]}``.

    Modelin yazdığı liste olduğu gibi kabul edilmez: boşlar ve tekrarlar atılır, ``SUGGEST_PER_ROLE``ın
    üstü kırpılır, altındakalınan rol hiç yoktur - yarım bir rolün tek sorusu panoya konacak bir
    aday değildir. Hiç rol kalmazsa öneri kurulamamıştır, yani ``SuggestError``.
    """
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": _request(schema, rules)},
    ]
    try:
        content = (llm.chat(messages, None).content or "").strip()
    except LLMError as exc:
        # Uç noktanın cümlesi kullanıcının okuduğu cümledir: iş onu aşama satırına taşır.
        raise SuggestError(str(exc)) from None
    raw = _json_object(content)
    if raw is None:
        raise SuggestError(NOT_JSON)
    texts = {}
    for role in config.BUSINESS_ROLES:
        kept = _clean(raw.get(role))
        if kept:
            texts[role] = kept
    if not texts:
        raise SuggestError(TOO_FEW)
    return texts


class SuggestJobs:
    """Öneri işleri: iş parçacığında koşar, aşama bellektedir; ekran ``status``u yoklayarak ilerler."""

    def __init__(self, store, sessions) -> None:
        # ``sessions`` küme adından oturum kurar: iş uygulamanın etkin oturumunu beklemez, bir küme
        # geçişi işin ortasında olsa da kendi dünyasında koşmaya devam eder (R7-20 "no swap").
        self.store = store
        self.sessions = sessions
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def start(self, dataset: str, username: str | None = None) -> dict:
        """İşi kaydedip iş parçacığını bırakır; sözleşmenin iş kaydını döndürür (route onu verir)."""
        job_id = uuid.uuid4().hex
        self._set(job_id, dataset, "asking", 0, 0, None)
        threading.Thread(target=self._run, args=(job_id, dataset, username), daemon=True).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict | None:
        """Sözleşme "suggest job"; hiç başlamamış bir iş için None (route 404 der)."""
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def _run(self, job_id: str, dataset: str, username: str | None) -> None:
        asked = stored = 0
        problem = None
        try:
            session = self.sessions(dataset)
            texts = suggest_texts(session.schema, session.rules, _client(session))
            # Defterin taşıdığı cümle yeniden aday değildir: aynı düğmeye ikinci basmak onay
            # bekleyenlerin üstüne ikiz satır yazmaz - satırın bir tek "Onayla"sı kalır (M24).
            known = {_key(row["question"]) for row in self.store.list_all(dataset)}
            for role, questions in texts.items():
                for question in questions:
                    if _key(question) in known:
                        continue
                    asked += 1
                    payload = ask_payload(session, question, source=SOURCE)
                    # Cevaplanmayan soru aday değildir: netleştirme de hata da satır yazmaz.
                    if payload["status"] == "answered" and payload["sql"]:
                        self.store.add(
                            dataset,
                            role,
                            question,
                            question,
                            payload["sql"],
                            suggest_display(
                                payload["columns"], payload["rows"], payload["chart"]
                            ),
                            created_by=username,
                            approved=False,
                        )
                        known.add(_key(question))
                        stored += 1
                    self._set(job_id, dataset, "asking", asked, stored, None)
        except Exception as exc:  # iş parçacığı buradan öte geçemez; cümle ekrana ulaşmalı
            problem = str(exc) or exc.__class__.__name__
        self._set(job_id, dataset, "failed" if problem else "done", asked, stored, problem)

    def _set(self, job_id: str, dataset: str, phase: str, asked: int, stored: int, message) -> None:
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "dataset": dataset,
                "phase": phase,
                "asked": asked,
                "stored": stored,
                "message": message,
            }


def _client(session):
    """Öneriyi yazan istemci: fake kümenin altın sorularını roller arasında dağıtır, gerçek uç nokta
    şemayı okur (R7-20) - sahte öneriler de gerçekten yürüyen sorulardır."""
    if session.llm_kind == "fake":
        golden = session.dataset.golden() if session.dataset else ()
        return fake.suggest_client(golden, config.BUSINESS_ROLES)
    return session.agent_llm("full")


def _request(schema: dict, rules: list) -> str:
    """Modelin önüne konan dünya: roller, tablolar ve iş terimleri - kolon dökümü değil."""
    parts = [
        "İŞ ROLLERİ (JSONun anahtarları bunlar):",
        "\n".join(f"- {code}: {display}" for code, display in config.BUSINESS_ROLES.items()),
        "",
        "TABLOLAR:",
        doc.compact_text(schema),
    ]
    terms = [
        f"- {rule.get('term')}: {rule.get('definition') or ''}".rstrip(" :")
        for rule in rules
        if rule.get("term")
    ]
    if terms:
        parts += ["", "İŞ KURALLARI:", "\n".join(terms)]
    return "\n".join(parts)


def _clean(value) -> list[str]:
    """Bir rolün listesi: olmayan liste boş sayılır, tekrarlar ve boşlar atılır, üst sınır kırpılır."""
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        text = " ".join(item.split()) if isinstance(item, str) else ""
        if text and text not in texts:
            texts.append(text)
    if len(texts) < config.SUGGEST_PER_ROLE[0]:
        return []
    return texts[: config.SUGGEST_PER_ROLE[1]]


def _key(question: str) -> str:
    """Adayla satırın aynı cümle olup olmadığı: boşluk ve büyük/küçük harf farkı sayılmaz."""
    return " ".join(question.split()).casefold()


def _json_object(text: str) -> dict | None:
    """Modelin döndürdüğü tek JSON nesnesi; kabuğu ya da çöpü None, yani red."""
    try:
        raw = json.loads(_FENCE.sub("", text))
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None
