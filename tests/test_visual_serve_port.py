"""T473: görsel koşu portu boşaltmadan başlamaz (M27 incelemesinin kırmızısı).

``scripts/visual_serve.py`` portu ``serve``a devretmeden önce kendisi dener: orada bir şey
dinliyorsa kum havuzunu silmez ve çocuk süreci açmaz. Ölçüm gerçek bir soketle yapılır, çünkü
kusurun kendisi bind'in sorulmamış olmasıydı -- 2026-10-27'deki M27 koşusu portu tutan eski bir
sunucuyu koştu ve 136 karenin hiçbiri o günün İngilizcesini göstermedi.
"""

import socket
import subprocess
import sys
from pathlib import Path

from scripts import visual_serve

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "visual_serve.py"


def test_a_taken_port_stops_the_run_before_the_sandbox_is_wiped():
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]

    # İşaret hazırlığın sildiği yere yazılır: ``prepare``ın rmtree'si oradan geçiyor, yani kalan
    # dosya "hiçbir şey silinmedi"nin ölçüsüdür. ``data/visual``ın kökü silinmediği için orada
    # duran bir dosya hiçbir şeyi kanıtlamazdı.
    marker = visual_serve.real_datasets_dir() / "T473-isaret.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("bu kosu silinmemeli", encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--port", str(port)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=ROOT,
        )

        assert proc.returncode != 0, f"port doluyken koşu yine de başladı: {proc.stdout[-500:]}"
        # ``serve``ın kendi hatası da portu söyler ("Bilgin: http://127.0.0.1:<port>", sonra 10048);
        # ölçülen betiğin portu daha çocuğa sormadan yazdığı satır.
        assert f"Port {port}" in proc.stdout, "betik portu hazırlıktan önce söylemiyor: " + proc.stdout
        assert marker.is_file(), "port doluyken kum havuzu silinmiş"
    finally:
        holder.close()
        marker.unlink(missing_ok=True)
