from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_VIEW = ROOT / "frontend-vue" / "src" / "views" / "Accounts.vue"
CLIPS_API = ROOT / "frontend-vue" / "src" / "api" / "clips.ts"


def test_video_detail_exposes_clip_action_for_downloaded_videos():
    text = ACCOUNTS_VIEW.read_text(encoding="utf-8")

    assert "import clipsApi from '@/api/clips'" in text
    assert "const canClipVideo = (row: AccountVideo) => row.download_status === 'downloaded'" in text
    assert "clipsApi.create(row.id)" in text
    assert "t('videoDetail.clip')" in text
    assert "t('videoDetail.clipRequiresDownloaded')" in text
    assert "router.push('/clip-history')" in text


def test_clips_api_can_create_manual_clip_task():
    text = CLIPS_API.read_text(encoding="utf-8")

    assert "create(videoId: number)" in text
    assert "url: '/api/clips'" in text
    assert "method: 'post'" in text
    assert "data: { video_id: videoId }" in text


def test_account_detail_action_matches_existing_sticky_table_button_style():
    text = ACCOUNTS_VIEW.read_text(encoding="utf-8")
    action_block_start = text.index("class: 'account-detail-action'")
    action_block = text[action_block_start - 120:action_block_start + 180]

    assert "h(NButton, {" in action_block
    assert "h('button', {" not in action_block
    assert ".account-detail-action {" in text
    assert "min-width: 76px;" in text
    assert "secondary: true" not in action_block
