import pandas as pd

from src.access_control import demo_profiles, scope_data


def _data():
    return pd.DataFrame(
        [
            {"clinic": "North Clinic", "provider": "Dr. Maya Patel", "date": "2025-01-01"},
            {"clinic": "North Clinic", "provider": "Dr. Ada Ross", "date": "2025-01-01"},
            {"clinic": "South Clinic", "provider": "Dr. Zara Hayes", "date": "2025-01-01"},
        ]
    )


def test_demo_profiles_apply_expected_aggregate_boundaries():
    df = _data()
    profiles = {profile.key: profile for profile in demo_profiles(df)}

    assert len(scope_data(df, profiles["executive"])) == 3
    assert len(scope_data(df, profiles["analyst"])) == 3
    assert set(scope_data(df, profiles["manager"]).provider) == {"Dr. Maya Patel", "Dr. Ada Ross"}
    assert set(scope_data(df, profiles["provider"]).provider) == {"Dr. Maya Patel"}


def test_uploaded_names_receive_a_usable_deterministic_fallback_scope():
    df = pd.DataFrame([{"clinic": "A Clinic", "provider": "Dr. Example", "date": "2025-01-01"}])
    profiles = {profile.key: profile for profile in demo_profiles(df)}
    assert profiles["manager"].clinic == "A Clinic"
    assert profiles["provider"].provider == "Dr. Example"
