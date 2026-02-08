from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_CANONICAL_FIELDS = [
    "country",
    "jurisdiction",
    "netting",
    "date_of_opinion_review",
    "next_review_date",
    "reviewer_name",
    "counterparty_types_included",
    "counterparty_type_notes_qualification",
    "counterparty_type_comment",
    "top_up_opinion_date",
    "top_up_opinion_date_comments",
    "additional_covered_counterparties_top_up_opinion",
    "additional_covered_products_top_up_opinion",
    "counterparty_types_excluded",
    "transaction_types_included",
    "transaction_types_excluded",
    "governing_law_of_agreement_covered_by_opinion",
    "automatic_early_termination_applicable",
    "early_termination_enforceable",
    "early_termination_notes",
    "closeout_netting_enforceable",
    "closeout_netting_margin_rules_exemptions_if_not_enforceable",
    "closeout_netting_notes",
    "netting_legislation_exists",
    "excluded_transaction_types_allowed",
    "second_method_assumed",
    "first_method_enforceable",
    "inclusion_of_branch_in_non_netting_country_allowed",
    "multibranch_local_branch",
    "foreign_currency_termination_amount_allowed",
    "termination_amount_currency_if_not_allowed",
    "amendment_recommended_counterparty_type",
    "amendment_notes_for_counterparty_type",
    "link_to_opinion",
]


DEFAULT_FIELD_ALIASES = {
    "country": ["country", "market", "country/market"],
    "jurisdiction": ["jurisdiction"],
    "netting": ["netting", "netting enforceable"],
    "date_of_opinion_review": ["date of opinion review", "opinion review date"],
    "next_review_date": ["next review date"],
    "reviewer_name": ["reviewer", "reviewer name"],
    "counterparty_types_included": ["counterparty types included"],
    "counterparty_type_notes_qualification": ["counterparty type notes qualification"],
    "counterparty_type_comment": ["counterparty type comment"],
    "top_up_opinion_date": ["top up opinion date", "top-up opinion date"],
    "top_up_opinion_date_comments": ["top up opinion date comments", "top-up opinion date comments"],
    "additional_covered_counterparties_top_up_opinion": [
        "additional covered counterparties",
        "additional covered counterparties top up opinion",
    ],
    "additional_covered_products_top_up_opinion": [
        "additional covered products",
        "additional covered products top up opinion",
    ],
    "counterparty_types_excluded": ["counterparty types excluded"],
    "transaction_types_included": ["transaction types included"],
    "transaction_types_excluded": ["transaction types excluded"],
    "governing_law_of_agreement_covered_by_opinion": ["governing law", "governing law of agreement"],
    "automatic_early_termination_applicable": ["automatic early termination applicable"],
    "early_termination_enforceable": ["early termination enforceable"],
    "early_termination_notes": ["early termination notes"],
    "closeout_netting_enforceable": ["closeout netting enforceable", "close-out netting enforceable"],
    "closeout_netting_margin_rules_exemptions_if_not_enforceable": [
        "if closeout netting is no then which margin rules are exempted",
        "margin rules exempted",
    ],
    "closeout_netting_notes": ["closeout netting notes", "close-out netting notes"],
    "netting_legislation_exists": ["netting legislation exists"],
    "excluded_transaction_types_allowed": ["excluded transaction types allowed"],
    "second_method_assumed": ["second method assumed"],
    "first_method_enforceable": ["first method enforceable"],
    "inclusion_of_branch_in_non_netting_country_allowed": [
        "inclusion of branch in non-netting country allowed",
    ],
    "multibranch_local_branch": ["multibranch local branch", "multi branch local branch"],
    "foreign_currency_termination_amount_allowed": [
        "foreign currency termination amount allowed",
    ],
    "termination_amount_currency_if_not_allowed": [
        "what currency for termination amount",
        "termination amount currency",
    ],
    "amendment_recommended_counterparty_type": ["amendment recommended counterparty type"],
    "amendment_notes_for_counterparty_type": [
        "amendment notes in relation to counterparty type",
        "amendment notes for counterparty type",
    ],
    "link_to_opinion": ["link to opinion"],
}


DEFAULT_EXTRACTION_SYSTEM_PROMPT = (
    "You are an expert legal operations analyst for ISDA netting reviews. "
    "Extract structured information from table-first DOCX data. "
    "Prefer table values over narrative text when conflicts exist. "
    "Return strict JSON only."
)

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "You are an expert legal operations assistant for ISDA netting review documents. "
    "Answer only from the provided extracted JSON and raw DOCX payload context. "
    "If data is missing, say so clearly."
)


DEFAULT_CONFIG = {
    "canonical_fields": DEFAULT_CANONICAL_FIELDS,
    "field_aliases": DEFAULT_FIELD_ALIASES,
    "extraction_system_prompt": DEFAULT_EXTRACTION_SYSTEM_PROMPT,
    "chat_system_prompt": DEFAULT_CHAT_SYSTEM_PROMPT,
}


def load_isda_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        return DEFAULT_CONFIG

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"ISDA config must be a JSON object: {path}")

    merged = dict(DEFAULT_CONFIG)
    merged.update(raw)

    canonical = merged.get("canonical_fields")
    if not isinstance(canonical, list):
        raise ValueError("ISDA config canonical_fields must be a list")

    aliases = merged.get("field_aliases")
    if not isinstance(aliases, dict):
        raise ValueError("ISDA config field_aliases must be an object")

    return merged
