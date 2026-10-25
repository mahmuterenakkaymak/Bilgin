"""`python -m nl2sql` giriş noktası: söz dizimi cli.main'de, çıkış kodu burada."""

import sys

from nl2sql.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
