"""CLI'nin dili (R8-5): ``--lang {tr,en}`` üst parserda ve her alt komutta; yardım metni katalogdan.

Test üç şeyi sabitler: İngilizce yardım Türkçe harf taşımaz, Türkçe yardım bugünle aynı metindir
(yalnız ``--lang`` satırı ve kullanım satırının yeniden sarılması eklenir), her alt komut ``--lang
en``i kabul eder ve ``NL2SQL_LANG=en`` bayrak olmadan İngilizce yardım verir. Karşılaştırma
makineden bağımsız olsun diye yardım gövdesinden kullanım bloğu ve ``--lang`` satırları düşürülür,
boşluklar katlanır ve makineye özel ``models.json`` yolu düzleştirilir.
"""

import argparse
import contextlib
import io
import re

import pytest

from nl2sql.cli import main as cli

TURKISH = set("çğıöşüÇĞİÖŞÜ")
PARSERS = {"top": [], "ask": ["ask"], "eval": ["eval"], "serve": ["serve"], "user_add": ["user", "add"]}


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch):
    """Yardım 100 sütunda sarılır; gövde karşılaştırması zaten genişlikten bağımsız, bu emniyet kemeri."""
    monkeypatch.setenv("COLUMNS", "100")


# Updated automatically: T417 changed this contract (the `template` subcommand joins the top-level help).
# Bugünün (R8-5 öncesi) yardımı: Türkçe yardımın değişmediğini kanıtlayan altın metin.
TODAY_HELP = {
    "top": r"""usage: python -m nl2sql [-h]
                        {build-db,build-index,eval-retrieval,import-map,introspect,diff-map,merge-map,make-login-script,template,ask,serve,user,eval}
                        ...

NL -> T-SQL ölçüm aracı.

positional arguments:
  {build-db,build-index,eval-retrieval,import-map,introspect,diff-map,merge-map,make-login-script,template,ask,serve,user,eval}
    build-db            sentetik veritabanını ve T-SQL betiğini kurar
    build-index         şema ve kurallardan arama indeksini kurar
    eval-retrieval      altın sorularında aramanın geri çağırmasını ölçer
    import-map          Excel şema haritasını eşler; --accept ile şemayı yazar
    introspect          veritabanını yoklar ve iskelet şemayı yazar
    diff-map            Excel haritası ile veritabanını karşılaştırır, farkı diff.json/md yazar
    merge-map           Excel haritası ile veritabanını birleştirir, şemayı --outa yazar
    make-login-script   salt okunur MSSQL giriş betiğini üretir ve yazar
    template            doldurulacak boş şablonu yazar; --dataset iskeleti o kümenin şemasından
                        doldurur
    ask                 tek bir soruyu modelden geçirip cevabı gösterir
    serve               web API'sini ve arayüzü kendi makinesine bağlı çalıştırır
    user                kullanıcı hesaplarını listeler, açar, değiştirir
    eval                altın soruları koşar ve raporu yazar

options:
  -h, --help            show this help message and exit
""",
    "ask": r"""usage: python -m nl2sql ask [-h] [--llm {fake,openai}] [--mode {full,full_rules,rag,auto}]
                            [--json] [--choice SEÇENEK] [--conversation ID | --new]
                            [--model PROFIL] [--models-file DOSYA.json] [--dataset AD]
                            question

positional arguments:
  question              Türkçe soru, örn. "Geçen ayın cirosu ne kadar?"

options:
  -h, --help            show this help message and exit
  --llm {fake,openai}   istem kaynağı (varsayılan openai)
  --mode {full,full_rules,rag,auto}
                        bağlam modu (varsayılan auto)
  --json                yalnız cevabın JSON'unu yazdır (web API ile aynı tek kapı)
  --choice SEÇENEK      netleştirme şıkkı: soruyu seçilen anlamıyla koşar, yeniden sormaz
  --conversation ID     soruyu bu konuşmanın devamı olarak sor (önceki turlar bağlama girer)
  --new                 yeni bir konuşma aç ve kimliğini son satırda söyle
  --model PROFIL        config/models.json profili (varsayılan: http://127.0.0.1:8080/v1)
  --models-file DOSYA.json
                        --model için profil dosyası (varsayılan
                        C:\Users\PC\Documents\GitHub\nl2sql\config\models.json)
  --dataset AD          veri kümesi adı (varsayılan: synthetic_erp)
""",
    "eval": r"""usage: python -m nl2sql eval [-h] [--llm {fake,openai}] [--only Q03 [Q03 ...]]
                             [--tag archive [archive ...]] [--mode {full,full_rules,rag,auto}]
                             [--compare] [--fresh] [--models A,B] [--modes M1,M2] [--repeat N]
                             [--schema DOSYA|full|skeleton] [--ambiguous] [--narrate]
                             [--followups] [--model PROFIL] [--models-file DOSYA.json]
                             [--dataset AD]

options:
  -h, --help            show this help message and exit
  --llm {fake,openai}   istem kaynağı (varsayılan openai)
  --only Q03 [Q03 ...]  yalnız bu soru kimlikleri (boşlukla ayrılır)
  --tag archive [archive ...]
                        yalnız bu etiketlerden birini taşıyan sorular (boşlukla ayrılır)
  --mode {full,full_rules,rag,auto}
                        bağlam modu (varsayılan full); auto yalnız ask'ta
  --compare             üç modu aynı sorularda koşar ve tek raporda karşılaştırır
  --fresh               --compare ile yeniden koşmayan modları da koşar
  --models A,B          --compare ile model x mod karşılaştırması: virgülle ayrılmış profil adları
  --modes M1,M2         --models ile koşulacak modlar (varsayılan full_rules,rag)
  --repeat N            --compare ile her modu N kez koşar ve gürültüyü ölçer (varsayılan 1)
  --schema DOSYA|full|skeleton
                        ölçümün şeması: tam ad ya da yol (varsayılan full)
  --ambiguous           altın sorulara kümenin belirsiz setini de katıp netleştirme metriklerini
                        ölçer
  --narrate             gönderilen her altın cevabı anlatıp anlatıcının kaynağını sayar
  --followups           altın koşumun ardına kümenin ardışık soru zincirlerini konuşmadan geçirip
                        bağlamı ölçer
  --model PROFIL        config/models.json profili (varsayılan: http://127.0.0.1:8080/v1)
  --models-file DOSYA.json
                        --model için profil dosyası (varsayılan
                        C:\Users\PC\Documents\GitHub\nl2sql\config\models.json)
  --dataset AD          veri kümesi adı (varsayılan: synthetic_erp)
""",
    "serve": r"""usage: python -m nl2sql serve [-h] [--host HOST] [--port PORT] [--llm {fake,openai}]
                              [--model PROFIL] [--models-file DOSYA.json] [--dataset AD]

options:
  -h, --help            show this help message and exit
  --host HOST           bağlanılacak adres (yalnız 127.0.0.1, localhost)
  --port PORT           bağlanılacak port (varsayılan 8777)
  --llm {fake,openai}   istem kaynağı (varsayılan openai)
  --model PROFIL        config/models.json profili (varsayılan: http://127.0.0.1:8080/v1)
  --models-file DOSYA.json
                        --model için profil dosyası (varsayılan
                        C:\Users\PC\Documents\GitHub\nl2sql\config\models.json)
  --dataset AD          veri kümesi adı (varsayılan: synthetic_erp)
""",
    "user_add": r"""usage: python -m nl2sql user add [-h] [--role {admin,user}]
                                 [--business-role {satis,satin_alma,muhasebe,yonetim,genel}]
                                 AD

positional arguments:
  AD

options:
  -h, --help            show this help message and exit
  --role {admin,user}   rol (varsayılan user)
  --business-role {satis,satin_alma,muhasebe,yonetim,genel}
                        iş rolü (varsayılan genel)
""",
}


