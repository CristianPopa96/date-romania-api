"""The official totals, for the API tests and the site's browser tests: the Finance
Ministry's workbook of December 2024 as published, the same figures again as if for
September 2026 (no 2026 workbook is kept as a fixture), and Eurostat's COFOG answer for
2023 and 2024."""

import hashlib
from datetime import date
from pathlib import Path

from date_romania.collectors.budget_execution.parse import PARSER_VERSION as EXECUTION_PARSER
from date_romania.collectors.budget_execution.parse import parse as parse_execution
from date_romania.collectors.budget_execution.run import url_of
from date_romania.collectors.cofog.parse import PARSER_VERSION as COFOG_PARSER
from date_romania.collectors.cofog.parse import URL as COFOG_URL
from date_romania.collectors.cofog.parse import parse as parse_cofog
from date_romania.models import BudgetExecution, CofogSpending, SourceDocument

FIXTURES = Path(__file__).parent / "fixtures"
DECEMBER_2024, SEPTEMBER_2026 = date(2024, 12, 31), date(2026, 9, 30)


def _document(session, source: str, url: str, sha: str, parser: int) -> SourceDocument:
    doc = SourceDocument(
        source=source,
        url=url,
        # Hashes of their own: the other seeds take the plain letters.
        sha256=hashlib.sha256(f"national {sha}".encode()).hexdigest(),
        storage_key=f"{source}/{sha}",
        size_bytes=1,
        parser_version=parser,
        rejected_rows=0,
    )
    session.add(doc)
    session.flush()
    return doc


def seed(session) -> None:
    parsed = parse_execution((FIXTURES / "budget_execution_202412.xlsx").read_bytes())
    for period_end, sha in ((DECEMBER_2024, "b"), (SEPTEMBER_2026, "c")):
        doc = _document(session, "budget-execution", url_of(period_end), sha, EXECUTION_PARSER)
        session.add_all(
            BudgetExecution(
                **{**row, "period_end": period_end},
                source_document_id=doc.id,
                parser_version=EXECUTION_PARSER,
            )
            for row in parsed.rows
        )
    cofog = parse_cofog((FIXTURES / "eurostat_cofog.json").read_bytes())
    doc = _document(session, "eurostat-cofog", COFOG_URL, "e", COFOG_PARSER)
    session.add_all(
        CofogSpending(**row, source_document_id=doc.id, parser_version=COFOG_PARSER)
        for row in cofog.rows
    )
    session.flush()
