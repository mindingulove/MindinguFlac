import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw
import video_motion


def artwork():
    frame = Image.new("RGB", (160, 90), "#173c65")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((25, 15, 120, 72), fill="#8a5029")
    draw.ellipse((50, 25, 100, 75), fill="#e0c080")
    return frame


def moving_frames():
    frames = []
    for index in range(9):
        frame = Image.new("RGB", (160, 90), (index * 20, 80, 180 - index * 15))
        ImageDraw.Draw(frame).rectangle((index * 10, 10, index * 10 + 50, 70), fill="white")
        frames.append(frame)
    return frames


class MotionPreviewTests(unittest.TestCase):
    def test_static_artwork_and_small_compression_changes_are_rejected(self):
        frames = []
        for index in range(9):
            encoded = io.BytesIO()
            artwork().save(encoded, "JPEG", quality=65 + index)
            frames.append(Image.open(io.BytesIO(encoded.getvalue())))
        self.assertEqual(video_motion.assess_frames(frames)["status"], "static")

    def test_real_picture_changes_are_accepted(self):
        self.assertEqual(video_motion.assess_frames(moving_frames())["status"], "moving")

    def test_short_intro_does_not_turn_an_album_cover_into_a_clip(self):
        frames = [Image.new("RGB", (160, 90), "black"), *[artwork() for _ in range(8)]]
        self.assertEqual(video_motion.assess_frames(frames)["status"], "static")

    def test_missing_preview_is_retryable_and_never_assumed_static(self):
        self.assertEqual(video_motion.assess_frames([artwork()])["status"], "unknown")

    def test_storyboard_reads_tiles_without_requesting_the_video(self):
        sheet = Image.new("RGB", (480, 270))
        for index, frame in enumerate(moving_frames()):
            sheet.paste(frame, (index % 3 * 160, index // 3 * 90))
        encoded = io.BytesIO()
        sheet.save(encoded, "JPEG")
        response = Mock(content=encoded.getvalue())
        info = {"duration": 90, "formats": [{"protocol": "mhtml", "width": 160, "height": 90,
                "rows": 3, "columns": 3, "fps": .1, "fragments": [{"url": "https://i.ytimg.com/sheet.jpg"}]}]}
        with patch("requests.get", return_value=response) as get:
            result = video_motion.storyboard_preview(info)
        self.assertEqual(result["status"], "moving")
        self.assertEqual(result["samples"], 9)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], "https://i.ytimg.com/sheet.jpg")

    def test_static_preview_stops_before_full_download(self):
        import backend_video
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(video_motion, "preview_youtube", return_value={"status": "static"}), \
                patch("yt_dlp.YoutubeDL") as downloader:
            with self.assertRaises(video_motion.StaticVideoError):
                backend_video._download_youtube_clip("https://youtube.com/watch?v=abcdefghijk", 0, Path(tmp) / "video.mp4")
        downloader.assert_not_called()

    def test_unavailable_preview_does_not_start_an_unchecked_download(self):
        import backend_video
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(video_motion, "preview_youtube", return_value={"status": "unknown", "reason": "network error"}), \
                patch("yt_dlp.YoutubeDL") as downloader:
            with self.assertRaises(video_motion.VideoPreviewError):
                backend_video._download_youtube_clip("https://youtube.com/watch?v=abcdefghijk", 0, Path(tmp) / "video.mp4")
        downloader.assert_not_called()

class VideoSelectionTests(unittest.TestCase):
    def test_static_first_candidate_is_skipped_for_a_moving_match(self):
        import backend_video
        entries = [{"id": "aaaaaaaaaaa", "title": "Artist Song official audio"},
                   {"id": "bbbbbbbbbbb", "title": "Artist Song official video"}]
        context = Mock()
        context.__enter__ = Mock(return_value=context)
        context.__exit__ = Mock(return_value=False)
        context.extract_info.return_value = {"entries": entries}
        with tempfile.TemporaryDirectory() as tmp, \
                patch("yt_dlp.YoutubeDL", return_value=context), \
                patch("db.get_youtube_video_override", return_value=None), \
                patch.object(backend_video, "_download_youtube_clip", side_effect=[video_motion.StaticVideoError(), True]) as download, \
                patch.object(backend_video, "_clip_duration_ok", return_value=True):
            self.assertTrue(backend_video.fetch_clip_to_path({"artist": "Artist", "title": "Song"}, Path(tmp) / "clip.mp4", log_cb=lambda _: None))
        self.assertEqual(download.call_count, 2)
        self.assertIn("bbbbbbbbbbb", download.call_args.args[0])

    def test_uncertain_preview_remains_an_error_instead_of_no_video(self):
        import backend_video
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(backend_video, "_download_youtube_clip", side_effect=video_motion.VideoPreviewError("offline")):
            with self.assertRaisesRegex(video_motion.VideoPreviewError, "offline"):
                backend_video.fetch_clip_to_path({"artist": "Artist", "title": "Song", "youtube_id": "aaaaaaaaaaa"}, Path(tmp) / "clip.mp4", log_cb=lambda _: None)


class CachedVideoTests(unittest.TestCase):
    def test_static_library_file_is_never_ready_and_refresh_keeps_the_file(self):
        import app
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "library.mp4"
            video.write_bytes(b'x' * 70000)
            with patch.object(app, "VIDEO_FILES_DIR", root / "video-cache"), \
                    patch.object(app, "app_config", SimpleNamespace(music_dir=root, cache_dir=root)), \
                    patch.object(video_motion, "cached_file_preview", return_value={"status": "static"}), \
                    patch.object(app, "_load_video_cache", return_value={}), patch.object(app, "_save_video_cache"), \
                    patch.object(app.threading, "Thread") as thread:
                identity = {"artist": "Artist", "title": "Song", "video_path": str(video), "offline": True}
                self.assertEqual(app._get_video_fetch(identity)["status"], "not_found")
                self.assertEqual(app._get_video_fetch(identity, force=True)["status"], "not_found")
                self.assertTrue(video.exists())
                thread.assert_not_called()

    def test_offline_missing_video_never_starts_a_network_job(self):
        import app
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "VIDEO_FILES_DIR", Path(tmp)), \
                patch.object(app.threading, "Thread") as thread:
            self.assertEqual(app._get_video_fetch({"artist": "Artist", "title": "Song", "offline": True})["status"], "not_found")
            thread.assert_not_called()
