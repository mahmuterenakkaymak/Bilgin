# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T346: kaydırılan gezinme satırı devamı olduğunu kendisi söylemeli (M21 görsel inceleme 1).

390px'te sıra bilerek kaydırılıyor: `overflow-x: auto`, çubuğu hem `scrollbar-width: none` hem
`::-webkit-scrollbar` ile gizli. Varsayım "kesilen ad devamı anlatır"dı; anlatmıyor — "Veritabanı
haritası" "Veritabanı harita" olarak basılıyor ve satır o anki sayfada açıldığı için soldaki
"Sor" ile "Kurallar" hiç yok sayılıyor (users-screen-users-table-390.png,
rules-screen-validation-390.png). Satır tek ve kaydırık kalıyor; taşan tarafın devamını maskenin
gradyanı üstleniyor. İddia kaynak CSS'te kurulur — ölçülen yazarın niyeti, küçültücünün metni
değil — ve aynı okuma T272'nin gezinme satırını kuran yardımcılarından gelir.
"""

from test_web_masthead_css import effective

# Maske taşan kenarda "buradan devam ediyor" dedirtecek kadar koyulaşmalı: gradyan + şeffaf durak.
GRADIENT = "gradient("


def fade_of(nav: dict[str, str]) -> str:
    """Kazanan `.masthead-nav` bildirimlerindeki maske: standart ad, yoksa WebKit ikizi."""
    for prop in ("mask-image", "-webkit-mask-image"):
        if nav.get(prop):
            return nav[prop]
    return ""


def test_the_overflowing_edge_fades():
    """Kesik kenar yazım hatası değil, devam işareti okunmalı: satırın taşan tarafında şeffaflaşa
    bir gradyan var mı — kaydırma çubuğu gösterilmeden de anlaşılan tek ipucu bu."""
    nav = effective(".masthead-nav")
    fade = fade_of(nav)
    assert fade, f".masthead-nav taşan kenarı hiç karartmıyor, kesik ad kesik kalıyor: {nav}"
    assert GRADIENT in fade, f"maske gradyan değil, kenar sert kesilir: {fade!r}"
    assert "transparent" in fade, f"gradyan şeffaflaşmıyor, devamı söylemez: {fade!r}"


def test_the_fade_is_not_paid_with_wrapping():
    """Fade taşmayı gizler, çözmez: bağlantı esnerse uzun ad kendi içinde kırılır ve satır yine
    ikinci kata çıkar — kaydırılacak sıra kalmaz, maske boş bir kenarı karartır."""
    link = effective(".nav-link")
    assert link.get("flex", "") == "none", (
        f".nav-link flex none değil: bağlantı esneyip kırılıyor, kaydırılan satır bozuluyor: {link}"
    )
