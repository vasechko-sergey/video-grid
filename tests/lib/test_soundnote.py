"""The sound note beside a music-less delivery (design 2026-10-20 §4)."""
from scripts.lib import soundnote
from scripts.lib.models import MusicSpec

_MS = MusicSpec(track="/m/cache/youtube-the-drums-lets-go-surfing-75be4374.webm",
                start_offset=49.0, duration=48.0, tempo=117.2, beats=(0.0, 0.5),
                energy=(0.3,), energy_hz=2.0)
_META = {"title": "Let's Go Surfing", "artist": "The Drums", "source": "youtube",
         "source_url": "https://www.youtube.com/watch?v=x", "license": "unknown (any lane)",
         "date": "2026-10-16"}


def test_clock_reads_like_an_apps_start_slider():
    assert [soundnote.clock(t) for t in (0, 49.0, 125.25, 59.96)] == [
        "0:00.0", "0:49.0", "2:05.2", "1:00.0"]


def test_the_note_names_the_track_the_start_and_the_cuts():
    text = soundnote.render(_MS, _META, "REEL_v5.mp4", "abc123", 45.66, [5.34, 10.87],
                            platform="reels")
    assert text.startswith("# Sound for REEL_v5.mp4 — attach it in Instagram\n")
    for line in ("| Track | The Drums — Let's Go Surfing |",
                 "| Source | youtube · https://www.youtube.com/watch?v=x · licence: unknown (any lane) |",
                 "| Start in the track | 0:49.0 |",
                 "| Length | 45.7 s (the whole reel) |",
                 "| Cuts | 5.3 · 10.9 s |",
                 "2. Add the sound: search \"The Drums Let's Go Surfing\".",
                 "3. Set its start to 0:49.0.",
                 "5. Check by ear that the first cut (5.3 s) lands on a beat."):
        assert line in text, line
    # the caveat this design cannot close, naming the file the offset was measured on
    assert "youtube-the-drums-lets-go-surfing-75be4374.webm" in text
    assert "sha256 `abc123`" in text and "not attested" in text


def test_a_local_track_with_no_record_is_named_by_its_file():
    text = soundnote.render(_MS, None, "REEL_v1.mp4", "d", 30.0, [], platform="")
    assert "attach it in the app" in text
    assert "| Track | youtube-the-drums-lets-go-surfing-75be4374 |" in text
    assert "no music_fetch record" in text and "| Cuts | none (one shot) |" in text



def test_a_silent_stem_is_called_silent_not_natural_sound():
    text = soundnote.render(_MS, _META, "REEL_v5.mp4", "d", 45.0, [5.0],
                            ambient=False, sfx=False)
    assert "and silent: the reel had no natural sound to keep" in text
    assert "natural sound kept" not in text and "whooshes" not in text
    assert "4. The file has no natural sound" in text


def test_whooshes_are_named_only_when_the_stem_has_them():
    plain = soundnote.render(_MS, _META, "R.mp4", "d", 45.0, [5.0], ambient=True, sfx=False)
    both = soundnote.render(_MS, _META, "R.mp4", "d", 45.0, [5.0], ambient=True, sfx=True)
    assert "whooshes" not in plain and "the natural sound and the transition whooshes kept" in both


def test_a_dynamic_music_mix_is_said_to_shift_the_natural_sound():
    text = soundnote.render(_MS, _META, "R.mp4", "d", 45.0, [5.0], linear=False)
    assert "levelled dynamically" in text
    assert "levelled dynamically" not in soundnote.render(_MS, _META, "R.mp4", "d", 45.0, [5.0])


def test_an_unfitted_cut_gets_no_beat_check():
    """Only a pacing pass fits the cuts to the music; without one, 'the first cut lands
    on a beat' would pull the start away from where the music was actually taken."""
    text = soundnote.render(_MS, _META, "R.mp4", "d", 45.0, [5.0], fitted=False)
    assert "not fitted to this song's beats" in text
    assert "lands on a beat" not in text and "nudge the start" not in text
