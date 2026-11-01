from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def integer(default=None, minimum=1, maximum=None):
    out = {"type": "integer", "minimum": minimum}
    if maximum is not None:
        out["maximum"] = maximum
    if default is not None:
        out["default"] = default
    return out


def string(default=None, enum=None, pattern=None, maximum=200):
    out = {"type": "string", "minLength": 1, "maxLength": maximum}
    if default is not None:
        out["default"] = default
    if enum:
        out["enum"] = enum
    if pattern:
        out["pattern"] = pattern
    return out


BVID = string(pattern=r"^BV[0-9A-Za-z]{10}$")
PAGE = integer(default=1, maximum=1000)
SIZE = integer(default=20, maximum=50)
MID = integer()
CONFIRM = {"type": "boolean", "const": True, "description": "确认这次具体的B站状态变更。服务也须以--enable-writes启动。"}


@dataclass(frozen=True)
class Endpoint:
    name: str
    category: str
    description: str
    path: str
    properties: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()
    host: str = "api.bilibili.com"
    method: str = "GET"
    auth: bool = False
    wbi: bool = False
    handler: str | None = None

    @property
    def schema(self):
        return {"type": "object", "properties": self.properties, "required": list(self.required), "additionalProperties": False}

    def parameters(self, arguments: dict) -> dict:
        return {**{k: v["default"] for k, v in self.properties.items() if "default" in v}, **arguments}


