"""Data model, one module per source. Every table is imported here, so Alembic sees all of them."""

from date_romania.models.core import (
    DONE,
    FAILED,
    PARTIAL,
    RUNNING,
    SUCCEEDED,
    Base,
    Entity,
    JobRun,
    SourceDocument,
    done_days,
    search_text,
)
from date_romania.models.eu_projects import EuProject, EuProjectPayment, EuSeapLink
from date_romania.models.places import (
    AnafRecord,
    LocalBudget,
    Place,
    Population,
    PublicEntity,
)
from date_romania.models.pnrr import (
    PnrrContract,
    PnrrContractLine,
    PnrrEdition,
    PnrrMeasure,
    PnrrPayment,
    PnrrTopRecipient,
)
from date_romania.models.programme import ExportBuyer, ExportContract, PniasLink, PniasPayment
from date_romania.models.reports import Report
from date_romania.models.seap_awards import (
    AwardContract,
    AwardNotice,
    AwardNoticeDetail,
    AwardNoticeVersion,
    AwardWinner,
)
from date_romania.models.seap_direct import (
    DirectPurchase,
    DirectPurchaseDetail,
    DirectPurchaseItem,
)

__all__ = [
    "DONE",
    "FAILED",
    "PARTIAL",
    "RUNNING",
    "SUCCEEDED",
    "done_days",
    "search_text",
    "Base",
    "SourceDocument",
    "JobRun",
    "Entity",
    "DirectPurchase",
    "DirectPurchaseDetail",
    "DirectPurchaseItem",
    "AwardNotice",
    "AwardContract",
    "AwardWinner",
    "AwardNoticeDetail",
    "AwardNoticeVersion",
    "PniasPayment",
    "ExportContract",
    "ExportBuyer",
    "PniasLink",
    "Report",
    "Place",
    "PublicEntity",
    "LocalBudget",
    "Population",
    "AnafRecord",
    "PnrrEdition",
    "PnrrMeasure",
    "PnrrContract",
    "PnrrContractLine",
    "PnrrPayment",
    "PnrrTopRecipient",
    "EuProject",
    "EuProjectPayment",
    "EuSeapLink",
]