def _parser(parser, path):
    for name in path:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                parser = action.choices[name]
                break
    return parser


def _render(lang, path):
    return _parser(cli.build_parser(lang), path).format_help()


def _body(text):
    """Kullanım bloğunu ve ``--lang`` satırlarını düşür, boşlukları katla, makine yolunu düzleştir."""
    text = text.split("\n\n", 1)[-1]
    text = "\n".join(line for line in text.splitlines() if "--lang" not in line)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\S*models\.json", "<M>", text).strip()


def _stdout_of(argv):
    buffer = io.StringIO()
    with contextlib.suppress(SystemExit), contextlib.redirect_stdout(buffer):
        cli.main(argv)
    return buffer.getvalue()


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_en_help_has_no_turkish_letter(name):
    help_text = _render("en", PARSERS[name])
    assert not set(help_text) & TURKISH, sorted(set(help_text) & TURKISH)


@pytest.mark.parametrize("name", sorted(PARSERS))
def test_tr_help_equals_todays_text(name):
    assert _body(_render("tr", PARSERS[name])) == _body(TODAY_HELP[name])


def test_every_subcommand_has_a_lang_option():
    parser = cli.build_parser("en")
    subcommands = [p for p in _walk(parser) if p is not parser]
    assert subcommands
    for sub in subcommands:
        assert any("--lang" in action.option_strings for action in sub._actions)