ENDPOINTS = [
    Endpoint("bilibili_search", "发现", "分类搜索视频、UP主、直播间、专栏和影视。返回分页原始结构；标题可能含高亮HTML。", "/x/web-interface/search/type", {"keyword": string(), "search_type": string("video", ["video", "bili_user", "live_room", "live_user", "article", "media_bangumi", "media_ft"]), "page": PAGE, "order": string("totalrank", ["totalrank", "click", "pubdate", "dm", "stow", "scores", "fans", "level"]), "duration": integer(0, 0, 4), "tids": integer(0, 0)}, ("keyword",)),
    Endpoint("bilibili_search_hot", "发现", "读取实时搜索热词。", "/x/web-interface/search/square", {"limit": integer(10, maximum=50)}),
    Endpoint("bilibili_popular", "发现", "读取热门视频列表。", "/x/web-interface/popular", {"pn": PAGE, "ps": SIZE}),
    Endpoint("bilibili_ranking", "发现", "按分区读取排行榜；rid=0为全站。", "/x/web-interface/ranking/v2", {"rid": integer(0, 0), "type": string("all", ["all", "origin", "rookie"])}),
    Endpoint("bilibili_region_online", "发现", "读取分区在线/投稿统计。", "/x/web-interface/online"),
    Endpoint("bilibili_video_info", "视频", "读取视频标题、简介、UP主、aid、cid、分P与统计。", "/x/web-interface/view", {"bvid": BVID}, ("bvid",)),
    Endpoint("bilibili_video_pages", "视频", "读取视频各分P的cid、标题与时长。", "/x/player/pagelist", {"bvid": BVID}, ("bvid",)),
    Endpoint("bilibili_video_stat", "视频", "读取视频播放、弹幕、评论、收藏、投币与点赞计数，从当前详情接口提取stat。", "/x/web-interface/view", {"bvid": BVID}, ("bvid",), handler="video_stat"),
    Endpoint("bilibili_video_related", "视频", "读取关联推荐视频。", "/x/web-interface/archive/related", {"bvid": BVID}, ("bvid",)),
    Endpoint("bilibili_video_tags", "视频", "读取视频标签。", "/x/tag/archive/tags", {"bvid": BVID}, ("bvid",)),
    Endpoint("bilibili_video_playurl", "视频", "取得当前会话可播放的临时媒体地址与清晰度；地址有时效。", "/x/player/playurl", {"bvid": BVID, "cid": integer(), "qn": integer(64, maximum=127), "fnval": integer(16, 0, 4048), "fourk": integer(1, 0, 1)}, ("bvid", "cid")),
    Endpoint("bilibili_subtitles", "字幕与弹幕", "查询分P字幕轨道；部分AI字幕依赖登录态及平台可见性。", "/x/player/wbi/v2", {"bvid": BVID, "cid": integer()}, ("bvid", "cid"), wbi=True),
    Endpoint("bilibili_subtitle_text", "字幕与弹幕", "读取字幕接口返回的hdslb字幕JSON，合并时间戳文本。", "", {"url": string(maximum=3000)}, ("url",), handler="subtitle"),
    Endpoint("bilibili_danmaku", "字幕与弹幕", "读取分P公开XML弹幕，最多返回limit条。", "/x/v1/dm/list.so", {"oid": integer(), "limit": integer(100, maximum=1000)}, ("oid",), handler="danmaku"),
    Endpoint("bilibili_comments", "评论", "读取视频/专栏主评论；oid使用视频aid，type=1为视频、12为专栏。", "/x/v2/reply", {"oid": integer(), "type": integer(1, maximum=100), "pn": PAGE, "ps": SIZE, "sort": integer(2, 0, 2)}, ("oid",)),
    Endpoint("bilibili_comment_replies", "评论", "读取指定根评论下的回复。", "/x/v2/reply/reply", {"oid": integer(), "root": integer(), "type": integer(1, maximum=100), "pn": PAGE, "ps": SIZE}, ("oid", "root")),
    Endpoint("bilibili_user_info", "用户", "读取UP主公开资料，自动附加WBI签名。", "/x/space/wbi/acc/info", {"mid": MID}, ("mid",), wbi=True),
    Endpoint("bilibili_user_videos", "用户", "读取UP主视频投稿列表，自动附加WBI签名。", "/x/space/wbi/arc/search", {"mid": MID, "pn": PAGE, "ps": SIZE, "order": string("pubdate", ["pubdate", "click", "stow"]), "tid": integer(0, 0)}, ("mid",), wbi=True),
    Endpoint("bilibili_user_relation_stats", "用户", "读取用户关注数、粉丝数等关系统计。", "/x/relation/stat", {"vmid": MID}, ("vmid",)),
    Endpoint("bilibili_user_followings", "用户", "分页读取用户公开关注列表；平台会限制可见范围。", "/x/relation/followings", {"vmid": MID, "pn": PAGE, "ps": SIZE}, ("vmid",)),
    Endpoint("bilibili_me", "账号", "使用当前已绑定会话核验登录并读取本人资料。", "/x/web-interface/nav", auth=True),
    Endpoint("bilibili_my_history", "账号", "分页读取本人观看历史；首次max/view_at=0，后续沿用响应cursor。", "/x/web-interface/history/cursor", {"max": integer(0, 0), "view_at": integer(0, 0), "business": {"type": "string", "enum": ["", "archive", "pgc", "live", "article"], "default": ""}, "ps": integer(20, maximum=30)}, auth=True),
    Endpoint("bilibili_my_watch_later", "账号", "读取本人稍后再看列表。", "/x/v2/history/toview", auth=True),
    Endpoint("bilibili_favorite_folders", "收藏", "列出收藏夹；不传up_mid时使用当前已绑定账号。", "/x/v3/fav/folder/created/list-all", {"up_mid": MID}, handler="self_mid"),
    Endpoint("bilibili_favorite_items", "收藏", "分页读取可见收藏夹中的视频。", "/x/v3/fav/resource/list", {"media_id": integer(), "pn": PAGE, "ps": SIZE, "order": string("mtime", ["mtime", "view", "pubtime"]), "type": integer(0, 0, 2), "tid": integer(0, 0)}, ("media_id",)),
    Endpoint("bilibili_my_feed", "动态", "读取当前登录用户关注动态；后续分页传offset。", "/x/polymer/web-dynamic/v1/feed/all", {"offset": {"type": "string", "default": "", "maxLength": 200}, "type": string("all", ["all", "video", "pgc", "article"] )}, auth=True),
    Endpoint("bilibili_user_feed", "动态", "读取指定UP主公开动态。", "/x/polymer/web-dynamic/v1/feed/space", {"host_mid": MID, "offset": {"type": "string", "default": "", "maxLength": 200}}, ("host_mid",)),
    Endpoint("bilibili_dynamic_detail", "动态", "读取指定动态内容。", "/x/polymer/web-dynamic/v1/detail", {"id": string(pattern=r"^[0-9]+$")}, ("id",)),
    Endpoint("bilibili_article_info", "专栏", "读取专栏文章公开信息。", "/x/article/viewinfo", {"id": integer()}, ("id",)),
    Endpoint("bilibili_live_areas", "直播", "读取直播分区树。", "/room/v1/Area/getList", host="api.live.bilibili.com"),
    Endpoint("bilibili_live_rooms", "直播", "按直播分区读取直播间列表。", "/room/v3/area/getRoomList", {"parent_area_id": integer(), "area_id": integer(0, 0), "page": PAGE, "page_size": integer(20, maximum=30), "sort_type": string("online", ["online", "live_time"])}, ("parent_area_id",), host="api.live.bilibili.com"),
    Endpoint("bilibili_live_room_info", "直播", "读取直播间信息和直播状态。", "/room/v1/Room/get_info", {"room_id": integer()}, ("room_id",), host="api.live.bilibili.com"),
    Endpoint("bilibili_live_playurl", "直播", "取得当前可见直播流地址。", "/xlive/web-room/v2/index/getRoomPlayInfo", {"room_id": integer(), "protocol": string("0,1", ["0", "1", "0,1"]), "format": string("0,1,2"), "codec": string("0,1"), "qn": integer(80, maximum=10000), "platform": string("web", ["web"])}, ("room_id",), host="api.live.bilibili.com"),
    Endpoint("bilibili_video_like", "互动写入", "点赞/取消点赞视频；like=1点赞、2取消。", "/x/web-interface/archive/like", {"aid": integer(), "like": {"type": "integer", "enum": [1, 2]}, "confirm": CONFIRM}, ("aid", "like", "confirm"), method="POST", auth=True),
    Endpoint("bilibili_video_favorite", "互动写入", "将视频加入/移出指定收藏夹，夹ID以逗号分隔。", "/x/v3/fav/resource/deal", {"rid": integer(), "type": {"type": "integer", "const": 2, "default": 2}, "add_media_ids": {"type": "string", "pattern": r"^[0-9,]*$", "default": "", "maxLength": 500}, "del_media_ids": {"type": "string", "pattern": r"^[0-9,]*$", "default": "", "maxLength": 500}, "confirm": CONFIRM}, ("rid", "confirm"), method="POST", auth=True),
    Endpoint("bilibili_watch_later_add", "互动写入", "将视频加入稍后再看。", "/x/v2/history/toview/add", {"aid": integer(), "confirm": CONFIRM}, ("aid", "confirm"), method="POST", auth=True),
    Endpoint("bilibili_watch_later_delete", "互动写入", "从稍后再看移除指定aid，逗号分隔。", "/x/v2/history/toview/del", {"avids": string(pattern=r"^[0-9]+(,[0-9]+)*$", maximum=500), "confirm": CONFIRM}, ("avids", "confirm"), method="POST", auth=True),
    Endpoint("bilibili_user_follow", "互动写入", "关注/取消关注UP主；act=1关注、2取消。", "/x/relation/modify", {"fid": MID, "act": {"type": "integer", "enum": [1, 2]}, "re_src": integer(11, 0), "confirm": CONFIRM}, ("fid", "act", "confirm"), method="POST", auth=True),
    Endpoint("bilibili_comment_add", "互动写入", "发布一条评论/回复；视频oid为aid，回复需root和parent。", "/x/v2/reply/add", {"oid": integer(), "type": integer(1, maximum=100), "message": string(maximum=1000), "root": integer(0, 0), "parent": integer(0, 0), "confirm": CONFIRM}, ("oid", "message", "confirm"), method="POST", auth=True),
    Endpoint("bilibili_comment_delete", "互动写入", "删除当前账号自己的指定评论。", "/x/v2/reply/del", {"oid": integer(), "type": integer(1, maximum=100), "rpid": integer(), "confirm": CONFIRM}, ("oid", "rpid", "confirm"), method="POST", auth=True),
]
BY_NAME = {endpoint.name: endpoint for endpoint in ENDPOINTS}


def catalog(category: str | None = None) -> dict[str, Any]:
    return {"version": "0.1.0", "transport": ["stdio", "streamable-http"], "categories": sorted({e.category for e in ENDPOINTS}),
            "tools": [{"name": e.name, "category": e.category, "description": e.description,
                       "method": e.method, "url": f"https://{e.host}{e.path}" if e.path else "hdslb subtitle URL only",
                       "authentication": "session" if e.auth else ("self_mid needs session" if e.handler == "self_mid" else "public / session optional"),
                       "wbi": e.wbi, "schema": e.schema} for e in ENDPOINTS if category is None or e.category == category]}
