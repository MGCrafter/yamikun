"""Spaß-Befehle: /8ball, /insult, /whoisguilty, /summondemon, /existential."""

from __future__ import annotations

import asyncio
import logging
import random
import re

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

MENTION_RE = re.compile(r"<@!?(\d+)>")

EIGHTBALL = [
    "Ja.", "Nein.", "Definitiv ja.", "Auf gar keinen Fall.", "Vielleicht…",
    "Frag später nochmal.", "Das steht in den Sternen.", "Ganz sicher!",
    "Eher nicht.", "Die Zeichen deuten auf ja.", "Sehr zweifelhaft.",
    "Tu lieber nichts.", "Verlass dich nicht drauf.", "Absolut!",
    "Träum weiter.", "Die Miesmuschel sagt: nein.", "Wenn du dich traust.",
    "Heute nicht.", "Das Universum schweigt dazu.", "Klar, warum nicht.",
]

INSULT_PREFIX = ["du", "du echt", "du absoluter", "du kleiner", "du wandelnder"]
INSULT_ADJ = [
    "galaktischer", "verpeilter", "ranziger", "quadratischer", "suboptimaler",
    "audiovisueller", "hydraulischer", "postmoderner", "frittierter",
    "überbackener", "tiefgekühlter", "handgeschnitzter", "bürokratischer",
    "freilaufender", "vakuumverpackter",
]
INSULT_NOUN = [
    "Gurkenbefruchter", "Toastscheiben-Hypnotiseur", "Sockenverlierer",
    "Kaktusflüsterer", "Teppichkantenkenner", "Wackelpudding-Ingenieur",
    "Nasenflöten-Virtuose", "Tütensuppen-Philosoph", "Parkscheinautomat",
    "Kühlschrank-Diplomat", "Staubsauger-Beauftragter", "Restmüll-Connaisseur",
    "Brötchentaucher", "Mettigel-Beauftragter", "Kabelsalat-Sommelier",
]

# Existenzkrise-Generator: Bausteine je Stil
CURSED = [
    "Ein {a} ist nur ein {b}, das zu lange nachgedacht hat.",
    "Jeder {a} war mal ein {b}, der aufgegeben hat.",
    "Am Ende sind wir alle nur {a} im Wartezimmer des {b}.",
]
FAKEDEEP = [
    "Wir sind nur {a} im {b} der {c}. 🌌",
    "Vielleicht war der echte {a} der {b}, den wir unterwegs verloren haben. 🥀",
    "Die Stille zwischen zwei {a} ist lauter als jeder {b}. 🌙",
]
PHIL = [
    "Wenn ein {a} im Wald umfällt und niemand pingt — war es dann ein {b}?",
    "Ist ein {a} ohne {b} überhaupt ein {a}?",
    "Warum {a}, wenn man auch einfach {b} könnte?",
]
WORDS_A = ["Gedanke", "Toaster", "Montag", "Algorithmus", "Schatten", "Keks", "Traum", "Pixel"]
WORDS_B = ["Versprechen", "Kühlschrank", "Sonnenuntergang", "Bug", "Seufzer", "Krümel", "Code", "Echo"]
WORDS_C = ["Ewigkeit", "Cloud", "Realität", "WLAN-Reichweite", "Leere", "Timeline"]

# Feste Zitate (keine Bausteine) — lässt sich beliebig erweitern.
CUSTOM = [
    "Wenn dir das Leben Steine in den Weg wirft, nimm diese Steine und wirf sie ihm ins Gesicht.",
]


def _existential(style: str) -> str:
    if style == "custom":
        return random.choice(CUSTOM)
    if style == "cursed":
        t = random.choice(CURSED)
    elif style == "fakedeep":
        t = random.choice(FAKEDEEP)
    else:
        t = random.choice(PHIL)
    return t.format(a=random.choice(WORDS_A), b=random.choice(WORDS_B), c=random.choice(WORDS_C))


class FunCog(commands.Cog):
    """Spaß-Commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _emoji(self, guild: discord.Guild | None, names: list[str], fallback: str) -> str:
        if guild is not None:
            for name in names:
                e = discord.utils.get(guild.emojis, name=name)
                if e is not None:
                    return str(e)
        return fallback

    @app_commands.command(name="8ball", description="Stelle der magischen Miesmuschel eine Frage.")
    @app_commands.describe(frage="Deine Ja/Nein-Frage")
    async def eightball(self, interaction: discord.Interaction, frage: str) -> None:
        embed = discord.Embed(color=0x2C2F33)
        embed.add_field(name="🎱 Frage", value=frage, inline=False)
        embed.add_field(name="Antwort", value=f"*{random.choice(EIGHTBALL)}*", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="insult", description="Eine zufällige, harmlose Beleidigung.")
    @app_commands.describe(user="Optional: wen treffen?")
    async def insult(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        text = f"{random.choice(INSULT_PREFIX)} {random.choice(INSULT_ADJ)} {random.choice(INSULT_NOUN)}!"
        target = f"{user.mention}, " if user else ""
        await interaction.response.send_message(
            f"{target}{text}", allowed_mentions=discord.AllowedMentions(users=True)
        )

    @app_commands.command(name="whoisguilty", description="Der Bot ermittelt den Schuldigen.")
    @app_commands.describe(verdaechtige="Pinge die Verdächtigen (mehrere möglich)")
    async def whoisguilty(self, interaction: discord.Interaction, verdaechtige: str) -> None:
        ids = list(dict.fromkeys(MENTION_RE.findall(verdaechtige)))  # eindeutig, Reihenfolge erhalten
        if not ids:
            await interaction.response.send_message(
                "⚠️ Pinge mindestens eine Person (z.B. `@User`).", ephemeral=True
            )
            return
        guilty = random.choice(ids)
        await interaction.response.send_message(
            f"🔍 Die Ermittlungen laufen…\n…\n⚖️ **Schuldig ist: <@{guilty}>!** Kein Zweifel.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @app_commands.command(name="existential", description="Cursed Weisheiten, Fake-deep Quotes & philosophischer Unsinn.")
    @app_commands.describe(stil="Welcher Stil? (Standard: zufällig)")
    @app_commands.choices(
        stil=[
            app_commands.Choice(name="Cursed Weisheit", value="cursed"),
            app_commands.Choice(name="Fake-deep Quote", value="fakedeep"),
            app_commands.Choice(name="Philosophischer Unsinn", value="phil"),
            app_commands.Choice(name="Custom Zitat", value="custom"),
        ]
    )
    async def existential(
        self, interaction: discord.Interaction, stil: app_commands.Choice[str] | None = None
    ) -> None:
        style = stil.value if stil else random.choice(["cursed", "fakedeep", "phil", "custom"])
        quote = _existential(style)
        embed = discord.Embed(description=f'*„{quote}“*', color=0x6C5CE7)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="summondemon", description="Beschwöre Yami… auf eigene Gefahr.")
    @app_commands.checks.cooldown(1, 30.0)
    async def summondemon(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if random.random() < 0.5:
            luv = self._emoji(guild, ["YamiLuv"], "💖")
            await interaction.response.send_message(
                f"✨ Yami erscheint… und ist heute **gnädig**. {luv}"
            )
        else:
            angry = self._emoji(guild, ["YamiAngry", "YamiSmug"], "😠")
            await interaction.response.send_message(f"🔥 Yami ist **ERZÜRNT!** {angry}")
            channel = interaction.channel
            if isinstance(channel, discord.abc.Messageable):
                for _ in range(9):
                    await asyncio.sleep(0.4)
                    try:
                        await channel.send(angry * 3)
                    except discord.HTTPException:
                        break


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
