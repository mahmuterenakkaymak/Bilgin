# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

import importlib


def test_packages_import():
    for name in [
        "bilgin",
        "bilgin.schema_map",
        "bilgin.policy",
        "bilgin.engine",
        "bilgin.agent",
        "bilgin.eval",
        "bilgin.cli",
        "eval",
    ]:
        importlib.import_module(name)
