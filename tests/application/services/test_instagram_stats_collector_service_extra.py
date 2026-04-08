"""Extra tests for instagram_stats_collector_service — uncovered lines."""

import pytest

from ugc_bot.application.services.instagram_stats_collector_service import (
    _extract_analytics_fields,
    _extract_post_metrics,
    _extract_posting_frequency,
    _extract_profile_fields,
    _get_posts_from_raw,
    _get_user_dict,
    _safe_bool,
    _safe_float,
)

# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


def test_safe_float_none_returns_none() -> None:
    """_safe_float(None) returns None."""
    assert _safe_float(None) is None


def test_safe_float_valid_number() -> None:
    """_safe_float converts numeric string to float."""
    assert _safe_float("3.14") == pytest.approx(3.14)
    assert _safe_float(42) == pytest.approx(42.0)


def test_safe_float_invalid_string_returns_none() -> None:
    """_safe_float returns None for non-numeric string."""
    assert _safe_float("abc") is None


def test_safe_float_invalid_type_returns_none() -> None:
    """_safe_float returns None for un-convertible type like list."""
    assert _safe_float([1, 2]) is None


# ---------------------------------------------------------------------------
# _safe_bool
# ---------------------------------------------------------------------------


def test_safe_bool_none_returns_none() -> None:
    """_safe_bool(None) returns None."""
    assert _safe_bool(None) is None


def test_safe_bool_true_literal() -> None:
    """_safe_bool(True) returns True."""
    assert _safe_bool(True) is True


def test_safe_bool_false_literal() -> None:
    """_safe_bool(False) returns False."""
    assert _safe_bool(False) is False


def test_safe_bool_string_true() -> None:
    """_safe_bool('true') returns True."""
    assert _safe_bool("true") is True
    assert _safe_bool("True") is True
    assert _safe_bool("1") is True
    assert _safe_bool("yes") is True
    assert _safe_bool("YES") is True


def test_safe_bool_string_false() -> None:
    """_safe_bool('false') returns False (not in truthy set)."""
    assert _safe_bool("false") is False
    assert _safe_bool("no") is False
    assert _safe_bool("0") is False


def test_safe_bool_int_truthy() -> None:
    """_safe_bool(1) returns True via bool() fallback."""
    assert _safe_bool(1) is True


def test_safe_bool_int_falsy() -> None:
    """_safe_bool(0) returns False via bool() fallback."""
    assert _safe_bool(0) is False


# ---------------------------------------------------------------------------
# _extract_profile_fields
# ---------------------------------------------------------------------------


def test_extract_profile_fields_basic() -> None:
    """Extract profile fields from a fully-populated user dict."""
    user = {
        "full_name": "Alice Smith",
        "is_professional_account": True,
        "is_business_account": False,
        "category_name": "Blogger",
        "external_url": "https://example.com",
    }
    full_name, is_prof, is_biz, category, ext_url = _extract_profile_fields(
        user
    )
    assert full_name == "Alice Smith"
    assert is_prof is True
    assert is_biz is False
    assert category == "Blogger"
    assert ext_url == "https://example.com"


def test_extract_profile_fields_bio_links_fallback() -> None:
    """external_url falls back to first bio_links entry when no external_url."""
    user = {
        "external_url": "",
        "bio_links": [{"url": "https://linktree.example.com"}],
    }
    _, _, _, _, ext_url = _extract_profile_fields(user)
    assert ext_url == "https://linktree.example.com"


def test_extract_profile_fields_bio_links_non_dict_ignored() -> None:
    """bio_links entries that are not dicts are ignored."""
    user = {
        "bio_links": ["https://raw-link.example.com"],
    }
    _, _, _, _, ext_url = _extract_profile_fields(user)
    assert ext_url is None


def test_extract_profile_fields_category_fallback() -> None:
    """category falls back to user.category when category_name absent."""
    user = {"category": "Lifestyle"}
    _, _, _, category, _ = _extract_profile_fields(user)
    assert category == "Lifestyle"


def test_extract_profile_fields_empty_dict() -> None:
    """Empty user dict returns all None."""
    result = _extract_profile_fields({})
    assert result == (None, None, None, None, None)


# ---------------------------------------------------------------------------
# _extract_post_metrics
# ---------------------------------------------------------------------------


def test_extract_post_metrics_empty_returns_nones() -> None:
    """Empty posts list returns all None."""
    result = _extract_post_metrics([])
    assert result == (None, None, None, None, None)


def test_extract_post_metrics_photo_posts() -> None:
    """Photo posts compute correct avg_likes and avg_comments."""
    posts = [
        {"like_count": 100, "comment_count": 10, "is_video": False},
        {"like_count": 200, "comment_count": 20, "is_video": False},
    ]
    avg_likes, avg_comments, avg_vv, video_count, photo_count = (
        _extract_post_metrics(posts)
    )
    assert avg_likes == pytest.approx(150.0)
    assert avg_comments == pytest.approx(15.0)
    assert avg_vv is None
    assert video_count == 0
    assert photo_count == 2


