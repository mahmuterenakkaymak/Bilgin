# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""`python -m nl2sql` giriş noktası: söz dizimi cli.main'de, çıkış kodu burada."""

import sys

from nl2sql.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
