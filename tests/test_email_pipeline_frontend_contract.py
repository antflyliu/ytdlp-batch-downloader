from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EMAIL_PIPELINE_VIEW = ROOT / "frontend-vue" / "src" / "views" / "EmailPipeline.vue"


def test_gmail_one_click_oauth_does_not_preselect_existing_account():
    text = EMAIL_PIPELINE_VIEW.read_text(encoding="utf-8")

    assert "selectedGmailAuthAccountId.value = gmailIds[0]" not in text
    assert "const selectedAccountId = accountId || selectedGmailAuthAccountId.value || null" in text
    assert "...(selectedAccountId ? { account_id: selectedAccountId } : {})" in text
    assert "readPending" in text
    assert "sendPending" in text
