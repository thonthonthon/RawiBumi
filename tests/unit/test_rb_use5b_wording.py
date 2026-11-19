"""The remaining scope-refusal note records the override without refusing orientation mixes."""
from apps.api.orientation_policy import OVERRIDE_NOTE


def test_override_note_only_records_the_reason():
    assert OVERRIDE_NOTE == "The orientation override records your reason."