def test_extract_post_metrics_video_posts() -> None:
    """Video posts track video_count and avg_video_views."""
    posts = [
        {
            "is_video": True,
            "like_count": 50,
            "comment_count": 5,
            "video_view_count": 1000,
        },
        {
            "is_video": True,
            "like_count": 150,
            "comment_count": 15,
            "video_view_count": 3000,
        },
    ]
    avg_likes, avg_comments, avg_vv, video_count, photo_count = (
        _extract_post_metrics(posts)
    )
    assert avg_likes == pytest.approx(100.0)
    assert avg_comments == pytest.approx(10.0)
    assert avg_vv == pytest.approx(2000.0)
    assert video_count == 2
    assert photo_count == 0


def test_extract_post_metrics_reels_counted_as_video() -> None:
    """Posts with product_type reels are counted as videos."""
    posts = [{"product_type": "reels", "like_count": 500, "comment_count": 50}]
    _, _, _, video_count, photo_count = _extract_post_metrics(posts)
    assert video_count == 1
    assert photo_count == 0


def test_extract_post_metrics_edge_liked_by_shape() -> None:
    """Posts in edge_liked_by / edge_media_to_comment shape are handled."""
    posts = [
        {
            "node": {
                "edge_liked_by": {"count": 80},
                "edge_media_to_comment": {"count": 8},
                "is_video": False,
            }
        }
    ]
    avg_likes, avg_comments, _, _, _ = _extract_post_metrics(posts)
    assert avg_likes == pytest.approx(80.0)
    assert avg_comments == pytest.approx(8.0)


def test_extract_post_metrics_non_dict_node_skipped() -> None:
    """Non-dict nodes are skipped gracefully."""
    posts = ["not_a_dict", {"like_count": 10, "comment_count": 1}]
    avg_likes, avg_comments, _, _, photo_count = _extract_post_metrics(posts)
    assert avg_likes == pytest.approx(10.0 / 2)
    assert photo_count == 1


def test_extract_post_metrics_video_without_view_count() -> None:
    """Video post with no view_count gives None avg_video_views."""
    posts = [{"is_video": True, "like_count": 100, "comment_count": 5}]
    _, _, avg_vv, video_count, _ = _extract_post_metrics(posts)
    assert avg_vv is None
    assert video_count == 1


# ---------------------------------------------------------------------------
# _extract_posting_frequency
# ---------------------------------------------------------------------------


def test_extract_posting_frequency_empty_returns_none() -> None:
    """Empty post list returns None."""
    assert _extract_posting_frequency([]) is None


def test_extract_posting_frequency_single_post_returns_none() -> None:
    """Single post can't determine frequency; returns None."""
    posts = [{"taken_at_timestamp": 1700000000}]
    assert _extract_posting_frequency(posts) is None


def test_extract_posting_frequency_two_posts() -> None:
    """Two posts 1 day apart returns 1.0 days."""
    one_day = 86400
    posts = [
        {"taken_at_timestamp": 1700000000 + one_day},
        {"taken_at_timestamp": 1700000000},
    ]
    freq = _extract_posting_frequency(posts)
    assert freq == pytest.approx(1.0)


def test_extract_posting_frequency_uses_taken_at_fallback() -> None:
    """taken_at key is used when taken_at_timestamp is absent."""
    one_day = 86400
    posts = [
        {"taken_at": 1700000000 + one_day},
        {"taken_at": 1700000000},
    ]
    freq = _extract_posting_frequency(posts)
    assert freq == pytest.approx(1.0)


def test_extract_posting_frequency_same_timestamp_returns_none() -> None:
    """Posts with identical timestamps (zero span) returns None."""
    posts = [
        {"taken_at_timestamp": 1700000000},
        {"taken_at_timestamp": 1700000000},
    ]
    assert _extract_posting_frequency(posts) is None


def test_extract_posting_frequency_non_dict_nodes_skipped() -> None:
    """Non-dict nodes in post list are skipped."""
    one_day = 86400
    posts = [
        "bad_node",
        {"taken_at_timestamp": 1700000000 + one_day},
        {"taken_at_timestamp": 1700000000},
    ]
    freq = _extract_posting_frequency(posts)
    assert freq == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _get_posts_from_raw
# ---------------------------------------------------------------------------


def test_get_posts_from_raw_edge_owner_to_timeline() -> None:
    """Posts extracted from data.user.edge_owner_to_timeline_media.edges."""
    post1 = {"node": {"like_count": 100}}
    raw = {
        "data": {
            "user": {
                "edge_owner_to_timeline_media": {
                    "count": 1,
                    "edges": [post1],
                }
            }
        }
    }
    posts = _get_posts_from_raw(raw)
    assert posts == [post1]


