# -*- coding: utf-8 -*-
"""Regression: clip detail modal #ccdTaskId must survive I18n.apply().

I18n.apply sets textContent on [data-i18n] elements, which removes all child nodes.
Placing <span id="ccdTaskId"> inside a single data-i18n eyebrow broke chViewTask with
Cannot set properties of null (setting 'textContent').
"""

from pathlib import Path


def test_clip_detail_modal_ccd_task_id_not_under_sole_data_i18n_parent():
    root = Path(__file__).resolve().parents[1]
    html = (root / "monitor_web" / "templates" / "modals" / "modal-clip-detail.html").read_text(
        encoding="utf-8"
    )
    assert 'id="ccdTaskId"' in html
    assert 'data-i18n="clipDetail.taskId"' not in html
    assert 'data-i18n="clipDetail.taskLabel"' in html
    assert "ccd-eyebrow" in html
    # 任务编号在独立 span 内，与翻译前缀并列，避免整段被 textContent 覆盖
    assert "ccd-task-id-suffix" in html
