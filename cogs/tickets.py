"""Ticket-System — privater Support pro Mitglied über Threads.

Ablauf:
- Ein **Panel** (Embed + Auswahlmenü) wird in einen Channel gepostet. Jede
  Auswahl entspricht einem konfigurierbaren **Thema** (z.B. Support, Bewerbung).
- Wählt jemand ein Thema, öffnet der Bot einen **privaten Thread** unter dem
  Panel-Channel — nur der Ersteller (und das Support-Team mit „Threads
  verwalten") sehen ihn. Die konfigurierte Support-Rolle wird gepingt.
- Im Ticket gibt es Buttons: **Übernehmen** (Claim) und **Schließen**. Beim
  Schließen wird ein **Transcript** (Textdatei) in den Log-Channel gepostet und
  der Thread archiviert/gesperrt.

Konfiguration: per `/ticket …`-Slash-Commands UND über das Webpanel. Beide rufen
dieselben Helfer dieses Cogs auf, damit Panel & Persistenz konsistent bleiben.

Persistente Komponenten (überleben Neustarts): Das Cog registriert in cog_load()
das Panel-Auswahlmenü (custom_id „ticket:open") und die Steuer-Buttons
(„ticket:claim" / „ticket:close") über bot.add_view().
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("oaken-tower-bot")

ACCENT = 0x7C3AED
MAX_OPEN_PER_USER = 3  # so viele offene Tickets darf ein Mitglied gleichzeitig haben


def _slug(text: str) -> str:
    """Thread-tauglicher Namensteil: Kleinbuchstaben, nur a-z0-9 und Bindestriche."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "ticket"


def _opt_emoji(raw: str | None) -> discord.PartialEmoji | None:
    """Emoji-String → PartialEmoji für SelectOption (Unicode oder Custom)."""
    if not raw:
        return None
    try:
        return discord.PartialEmoji.from_str(raw)
    except Exception:  # noqa: BLE001
        return None


# --- Persistente UI-Komponenten ----------------------------------------------


class TicketCategorySelect(discord.ui.Select):
    """Auswahlmenü im Panel. Ein fester custom_id, Optionen kommen pro Server."""

    def __init__(self, cog: "TicketCog", categories: list[dict] | None = None) -> None:
        self.cog = cog
        options: list[discord.SelectOption] = []
        for cat in categories or []:
            options.append(
                discord.SelectOption(
                    label=cat["label"][:100],
                    value=str(cat["id"]),
                    description=(cat.get("description") or None) and cat["description"][:100],
                    emoji=_opt_emoji(cat.get("emoji")),
                )
            )
        if not options:
            # Default-Thema, wenn (noch) keine Kategorien angelegt sind.
            options = [discord.SelectOption(label="Support", value="0", emoji="🎫")]
        super().__init__(
            placeholder="Thema wählen, um ein Ticket zu öffnen…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket:open",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.open_ticket(interaction, self.values[0])


class TicketPanelView(discord.ui.View):
    """Persistente View für das Ticket-Panel."""

    def __init__(self, cog: "TicketCog", categories: list[dict] | None = None) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect(cog, categories))


