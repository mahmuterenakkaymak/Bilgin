# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""wwi_real is the restored WideWorldImporters on SQL Server (BILGIN_BACKEND=mssql, read-only login in
BILGIN_MSSQL_CONN). There is nothing to build or generate: the rows are Microsoft's, and the golden answers are
the golden SQL run on that database."""


def build_db(seed, db_path, sql_path):
    raise SystemExit("wwi_real kurulmaz: gerçek WideWorldImporters SQL Server'da (BILGIN_BACKEND=mssql).")


def generate(seed):
    raise SystemExit("wwi_real üretilmez: satırlar Microsoft'un örnek veritabanından gelir.")


REFERENCES = {}
