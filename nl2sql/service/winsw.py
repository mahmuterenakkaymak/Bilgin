"""WinSW şablonunun doldurulması: ``deploy/windows/bilgin.xml`` -> kurulacak servisin XML'i (R8-22).

Bir Windows servisinin ortamı XML'de yazar, o yüzden burada iki şey birden sabittir. Servisin
ortamı üç anahtardır - NL2SQL_HOME, NL2SQL_LANG, NL2SQL_BACKEND - ve söylenirse ikisi daha
yazılır: NL2SQL_LLM_MODEL, çünkü kurulum betiği model anahtarını hangi profil için mühürlediyse
servis de o adı okumalıdır, ve NL2SQL_DATASETS_DIR. Adı bir sır taşıdığını söyleyen bir anahtar
şablona girse bile reddedilir: R8-23 gereği bağlantı dizesi uygulama veritabanında, model anahtarı
``NL2SQL_HOME/secrets``ta DPAPI blobu olarak durur, ikisinin de XML'de işi yoktur. İkincisi,
doldurulmamış bir boşluk servise bırakılamaz: ``@AD@`` biçimli bir metin çıktıda kalırsa
fırlatılır, yani eksik bir parametre geç kurulmuş bir servis değil kurulmayan bir servis üretir.

Değerler kaçırılarak yazılır - bir kurulum yolu ``&`` taşıyabilir ve işareti XML'i bozar - ve
ekranın cümleleri kataloğun ``service`` satırlarıdır, yani servisin adı hangi dilde kurulduğu
söyler.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from nl2sql import config
from nl2sql.i18n import t

TEMPLATE_PATH = config.ROOT / "deploy" / "windows" / "bilgin.xml"
SERVICE_NAME = "Bilgin"
SERVICE_ACCOUNT = f"NT SERVICE\\{SERVICE_NAME}"
HOST = "127.0.0.1"
DATASETS_ENV_KEY = "NL2SQL_DATASETS_DIR"
MODEL_ENV_KEY = "NL2SQL_LLM_MODEL"

# R8-23: bu köklerden birini taşıyan bir env anahtarı, adı ne kadar masum görünürse görünsün,
# XML'e girmemesi gereken bir değerin habercisidir.
SECRET_ENV = re.compile(r"PASSWORD|KEY|SECRET|CONN|TOKEN", re.IGNORECASE)
_LEFTOVER = re.compile(r"@[A-Z][A-Z0-9_]*@")
_ENV_KEY = re.compile(r'<env\s+key="([^"]*)"')
_ENTITIES = {'"': "&quot;"}


def render_xml(
    python_exe: str | Path,
    repo: str | Path,
    home: str | Path,
    port: int,
    dataset: str,
    lang: str,
    backend: str,
    datasets_dir: str | Path | None = None,
    model: str | None = None,
) -> str:
    """Şablonu doldurur, kaçırılmış tek bir XML metni döndürür (R8-22).

    Servisin çalıştıracağı komut bugünkü ``serve``ın komut satırıdır: döngü adresi sabittir,
    port ve küme kurulacak dünyanın ikisidir. ``datasets_dir`` ve ``model`` söylenmediğinde o
    env satırı hiç yazılmaz - küme kod klasöründe kaldığında servise ayrı bir yol söylemek
    gerekmez, profil de programın kendi varsayılanıdır. Bir profil adı sır değildir; anahtarın
    kendisi ``NL2SQL_HOME/secrets``ta kalır.
    """
    home = Path(home)
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    values = {
        "DISPLAY_NAME": t("service.display_name", lang),
        "DESCRIPTION": t("service.description", lang, host=HOST, port=port, dataset=dataset),
        "PYTHON_EXE": str(python_exe),
        "ARGUMENTS": f"-m nl2sql serve --host {HOST} --port {port} --dataset {dataset}",
        "REPO": str(repo),
        "HOME": str(home),
        "LANG": lang,
        "BACKEND": backend,
        "LOG_DIR": str(home / "logs"),
    }
    for name, value in values.items():
        text = text.replace(f"@{name}@", escape(value, _ENTITIES))
    env = (
        ""
        if datasets_dir is None
        else f'  <env key="{DATASETS_ENV_KEY}" value="{escape(str(datasets_dir), _ENTITIES)}" />\n'
    )
    text = text.replace("  @DATASETS_ENV@\n", env)
    model_env = (
        ""
        if model is None
        else f'  <env key="{MODEL_ENV_KEY}" value="{escape(str(model), _ENTITIES)}" />\n'
    )
    text = text.replace("  @MODEL_ENV@\n", model_env)
    leftover = _LEFTOVER.search(text)
    if leftover:
        raise ValueError(f"şablonda boşluk kaldı: {leftover.group(0)}")
    for key in _ENV_KEY.findall(text):
        if SECRET_ENV.search(key):
            raise ValueError(f"XML'e sır taşıyan bir ortam anahtarı yazılamaz: {key}")
    return text