class TicketControlView(discord.ui.View):
    """Persistente Steuer-Buttons innerhalb eines Tickets."""

    def __init__(self, cog: "TicketCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Übernehmen", style=discord.ButtonStyle.secondary,
        emoji="🙋", custom_id="ticket:claim",
    )
    async def claim(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.claim_ticket(interaction)

    @discord.ui.button(
        label="Schließen", style=discord.ButtonStyle.danger,
        emoji="🔒", custom_id="ticket:close",
    )
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.close_ticket_flow(interaction)


# --- Cog ----------------------------------------------------------------------


class TicketCog(commands.Cog):
    """Ticket-System: Panel, private Threads, Claim/Close, Transcript-Log."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.db = bot.db  # type: ignore[attr-defined]

    async def cog_load(self) -> None:
        # Persistente Views registrieren, damit Panel & Buttons nach einem
        # Neustart weiterhin reagieren (Dummy-Instanzen genügen — sie matchen
        # eingehende Interaktionen über die festen custom_ids).
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(TicketControlView(self))

    # --- Hilfen ---------------------------------------------------------------

    @staticmethod
    def _is_support(member: discord.Member, cfg: dict) -> bool:
        if member.guild_permissions.manage_guild:
            return True
        role_id = cfg.get("support_role_id")
        return bool(role_id) and any(r.id == role_id for r in member.roles)

    def _panel_embed(self, cfg: dict) -> discord.Embed:
        return discord.Embed(title=cfg["title"], description=cfg["text"], color=ACCENT)

    def _panel_view(self, guild_id: int) -> TicketPanelView:
        return TicketPanelView(self, self.db.list_ticket_categories(guild_id))

    async def post_panel(
        self, guild: discord.Guild, channel: discord.TextChannel
    ) -> discord.Message:
        """Postet das Panel (löscht ein altes), speichert es und aktiviert das System."""
        cfg = self.db.get_ticket_config(guild.id)
        # Altes Panel entfernen, falls vorhanden.
        if cfg["panel_channel_id"] and cfg["panel_message_id"]:
            old_ch = guild.get_channel(cfg["panel_channel_id"])
            if isinstance(old_ch, discord.TextChannel):
                try:
                    old = await old_ch.fetch_message(cfg["panel_message_id"])
                    await old.delete()
                except discord.HTTPException:
                    pass
        msg = await channel.send(embed=self._panel_embed(cfg), view=self._panel_view(guild.id))
        self.db.set_ticket_panel(guild.id, channel.id, msg.id)
        self.db.set_ticket_config(guild.id, enabled=True)
        return msg

    async def refresh_panel(self, guild: discord.Guild) -> None:
        """Bestehendes Panel an geänderte Kategorien/Texte anpassen (falls vorhanden)."""
        cfg = self.db.get_ticket_config(guild.id)
        if not (cfg["panel_channel_id"] and cfg["panel_message_id"]):
            return
        ch = guild.get_channel(cfg["panel_channel_id"])
        if not isinstance(ch, discord.TextChannel):
            return
        try:
            msg = await ch.fetch_message(cfg["panel_message_id"])
            await msg.edit(embed=self._panel_embed(cfg), view=self._panel_view(guild.id))
        except discord.HTTPException:
            pass

    # --- Kern-Aktionen (von Buttons UND Slash-Commands genutzt) ---------------

    async def open_ticket(self, interaction: discord.Interaction, value: str) -> None:
        guild = interaction.guild
        if guild is None:
            return
        cfg = self.db.get_ticket_config(guild.id)
        if not cfg["enabled"]:
            await interaction.response.send_message(
                "🎫 Das Ticket-System ist gerade deaktiviert.", ephemeral=True
            )
            return
        parent = interaction.channel
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message(
                "⚠️ Hier lassen sich keine Tickets öffnen.", ephemeral=True
            )
            return
        if self.db.count_open_tickets(guild.id, interaction.user.id) >= MAX_OPEN_PER_USER:
            await interaction.response.send_message(
                f"⚠️ Du hast bereits {MAX_OPEN_PER_USER} offene Tickets. "
                "Schließe erst eines, bevor du ein neues öffnest.",
                ephemeral=True,
            )
            return

        cat_id: int | None = None
        label = "Support"
        if value and value.isdigit() and value != "0":
            cat = self.db.get_ticket_category(guild.id, int(value))
            if cat:
                cat_id, label = cat["id"], cat["label"]

        await interaction.response.defer(ephemeral=True)
        number = self.db.next_ticket_number(guild.id)
        name = f"ticket-{number:04d}-{_slug(interaction.user.display_name)}"[:100]
        try:
            thread = await parent.create_thread(
                name=name,
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason=f"Ticket #{number} von {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Ich darf hier keine privaten Threads erstellen. Bitte gib mir das "
                "Recht **Private Threads erstellen** in diesem Channel.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            logger.exception("Ticket-Thread konnte nicht erstellt werden (Guild %s).", guild.id)
            await interaction.followup.send(
                "⚠️ Das Ticket konnte nicht erstellt werden.", ephemeral=True
            )
            return

        self.db.create_ticket(
            thread.id, guild.id, parent.id, interaction.user.id, cat_id, label, number, time.time()
        )
        try:
            await thread.add_user(interaction.user)
        except discord.HTTPException:
            pass

        support_role = guild.get_role(cfg["support_role_id"]) if cfg["support_role_id"] else None
        ping = f"{support_role.mention} " if support_role else ""
        embed = discord.Embed(
            title=f"🎫 Ticket #{number:04d} · {label}",
            description=(
                f"Hallo {interaction.user.mention}! Beschreibe dein Anliegen bitte so "
                "genau wie möglich — ein Teammitglied meldet sich gleich bei dir.\n\n"
                "Mit **Schließen** kannst du das Ticket beenden, wenn alles erledigt ist."
            ),
            color=ACCENT,
        )
        embed.set_footer(text=f"Geöffnet von {interaction.user.display_name}")
        await thread.send(
            content=f"{ping}{interaction.user.mention}".strip(),
            embed=embed,
            view=TicketControlView(self),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
        )
        await interaction.followup.send(
            f"✅ Dein Ticket wurde erstellt: {thread.mention}", ephemeral=True
        )

    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        ticket = self.db.get_ticket(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message(
                "⚠️ Das ist kein offenes Ticket.", ephemeral=True
            )
            return
        cfg = self.db.get_ticket_config(interaction.guild_id)
        if not self._is_support(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message(
                "⛔ Nur das Support-Team kann Tickets übernehmen.", ephemeral=True
            )
            return
        if ticket["claimed_by"]:
            await interaction.response.send_message(
                f"ℹ️ Dieses Ticket wurde bereits von <@{ticket['claimed_by']}> übernommen.",
                ephemeral=True,
            )
            return
        self.db.set_ticket_claimed(interaction.channel_id, interaction.user.id)
        await interaction.response.send_message(
            f"🙋 {interaction.user.mention} kümmert sich jetzt um dieses Ticket."
        )

    async def close_ticket_flow(self, interaction: discord.Interaction) -> None:
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.response.send_message(
                "⚠️ Dieser Befehl funktioniert nur in einem Ticket-Thread.", ephemeral=True
            )
            return
        ticket = self.db.get_ticket(thread.id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message(
                "⚠️ Das ist kein offenes Ticket.", ephemeral=True
            )
            return
        cfg = self.db.get_ticket_config(interaction.guild_id)
        is_admin = interaction.user.guild_permissions.manage_guild  # type: ignore[union-attr]
        is_opener = interaction.user.id == ticket["opener_id"]
        is_claimer = bool(ticket["claimed_by"]) and interaction.user.id == ticket["claimed_by"]
        if not (is_admin or is_opener or is_claimer):
            if ticket["claimed_by"]:
                hint = (
                    f"⛔ Dieses Ticket bearbeitet <@{ticket['claimed_by']}>. "
                    "Nur der Bearbeiter oder ein Admin kann es schließen."
                )
            else:
                hint = (
                    "⛔ Übernimm das Ticket zuerst mit **Übernehmen** — danach kannst nur du "
                    "(oder ein Admin) es schließen."
                )
            await interaction.response.send_message(
                hint, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
            )
            return
        await interaction.response.send_message(
            f"🔒 Ticket wird von {interaction.user.mention} geschlossen — Transcript wird gesichert…"
        )
        await self._finalize_close(thread, ticket, cfg, interaction.user)

    async def _finalize_close(
        self, thread: discord.Thread, ticket: dict, cfg: dict, closed_by: discord.abc.User
    ) -> None:
        self.db.close_ticket(thread.id)
        guild = thread.guild

        # Nachrichten strukturiert sammeln und als Transcript (für die Web-Ansicht)
        # speichern — unabhängig davon, ob ein Log-Channel gesetzt ist.
        try:
            messages = await self._collect_messages(thread)
        except discord.HTTPException:
            logger.exception("Ticket-Verlauf konnte nicht gelesen werden.")
            messages = []
        token = secrets.token_urlsafe(16)
        opener = guild.get_member(ticket["opener_id"])
        self.db.save_ticket_transcript(
            token=token,
            thread_id=thread.id,
            guild_id=guild.id,
            number=ticket["number"],
            category_label=ticket["category_label"],
            opener_id=ticket["opener_id"],
            opener_name=opener.display_name if opener else str(ticket["opener_id"]),
            closed_by_id=closed_by.id,
            closed_by_name=getattr(closed_by, "display_name", str(closed_by)),
            closed_at=time.time(),
            message_count=len(messages),
            data=json.dumps(messages, ensure_ascii=False),
        )
        base = os.environ.get("WEB_BASE_URL", "").rstrip("/")
        url = f"{base}/t/{token}" if base else None

        # In den Log-Channel ein Embed mit Link zum Web-Transcript posten.
        log_id = cfg.get("log_channel_id")
        if log_id:
            log_ch = guild.get_channel(log_id)
            if isinstance(log_ch, discord.TextChannel):
                embed = discord.Embed(
                    title=f"🎫 Ticket #{ticket['number']:04d} geschlossen · {ticket['category_label']}",
                    color=ACCENT,
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name="Ersteller", value=f"<@{ticket['opener_id']}>", inline=True)
                if ticket["claimed_by"]:
                    embed.add_field(
                        name="Bearbeitet von", value=f"<@{ticket['claimed_by']}>", inline=True
                    )
                embed.add_field(name="Geschlossen von", value=closed_by.mention, inline=True)
                embed.add_field(name="Nachrichten", value=str(len(messages)), inline=True)
                view = None
                if url:
                    embed.add_field(
                        name="Transcript", value=f"[Im Browser ansehen →]({url})", inline=False
                    )
                    view = discord.ui.View()
                    view.add_item(
                        discord.ui.Button(label="Transcript ansehen", url=url, emoji="🧾")
                    )
                else:
                    embed.set_footer(text="WEB_BASE_URL ist nicht gesetzt — kein öffentlicher Link.")
                try:
                    await log_ch.send(embed=embed, view=view)
                except discord.HTTPException:
                    logger.exception("Ticket-Log konnte nicht gepostet werden.")

        try:
            await thread.edit(
                archived=True, locked=True, reason=f"Ticket geschlossen von {closed_by}"
            )
        except discord.HTTPException:
            pass

    async def _collect_messages(self, thread: discord.Thread) -> list[dict]:
        """Liest den Thread-Verlauf in eine serialisierbare Nachrichtenliste."""
        out: list[dict] = []
        async for m in thread.history(limit=None, oldest_first=True):
            out.append({
                "author_id": str(m.author.id),
                "author_name": m.author.display_name,
                "avatar": str(m.author.display_avatar.url),
                "bot": bool(m.author.bot),
                "ts": m.created_at.timestamp(),
                "content": (m.clean_content or "")[:4000],
                "attachments": [
                    {
                        "url": a.url,
                        "name": a.filename,
                        "is_image": bool((a.content_type or "").startswith("image/")),
                    }
                    for a in m.attachments
                ],
            })
            if len(out) >= 2000:  # Schutz vor extrem langen Tickets
                break
        return out

    # --- Slash-Commands -------------------------------------------------------

    group = app_commands.Group(
        name="ticket", description="Ticket-System verwalten und nutzen.", guild_only=True
    )
    category = app_commands.Group(
        name="category", description="Ticket-Themen verwalten (Panel-Optionen).", parent=group
    )

    async def _require_manage(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:  # type: ignore[union-attr]
            return True
        await interaction.response.send_message(
            "⛔ Dafür brauchst du die Berechtigung **Server verwalten**.", ephemeral=True
        )
        return False

    @group.command(name="panel", description="Postet (oder erneuert) das Ticket-Panel in einem Channel.")
    @app_commands.describe(channel="Channel fürs Panel (Standard: aktueller Channel)")
    async def ticket_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        if not await self._require_manage(interaction):
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message(
                "⚠️ Bitte einen normalen Text-Channel wählen.", ephemeral=True
            )
            return
        try:
            await self.post_panel(interaction.guild, target)  # type: ignore[arg-type]
        except discord.Forbidden:
            await interaction.response.send_message(
                f"⚠️ Ich darf in {target.mention} nicht schreiben.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Ticket-Panel in {target.mention} gepostet. Das System ist aktiv.", ephemeral=True
        )

    @group.command(name="disable", description="Deaktiviert das Ticket-System (Panel bleibt entfernt).")
    async def ticket_disable(self, interaction: discord.Interaction) -> None:
        if not await self._require_manage(interaction):
            return
        cfg = self.db.get_ticket_config(interaction.guild_id)
        if cfg["panel_channel_id"] and cfg["panel_message_id"]:
            ch = interaction.guild.get_channel(cfg["panel_channel_id"])  # type: ignore[union-attr]
            if isinstance(ch, discord.TextChannel):
                try:
                    msg = await ch.fetch_message(cfg["panel_message_id"])
                    await msg.delete()
                except discord.HTTPException:
                    pass
        self.db.set_ticket_panel(interaction.guild_id, None, None)
        self.db.set_ticket_config(interaction.guild_id, enabled=False)
        await interaction.response.send_message(
            "🎫 Ticket-System deaktiviert und Panel entfernt.", ephemeral=True
        )

    @group.command(name="setrole", description="Legt die Support-Rolle fest (wird bei neuen Tickets gepingt).")
    @app_commands.describe(role="Rolle des Support-Teams")
    async def ticket_setrole(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not await self._require_manage(interaction):
            return
        self.db.set_ticket_config(interaction.guild_id, support_role_id=role.id)
        await interaction.response.send_message(
            f"✅ Support-Rolle auf {role.mention} gesetzt.", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @group.command(name="setlog", description="Channel für Ticket-Transcripts festlegen (leer = aus).")
    @app_commands.describe(channel="Log-Channel (weglassen, um das Logging abzuschalten)")
    async def ticket_setlog(
        self, interaction: discord.Interaction, channel: discord.TextChannel | None = None
    ) -> None:
        if not await self._require_manage(interaction):
            return
        self.db.set_ticket_config(
            interaction.guild_id, log_channel_id=channel.id if channel else None
        )
        msg = (
            f"✅ Transcripts werden in {channel.mention} geloggt."
            if channel else "✅ Transcript-Logging deaktiviert."
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @group.command(name="config", description="Zeigt die aktuelle Ticket-Konfiguration.")
    async def ticket_config(self, interaction: discord.Interaction) -> None:
        if not await self._require_manage(interaction):
            return
        cfg = self.db.get_ticket_config(interaction.guild_id)
        cats = self.db.list_ticket_categories(interaction.guild_id)
        role = interaction.guild.get_role(cfg["support_role_id"]) if cfg["support_role_id"] else None  # type: ignore[union-attr]
        log = interaction.guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None  # type: ignore[union-attr]
        panel = interaction.guild.get_channel(cfg["panel_channel_id"]) if cfg["panel_channel_id"] else None  # type: ignore[union-attr]
        lines = [
            f"**Status:** {'🟢 aktiv' if cfg['enabled'] else '🔴 aus'}",
            f"**Panel-Channel:** {panel.mention if isinstance(panel, discord.TextChannel) else '—'}",
            f"**Support-Rolle:** {role.mention if role else '—'}",
            f"**Log-Channel:** {log.mention if isinstance(log, discord.TextChannel) else '—'}",
            "",
            "**Themen:**",
        ]
        if cats:
            lines += [
                f"`{c['id']}` {c['emoji'] or '•'} {c['label']}"
                + (f" — {c['description']}" if c["description"] else "")
                for c in cats
            ]
        else:
            lines.append("— keine (Standard-Thema »Support«)")
        embed = discord.Embed(title="🎫 Ticket-Konfiguration", description="\n".join(lines), color=ACCENT)
        await interaction.response.send_message(
            embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @group.command(name="close", description="Schließt das aktuelle Ticket.")
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        await self.close_ticket_flow(interaction)

    @group.command(name="claim", description="Übernimmt das aktuelle Ticket (Support).")
    async def ticket_claim(self, interaction: discord.Interaction) -> None:
        await self.claim_ticket(interaction)

    @group.command(name="add", description="Fügt jemanden zum aktuellen Ticket hinzu (Support).")
    @app_commands.describe(user="Mitglied, das hinzugefügt werden soll")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        thread = interaction.channel
        if not isinstance(thread, discord.Thread) or not self.db.get_ticket(thread.id):
            await interaction.response.send_message(
                "⚠️ Das funktioniert nur in einem Ticket-Thread.", ephemeral=True
            )
            return
        cfg = self.db.get_ticket_config(interaction.guild_id)
        if not self._is_support(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message(
                "⛔ Nur das Support-Team kann Mitglieder hinzufügen.", ephemeral=True
            )
            return
        try:
            await thread.add_user(user)
        except discord.HTTPException:
            await interaction.response.send_message(
                "⚠️ Konnte das Mitglied nicht hinzufügen.", ephemeral=True
            )
            return
        await interaction.response.send_message(f"➕ {user.mention} wurde zum Ticket hinzugefügt.")

    # --- /ticket category … ---------------------------------------------------

    @category.command(name="add", description="Legt ein Ticket-Thema (Panel-Option) an.")
    @app_commands.describe(
        label="Name des Themas (z.B. Support, Bewerbung, Report)",
        emoji="Optionales Emoji für die Auswahl",
        description="Optionaler Hinweistext unter dem Thema",
    )
    async def category_add(
        self,
        interaction: discord.Interaction,
        label: str,
        emoji: str | None = None,
        description: str | None = None,
    ) -> None:
        if not await self._require_manage(interaction):
            return
        cats = self.db.list_ticket_categories(interaction.guild_id)
        if len(cats) >= 25:
            await interaction.response.send_message(
                "⚠️ Mehr als 25 Themen unterstützt das Auswahlmenü nicht.", ephemeral=True
            )
            return
        cid = self.db.add_ticket_category(
            interaction.guild_id, label.strip()[:100],
            (emoji or "").strip() or None, (description or "").strip()[:100] or None,
        )
        await self.refresh_panel(interaction.guild)  # type: ignore[arg-type]
        await interaction.response.send_message(
            f"✅ Thema **{label}** angelegt (ID `{cid}`).", ephemeral=True
        )

    @category.command(name="remove", description="Entfernt ein Ticket-Thema.")
    @app_commands.describe(category_id="ID des Themas (siehe /ticket category list)")
    async def category_remove(self, interaction: discord.Interaction, category_id: int) -> None:
        if not await self._require_manage(interaction):
            return
        ok = self.db.remove_ticket_category(interaction.guild_id, category_id)
        if ok:
            await self.refresh_panel(interaction.guild)  # type: ignore[arg-type]
        await interaction.response.send_message(
            "🗑️ Thema entfernt." if ok else "⚠️ Kein Thema mit dieser ID gefunden.", ephemeral=True
        )

    @category.command(name="list", description="Zeigt alle Ticket-Themen.")
    async def category_list(self, interaction: discord.Interaction) -> None:
        if not await self._require_manage(interaction):
            return
        cats = self.db.list_ticket_categories(interaction.guild_id)
        if not cats:
            await interaction.response.send_message(
                "Noch keine Themen — es wird das Standard-Thema »Support« angeboten. "
                "Lege welche mit `/ticket category add` an.",
                ephemeral=True,
            )
            return
        lines = [
            f"`{c['id']}` {c['emoji'] or '•'} **{c['label']}**"
            + (f" — {c['description']}" if c["description"] else "")
            for c in cats
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
