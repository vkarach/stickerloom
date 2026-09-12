import pytest

from convert.errors import ProbeFailed
from convert.probe import parse_probe

STILL_PNG = {
    "streams": [{
        "codec_type": "video", "codec_name": "png",
        "width": 320, "height": 240,
        "r_frame_rate": "25/1", "avg_frame_rate": "25/1",
    }],
    "format": {"format_name": "png_pipe", "size": "799"},
}

ANIMATED_GIF = {
    "streams": [{
        "codec_type": "video", "codec_name": "gif",
        "width": 320, "height": 240,
        "r_frame_rate": "15/1", "avg_frame_rate": "50/3",
        "duration": "2.000000", "nb_frames": "30",
    }],
    "format": {"format_name": "gif", "duration": "2.000000", "size": "140665"},
}

MP4_WITH_AUDIO = {
    "streams": [
        {
            "codec_type": "video", "codec_name": "h264",
            "width": 640, "height": 480,
            "r_frame_rate": "30/1", "avg_frame_rate": "30/1",
            "duration": "2.000000", "nb_frames": "60",
        },
        {"codec_type": "audio", "codec_name": "aac", "duration": "2.000000"},
    ],
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "2.000000"},
}

ANIMATED_WEBP = {
    "streams": [{
        "codec_type": "video", "codec_name": "webp",
        "width": 0, "height": 0,
        "r_frame_rate": "25/1", "avg_frame_rate": "25/1",
    }],
    "format": {"format_name": "webp_pipe", "size": "25054"},
}

AUDIO_ONLY = {
    "streams": [{"codec_type": "audio", "codec_name": "mp3", "duration": "2.0"}],
    "format": {"format_name": "mp3", "duration": "2.0"},
}


def test_still_image_is_one_frame_and_not_animated():
    info = parse_probe(STILL_PNG)
    assert (info.width, info.height) == (320, 240)
    assert info.frames == 1
    assert info.is_animated is False
    assert info.duration == 0.0


def test_animated_gif_keeps_duration_and_frame_count():
    info = parse_probe(ANIMATED_GIF)
    assert (info.width, info.height) == (320, 240)
    assert info.frames == 30
    assert info.duration == pytest.approx(2.0)
    assert info.is_animated is True


def test_audio_stream_is_ignored():
    info = parse_probe(MP4_WITH_AUDIO)
    assert (info.width, info.height) == (640, 480)
    assert info.frames == 60
    assert info.is_animated is True


def test_missing_video_stream_is_rejected():
    with pytest.raises(ProbeFailed):
        parse_probe(AUDIO_ONLY)


def test_empty_payload_is_rejected():
    with pytest.raises(ProbeFailed):
        parse_probe({"streams": [], "format": {}})


def test_unreadable_webp_is_flagged_for_expansion():
    info = parse_probe(ANIMATED_WEBP)
    assert info.needs_frame_expansion is True
