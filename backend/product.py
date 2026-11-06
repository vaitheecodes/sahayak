"""The product this help desk supports: app_settings section "product".

Sahayak is set up per client, and their product is not known in advance,
so no prompt, reply or check names a product in code. Prompts describe it
with described() ("Brightdesk HR (an HR management system)"), or as "the
product" while the admin hasn't named it yet.
"""

from __future__ import annotations

import re

from backend import app_settings

GENERIC_NAME = "the product"


def profile() -> app_settings.ProductSettings:
    return app_settings.get("product")


def name() -> str:
    return profile().name.strip() or GENERIC_NAME


def described() -> str:
    """The product's name with its description, for prompts."""
    p = profile()
    if not p.name.strip():
        return f"{GENERIC_NAME} ({p.description.strip()})" if p.description.strip() else GENERIC_NAME
    return f"{p.name.strip()} ({p.description.strip()})" if p.description.strip() else p.name.strip()


def support_team() -> str:
    return profile().support_team_name.strip() or "Support Team"


def name_words() -> set[str]:
    """The product name's words, lower case: "I have an issue with
    Brightdesk" says nothing about the problem."""
    return set(re.findall(r"[a-z0-9]+", profile().name.lower()))