def _walk(parser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _walk(sub)


@pytest.mark.parametrize(
    "argv",
    [
        ["build-db", "--lang", "en"],
        ["build-index", "--lang", "en"],
        ["eval-retrieval", "--lang", "en"],
        ["import-map", "h.xlsx", "--lang", "en"],
        ["introspect", "--lang", "en"],
        ["diff-map", "--excel", "s.json", "--db", "--lang", "en"],
        ["merge-map", "--excel", "s.json", "--db", "--lang", "en"],
        ["make-login-script", "--lang", "en"],
        ["ask", "soru", "--lang", "en"],
        ["serve", "--lang", "en"],
        ["eval", "--lang", "en"],
        ["user", "add", "ada", "--lang", "en"],
        ["user", "list", "--lang", "en"],
        ["user", "passwd", "ada", "--lang", "en"],
        ["user", "set", "ada", "--role", "user", "--lang", "en"],
    ],
)
def test_every_subcommand_accepts_lang_en(argv):
    # tr parserında bayrağı veriyoruz: varsayılanı ezip en olduğundan ``lang`` "en" olmalı.
    assert cli.build_parser("tr").parse_args(argv).lang == "en"


def test_lang_flag_at_top_level_is_stored_for_the_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "build_database", lambda **kwargs: seen.update(kwargs) or 0)
    assert cli.main(["--lang", "en", "build-db"]) == 0
    assert seen == {}


@pytest.mark.parametrize("argv,expected", [(["--lang", "en"], "en"), (["--lang=en"], "en"), ([], "tr")])
def test_scan_lang_reads_the_flag(argv, expected):
    assert cli._scan_lang(argv) == expected


def test_scan_lang_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("NL2SQL_LANG", "en")
    assert cli._scan_lang([]) == "en"
    assert cli._scan_lang(["--lang", "fr"]) == "en"  # tanınmayan değer ortama düşer


def test_env_lang_en_without_flag_gives_en_help(monkeypatch):
    monkeypatch.setenv("NL2SQL_LANG", "en")
    assert not set(_stdout_of(["--help"])) & TURKISH


def test_flag_en_without_env_gives_en_help():
    assert not set(_stdout_of(["--help", "--lang", "en"])) & TURKISH


def test_default_help_is_turkish():
    assert set(_stdout_of(["--help"])) & TURKISH
