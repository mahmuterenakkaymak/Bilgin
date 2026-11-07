# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T350: telefon başlığı etkin veri kümesini adıyla söylemeli (M21 görsel inceleme 5).

#model-chip tek bir dizi basıyordu: ad + parantez içi + model birleşip tek metin oluyordu,
telefon bloğu da çipi `max-width: 7rem`'de kesiyordu. 390px'te başlık "Sentetik ERP (…" ve
küme geçtikten sonra "ornek_fatura ·…" diyor (landing-empty-state-390.png,
admin-map-onboard-map-name-taken-390.png) — üç nokta, bir kümeyi diğerinden ayıran tarafı
yiyor; oysa başlık her sayının hangi veritabanından geldiğini söyleyen tek yer. Çip artık iki
yuva: ad ve `.chip-note` (parantez içi ile model), tamamı çipin title'ında. İddia kaynak CSS'te
kurulur — ölçülen yazarın niyeti, küçültücünün metni değil — okuma T272'nin yardımcısından gelir.
"""

from test_web_masthead_css import effective


def test_the_qualifier_steps_aside_for_the_name():
    """Dar ekranda çipin yükü ad: nitelik satırda kalırsa ellipsis yine adı yer. `.chip-note`
    390'da display none olmalı ki sütunun payı kümenin kendisine kalsın."""
    note = effective(".masthead .chip-note")
    assert note.get("display") == "none", (
        f".chip-note dar ekranda gizlenmiyor ({note or 'kural yok'}): üç nokta adı yemeye devam eder"
    )


def test_the_name_keeps_its_right_to_shrink():
    """Nitelik kalkınca ad sütunun tamamını ister: küçülme hakkı olmazsa uzun ad sütunu şişirir,
    satır taşar ve başlık üçüncü kata çıkar. Burada tavan değil taban gerekiyor — ellipsis
    çalışsın diye min-width sıfıra iner."""
    chip = effective("#model-chip")
    assert chip.get("min-width") == "0", (
        f"#model-chip min-width'ı sıfıra inmiyor: {chip} — uzun ad satırı taşırır"
    )
