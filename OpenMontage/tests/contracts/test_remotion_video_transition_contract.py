from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_video_scene_honors_hard_cut_tokens_and_backing_color() -> None:
    source = (REPO_ROOT / "remotion-composer/src/Explainer.tsx").read_text(
        encoding="utf-8"
    )

    assert '["cut", "none"].includes((transitionIn || "").toLowerCase())' in source
    assert '["cut", "none"].includes((transitionOut || "").toLowerCase())' in source
    assert "transitionIn={cut.transition_in}" in source
    assert "transitionOut={cut.transition_out}" in source
    assert "sceneDurationSeconds={cut.out_seconds - cut.in_seconds}" in source
    assert "Math.round(sceneDurationSeconds * fps)" in source
    assert "durationInFrames - transitionFrames" in source
    assert "backgroundColor={cut.backgroundColor}" in source


def test_cinematic_fades_are_bounded_by_each_scene_duration() -> None:
    source = (REPO_ROOT / "remotion-composer/src/CinematicRenderer.tsx").read_text(
        encoding="utf-8"
    )

    assert "Math.round(scene.durationSeconds * fps)" in source
    assert "durationInFrames - fadeOutFrames" in source
