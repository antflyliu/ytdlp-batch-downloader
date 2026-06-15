from pydantic import BaseModel


# ---- parseShareUrl 响应 ----

class ParseData(BaseModel):
    wx_export_id: str = ""
    cover_url: str = ""
    author_certification_icon: str = ""
    author: str = ""
    author_icon: str = ""
    desc: str = ""
    playable_url: str = ""


class ParseResponse(BaseModel):
    code: int = -1
    msg: str = ""
    data: ParseData = ParseData()


# ---- getFeedInfo 响应 ----

class H264VideoInfo(BaseModel):
    video_url: str = ""


class H265VideoInfo(BaseModel):
    video_url: str = ""


class ScalingInfo(BaseModel):
    version: str = ""
    is_split_screen: bool = False
    is_disable_follow: bool = False
    up_percent_position: float = 0.0
    down_percent_position: float = 0.0
    aspect_ratio_exceeds_169: bool = False


class FeedInfo(BaseModel):
    pic_info: list = []
    video_url: str = ""
    origin_video_url: str = ""
    description: str = ""
    media_type: int = 0
    fav_count_fmt: str = ""
    like_count_fmt: str = ""
    forward_count_fmt: str = ""
    comment_count_fmt: str = ""
    h264_video_info: H264VideoInfo = H264VideoInfo()
    h265_video_info: H265VideoInfo = H265VideoInfo()
    createtime: int = 0
    scaling_info: ScalingInfo = ScalingInfo()
    is_hard_ad: bool = False
    cover_url: str = ""


class AuthorInfo(BaseModel):
    nickname: str = ""
    head_img_url: str = ""
    auth_icon_url: str = ""


class ErrMsg(BaseModel):
    type: int = 0


class SceneInfo(BaseModel):
    dynamic_export_id: str = ""
    comment_scene: int = 0
    expired_time: int = 0
    request_scene: int = 0
    entry_scene: int = 0
    entry_card_type: int = 0


class FeedResponseData(BaseModel):
    author_info: AuthorInfo = AuthorInfo()
    feed_info: FeedInfo = FeedInfo()
    err_msg: ErrMsg = ErrMsg()
    scene_info: SceneInfo = SceneInfo()


class FeedResponse(BaseModel):
    data: FeedResponseData = FeedResponseData()
    err_code: int = -1
    err_msg: str = ""


# ---- 统一 API 响应 ----

class ApiResponse(BaseModel):
    code: int = 0
    msg: str = "成功"
    data: object = None


# ---- Cookie 更新请求 ----

class CookieUpdateRequest(BaseModel):
    cookie: str
