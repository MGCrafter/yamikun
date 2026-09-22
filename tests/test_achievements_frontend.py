from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_achievement_web_route_and_friend_comparison_ui_exist():
    app = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    dashboard = (ROOT / "frontend/src/pages/UserDashboard.tsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/Achievements.tsx").read_text(encoding="utf-8")
    landing = (ROOT / "frontend/src/pages/Landing.tsx").read_text(encoding="utf-8")

    assert 'path="/u/:gid/achievements"' in app
    assert "/achievements" in dashboard
    assert "/api/u/${gid}/achievements" in page
    assert "friends" in page
    assert "Geheimes Achievement" in page
    assert "<strong>Tipp:</strong>" in page
    assert "Geheime Achievements bleiben vollständig privat" in page
    assert "Dein Turm. Deine Regeln." in landing
    assert "Yami hält die Wache." in landing
