import json
import subprocess
import sys
from fractions import Fraction

import pytest

from app.services.media.timeline import MediaError, analyze


def make_video(path, *filters):
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    for item in filters:
        command += ["-f", "lavfi", "-i", item]
    if len(filters) > 1:
        command += ["-filter_complex", f"concat=n={len(filters)}:v=1:a=0[out]", "-map", "[out]"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, timeout=30, capture_output=True)


def test_two_shots_and_real_reference_frames(tmp_path):
    source = tmp_path / "source.mp4"
    make_video(source, "color=red:s=160x90:r=10:d=1", "color=blue:s=160x90:r=10:d=1")
    output = tmp_path / "result"
    result = analyze(source, output)
    assert result["metadata"]["audio_present"] is False
    assert len(result["shots"]) == 2
    assert abs(result["shots"][1]["start_ms"] - 1000) <= 100
    assert result["shots"][0]["start_ms"] == 0
    assert result["shots"][0]["end_ms"] == result["shots"][1]["start_ms"]
    assert result["shots"][-1]["end_ms"] == result["metadata"]["duration_ms"]
    for shot in result["shots"]:
        frame = shot["reference"]
        assert shot["start_ms"] <= frame["timestamp_ms"] < shot["end_ms"]
        assert (output / frame["file"]).read_bytes().startswith(b"\xff\xd8")
        assert (output / shot["thumbnail"]).read_bytes().startswith(b"\xff\xd8")
        assert len(frame["sha256"]) == 64
    assert json.loads((output / "timeline.json").read_text(encoding="utf-8")) == result


def test_single_vertical_shot(tmp_path):
    source = tmp_path / "vertical.mp4"
    make_video(source, "color=white:s=90x160:r=10:d=1")
    result = analyze(source, tmp_path / "out")
    assert len(result["shots"]) == 1
    assert result["metadata"]["width"] == 90
    assert result["metadata"]["height"] == 160


def test_corrupt_media_never_publishes_result(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    output = tmp_path / "result"
    with pytest.raises(MediaError):
        analyze(source, output)
    assert not output.exists()


def test_existing_result_is_not_overwritten(tmp_path):
    source = tmp_path / "source.mp4"
    make_video(source, "color=red:s=160x90:r=10:d=1")
    output = tmp_path / "result"
    output.mkdir()
    (output / "sentinel").write_text("untouched")
    with pytest.raises(MediaError):
        analyze(source, output)
    assert (output / "sentinel").read_text() == "untouched"


def test_variable_frame_rate_uses_decoded_pts(tmp_path):
    source = tmp_path / "variable.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=s=160x90:r=10:d=2", "-vf", "select=not(eq(mod(n\\,3)\\,1))",
         "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True, timeout=30, capture_output=True,
    )
    result = analyze(source, tmp_path / "result")
    assert result["metadata"]["variable_frame_rate"] is True
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries",
         "frame=best_effort_timestamp", "-of", "json", str(source)],
        check=True, capture_output=True, timeout=30,
    ).stdout)
    original_pts = {int(frame["best_effort_timestamp"]) for frame in probe["frames"]}
    assert all(shot["reference"]["pts"] in original_pts for shot in result["shots"])
    base = Fraction(result["metadata"]["time_base"])
    first = result["metadata"]["source_start_pts"]
    assert all(shot["reference"]["timestamp_ms"] == int((shot["reference"]["pts"] - first) * base * 1000)
               for shot in result["shots"])
    assert all(shot["start_ms"] <= shot["reference"]["timestamp_ms"] < shot["end_ms"]
               for shot in result["shots"])


def test_rotation_and_audio_metadata(tmp_path):
    original = tmp_path / "original.mp4"
    source = tmp_path / "rotated.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=160x90:r=10:d=1",
         "-f", "lavfi", "-i", "sine=frequency=1000:duration=1", "-c:v", "libx264", "-c:a", "aac",
         "-shortest", str(original)], check=True, capture_output=True, timeout=30,
    )
    options = subprocess.run(["ffmpeg", "-h", "full"], capture_output=True, timeout=30).stdout
    command = (["-display_rotation", "90", "-i", str(original), "-c", "copy"]
               if b"-display_rotation" in options else
               ["-i", str(original), "-c", "copy", "-metadata:s:v:0", "rotate=90"])
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *command, str(source)],
                   check=True, capture_output=True, timeout=30)
    result = analyze(source, tmp_path / "result")
    assert abs(result["metadata"]["rotation"]) == 90
    assert result["metadata"]["audio_present"] is True
    assert len(result["metadata"]["audio_stream_indices"]) == 1


def test_probe_timeout_does_not_publish(monkeypatch, tmp_path):
    from app.services.media import timeline

    source = tmp_path / "source.mp4"
    source.write_bytes(b"input")
    monkeypatch.setattr(timeline, "_run", lambda *args, **kwargs: (_ for _ in ()).throw(
        MediaError("MEDIA_PROCESS_FAILED")))
    with pytest.raises(MediaError, match="MEDIA_PROCESS_FAILED"):
        analyze(source, tmp_path / "result")
    assert not (tmp_path / "result").exists()


def test_process_timeout_terminates_unresponsive_child():
    from app.services.media.timeline import _run

    with pytest.raises(MediaError, match="MEDIA_PROCESS_FAILED"):
        _run([sys.executable, "-c", "import threading; threading.Event().wait()"], timeout=0.2)


@pytest.mark.parametrize("frames", [
    [{"best_effort_timestamp": 0}, {}],
    [{"best_effort_timestamp": 2}, {"best_effort_timestamp": 1}],
    [{"best_effort_timestamp": 1}, {"best_effort_timestamp": 1}],
])
def test_invalid_timestamps_are_rejected_without_result(monkeypatch, tmp_path, frames):
    from app.services.media import timeline

    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic")
    metadata = {"streams": [{"codec_type": "video", "width": 16, "height": 16, "time_base": "1/1000"}],
                "format": {"format_name": "mov,mp4"}}
    responses = iter([json.dumps(metadata).encode(), json.dumps({"frames": frames}).encode()])
    monkeypatch.setattr(timeline, "_run", lambda *args, **kwargs: next(responses))
    with pytest.raises(MediaError):
        analyze(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("rate,duration,size", [
    (rate, duration, size)
    for rate in (10, 15, 20, 25, 30)
    for duration, size in ((0.4, "160x90"), (0.8, "90x160"), (1.0, "160x90"), (1.2, "90x160"))
])
def test_synthetic_hard_cut_boundaries(tmp_path, rate, duration, size):
    source = tmp_path / "synthetic.mp4"
    make_video(source, f"color=red:s={size}:r={rate}:d={duration}",
               f"color=blue:s={size}:r={rate}:d={duration}")
    result = analyze(source, tmp_path / "out")
    assert len(result["shots"]) == 2
    assert abs(result["shots"][1]["start_ms"] - duration * 1000) <= 150