def test_get_posts_from_raw_media_list() -> None:
    """Posts extracted from data.media (list)."""
    post1 = {"like_count": 50}
    raw = {"media": [post1]}
    posts = _get_posts_from_raw(raw)
    assert posts == [post1]


def test_get_posts_from_raw_posts_list() -> None:
    """Posts extracted from data.posts (list)."""
    post1 = {"like_count": 50}
    raw = {"posts": [post1]}
    posts = _get_posts_from_raw(raw)
    assert posts == [post1]


def test_get_posts_from_raw_media_dict_items_key() -> None:
    """Posts extracted from data.media.items when media is a dict."""
    post1 = {"like_count": 50}
    raw = {"media": {"items": [post1]}}
    posts = _get_posts_from_raw(raw)
    assert posts == [post1]


def test_get_posts_from_raw_media_dict_data_key() -> None:
    """Posts extracted from data.media.data when media is a dict."""
    post1 = {"like_count": 50}
    raw = {"media": {"data": [post1]}}
    posts = _get_posts_from_raw(raw)
    assert posts == [post1]


def test_get_posts_from_raw_media_dict_edges_key() -> None:
    """Posts extracted from data.media.edges when media is a dict."""
    post1 = {"like_count": 50}
    raw = {"media": {"edges": [post1]}}
    posts = _get_posts_from_raw(raw)
    assert posts == [post1]


def test_get_posts_from_raw_no_posts_returns_empty() -> None:
    """Returns empty list when no recognizable post structure."""
    raw = {"data": {"username": "test"}}
    posts = _get_posts_from_raw(raw)
    assert posts == []


# ---------------------------------------------------------------------------
# _get_user_dict
# ---------------------------------------------------------------------------


def test_get_user_dict_returns_data_user() -> None:
    """Returns data.user when present as dict."""
    user = {"username": "alice"}
    raw = {"data": {"user": user, "other": "x"}}
    assert _get_user_dict(raw) is user


def test_get_user_dict_returns_data_when_no_user() -> None:
    """Returns data dict when no user key."""
    data = {"username": "alice"}
    raw = {"data": data}
    assert _get_user_dict(raw) is data


def test_get_user_dict_returns_raw_when_data_not_dict() -> None:
    """Returns raw dict (not {}) when data value is not a dict."""
    raw = {"data": "invalid"}
    # When data is not a dict, data = raw, so we get raw back (no user key)
    result = _get_user_dict(raw)
    assert result is raw


# ---------------------------------------------------------------------------
# _extract_analytics_fields — engagement metrics
# ---------------------------------------------------------------------------


def test_extract_analytics_fields_computes_engagement_rate() -> None:
    """engagement_rate = (avg_likes + avg_comments) / followers."""
    raw = {
        "data": {
            "username": "alice",
            "followers_count": 1000,
            "follows_count": 100,
            "posts": [
                {"like_count": 100, "comment_count": 10},
                {"like_count": 200, "comment_count": 20},
            ],
        }
    }
    fields = _extract_analytics_fields(
        raw, followers_count=1000, follows_count=100
    )
    # avg_likes=150, avg_comments=15, rate = 165/1000
    assert fields.engagement_rate == pytest.approx(0.165)
    assert fields.followers_to_follows_ratio == pytest.approx(10.0)
    assert fields.comments_to_likes_ratio == pytest.approx(15.0 / 150.0)


def test_extract_analytics_fields_video_ratio() -> None:
    """video_ratio is video_count / total posts."""
    raw = {
        "posts": [
            {"like_count": 10, "is_video": True, "video_view_count": 500},
            {"like_count": 10, "is_video": False},
            {"like_count": 10, "is_video": False},
        ]
    }
    fields = _extract_analytics_fields(
        raw, followers_count=None, follows_count=None
    )
    assert fields.video_ratio == pytest.approx(1.0 / 3.0)
    assert fields.total_video_count == 1
    assert fields.total_photo_count == 2
    assert fields.avg_video_views == pytest.approx(500.0)


def test_extract_analytics_fields_posting_frequency() -> None:
    """posting_frequency_days is computed from post timestamps."""
    one_day = 86400
    raw = {
        "posts": [
            {"like_count": 10, "taken_at_timestamp": 1700000000 + one_day},
            {"like_count": 10, "taken_at_timestamp": 1700000000},
        ]
    }
    fields = _extract_analytics_fields(
        raw, followers_count=None, follows_count=None
    )
    assert fields.posting_frequency_days == pytest.approx(1.0)


def test_extract_analytics_fields_no_posts_all_none() -> None:
    """With no posts, engagement and video metrics are None."""
    raw = {"data": {"username": "alice"}}
    fields = _extract_analytics_fields(
        raw, followers_count=None, follows_count=None
    )
    assert fields.avg_likes is None
    assert fields.avg_comments is None
    assert fields.engagement_rate is None
    assert fields.video_ratio is None
    assert fields.posting_frequency_days is None
