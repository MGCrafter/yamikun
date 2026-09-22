from __future__ import annotations

import discord

from cogs.profile import ProfileView


def test_profile_favorite_carousel_render_does_not_accumulate_fields():
    base = discord.Embed(title="Profil von Jessy")
    base.add_field(name="Level", value="19", inline=True)
    base.add_field(name="Coins", value="114.211", inline=True)
    favs: list[tuple[str, str, str, str, str | None]] = [
        ("league of legends", "lol-card", "Signature Prestige Cybercat Yuumi", "legendary", None),
        ("valorant", "valorant-card", "Signature Neon Card", "epic", None),
    ]
    view = ProfileView(db=None, owner_id=123, base_embed=base, favs=favs, is_self=True)

    first = view.render()
    view.index = 1
    second = view.render()
    view.index = 0
    third = view.render()

    assert [field.name for field in base.fields] == ["Level", "Coins"]
    assert [field.name for field in first.fields].count("⭐ Lieblingskarte · league of legends (1/2)") == 1
    assert [field.name for field in second.fields].count("⭐ Lieblingskarte · valorant (2/2)") == 1
    assert [field.name for field in third.fields].count("⭐ Lieblingskarte · league of legends (1/2)") == 1
    assert len(first.fields) == 3
    assert len(second.fields) == 3
    assert len(third.fields) == 3
