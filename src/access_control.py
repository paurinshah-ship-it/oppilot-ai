"""Demo role scopes for the synthetic Provider Performance Copilot.

This module intentionally models data *scope*, rather than authentication.
The Streamlit selector is useful for demonstrating enterprise product design,
but a deployed application must derive these values from a server-enforced
identity and authorization system.
"""
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DemoAccessProfile:
    """A named demo user and the aggregate data boundary assigned to them."""

    key: str
    role: str
    display_name: str
    clinic: str | None = None
    provider: str | None = None

    @property
    def label(self) -> str:
        return f"{self.role} · {self.display_name}"

    @property
    def scope_label(self) -> str:
        if self.provider:
            return f"Own aggregated performance · {self.provider}"
        if self.clinic:
            return f"Practice-level performance · {self.clinic}"
        return "Organization-level performance"


def demo_profiles(df: pd.DataFrame) -> list[DemoAccessProfile]:
    """Return stable demo identities, resolving their scope against loaded data.

    Uploaded aggregate data can use different clinic or provider names. In that
    case the demo manager and provider fall back deterministically to the first
    available clinic/provider so the scoped experience remains usable.
    """
    clinics = sorted(df["clinic"].dropna().unique())
    providers = sorted(df["provider"].dropna().unique())
    if not clinics or not providers:
        raise ValueError("Role scopes require at least one clinic and provider.")
    manager_clinic = "North Clinic" if "North Clinic" in clinics else clinics[0]
    provider = "Dr. Maya Patel" if "Dr. Maya Patel" in providers else providers[0]
    return [
        DemoAccessProfile("executive", "Executive", "Avery Morgan"),
        DemoAccessProfile("manager", "Practice Manager", "Jordan Reyes", clinic=manager_clinic),
        DemoAccessProfile("provider", "Provider", provider, provider=provider),
        DemoAccessProfile("analyst", "Analyst", "Casey Nguyen"),
    ]


def scope_data(df: pd.DataFrame, profile: DemoAccessProfile) -> pd.DataFrame:
    """Return only the provider-day aggregate rows visible to ``profile``.

    Executive and Analyst demo users can view the organization. A Practice
    Manager is restricted to the assigned clinic. A Provider is restricted to
    their own provider-day aggregates before calculations occur, so every
    metric, chart, copilot response, report, and export derives from that scope.
    """
    if profile.provider:
        return df.loc[df["provider"].eq(profile.provider)].copy()
    if profile.clinic:
        return df.loc[df["clinic"].eq(profile.clinic)].copy()
    return df.copy()


def scope_description(profile: DemoAccessProfile, row_count: int) -> str:
    """Human-readable scope evidence for the application controls."""
    return f"{profile.scope_label} · {row_count:,} provider-day aggregate rows"
