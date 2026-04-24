"""Wave 0 stub for test_brand_term_validation. Activated by plan 12-06."""
import pytest

pytest.skip("Wave 0 stub — activated by plan 12-06", allow_module_level=True)

# When activated, tests here will cover:
# - test_term_rejects_stoplist_word — default stoplist hit => ValidationError
# - test_term_rejects_empty_string — whitespace-only term rejected
# - test_term_rejects_short_term — length < threshold flagged as advisory
# - test_term_type_pii_requires_gdpr_ack — PII term without GDPR acknowledgement rejected
# - test_term_normalises_case_and_trim — stored in canonical lowercase trimmed form
