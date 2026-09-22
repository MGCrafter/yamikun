import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { motion } from "motion/react";
import { Icon } from "../components/Icon";
import { Avatar } from "../components/ui/Avatar";
import { ThemeToggle } from "../components/ui/ThemeToggle";
import { useAuth } from "../lib/auth";
import { Spinner } from "../components/common";

// Gruppierte Navigation — Keys/Routen unverändert, nur visuell gebündelt.
const NAV_GROUPS: { title: string; items: { key: string; label: string; icon: string }[] }[] = [
  {
    title: "Übersicht",
    items: [{ key: "overview", label: "Dashboard", icon: "grid" }],
  },
  {
    title: "Wirtschaft & Karten",
    items: [
      { key: "cards", label: "Sammelkarten", icon: "layers" },
      { key: "yami", label: "Yami-Karten", icon: "cards" },
      { key: "inventory", label: "Inventare", icon: "box" },
      { key: "economy", label: "Economy", icon: "coins" },
    ],
  },
  {
    title: "Community",
    items: [
      { key: "reactionroles", label: "Reaction Roles", icon: "users" },
      { key: "welcome", label: "Willkommen", icon: "enter" },
      { key: "boost", label: "Boost-Nachricht", icon: "sparkle" },
      { key: "twitch", label: "Twitch Live", icon: "sparkle" },
      { key: "autoroles", label: "Auto-Rollen", icon: "shield" },
      { key: "automod", label: "AutoMod", icon: "alert" },
      { key: "voice", label: "Yami Voice", icon: "discord" },
      { key: "levelup", label: "Level-Up", icon: "sparkle" },
      { key: "announce", label: "Nachricht senden", icon: "hash" },
      { key: "tickets", label: "Tickets", icon: "ticket" },
      { key: "audit", label: "Audit-Log", icon: "scroll" },
    ],
  },
  {
    title: "Server",
    items: [
      { key: "games", label: "Spiele & Channel", icon: "gamepad" },
      { key: "botprofile", label: "Bot-Profil", icon: "discord" },
      { key: "support", label: "Support & Wünsche", icon: "alert" },
    ],
  },
];

export default function Layout() {
  const { me, loading } = useAuth();
  const { gid } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  if (loading) return <Spinner />;
  if (!me?.authenticated) return <Navigate to="/" replace />;
  const guilds = me.guilds ?? [];
  if (!guilds.some((g) => g.id === gid)) return <Navigate to="/app" replace />;

  const section = location.pathname.split("/")[3] || "overview";

  return (
    <div className="grid min-h-screen grid-cols-1 md:grid-cols-[270px_1fr]">
      {/* Sidebar */}
      <aside className="sticky top-0 z-20 flex h-auto flex-row flex-wrap items-center gap-2 border-b border-border bg-surface p-4 md:h-screen md:flex-col md:items-stretch md:gap-1 md:overflow-hidden md:border-b-0 md:border-r md:bg-gradient-to-b md:from-surface md:to-bg md:p-4 md:pt-5">
        {/* Brand */}
        <div className="mr-auto flex items-center gap-3 px-2 font-display text-[19px] font-bold md:mr-0 md:pb-4">
          <img
            src="/assets/YamiKun.webp"
            alt=""
            className="h-[42px] w-[42px] rounded-full object-cover ring-2 ring-border-strong"
          />
          <span>Yamikun</span>
        </div>

        {/* User-Profil — klickbar → eigenes Dashboard */}
        <Link
          to={`/u/${gid}`}
          title="Mein Profil ansehen"
          className="group hidden items-center gap-3 rounded-md border border-border bg-surface-2 p-3 transition-colors hover:border-border-strong md:mb-5 md:flex"
        >
          <Avatar src={me.avatar} name={me.username} size={40} online />
          <div className="min-w-0">
            <div className="truncate text-[14.5px] font-bold leading-tight">{me.username}</div>
            <div className="flex items-center gap-1 text-[12px] font-medium text-muted group-hover:text-accent">
              Mein Profil <Icon name="arrow" size={12} />
            </div>
          </div>
        </Link>

        {/* Server-Umschalter */}
        {guilds.length > 1 && (
          <select
            value={gid}
            onChange={(e) => navigate(`/g/${e.target.value}/${section}`)}
            className="field mb-0 hidden cursor-pointer font-semibold md:mb-4 md:block"
          >
            {guilds.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        )}

        {/* Navigation (gruppiert) — scrollt vertikal, falls viele Tabs.
            md:flex-nowrap ist wichtig: mit flex-col würde flex-wrap sonst in eine
            zweite Spalte umbrechen (seitliches Scrollen) statt nach unten. */}
        <nav className="sidebar-scroll flex flex-row flex-wrap gap-1 md:min-h-0 md:flex-1 md:flex-col md:flex-nowrap md:gap-0.5 md:overflow-y-auto md:pr-1">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="contents md:mb-1 md:block">
              <div className="eyebrow mb-1 mt-4 hidden px-3 md:block">{group.title}</div>
              {group.items.map((n) => (
                <NavLink
                  key={n.key}
                  to={`/g/${gid}/${n.key}`}
                  className={({ isActive }) =>
                    `group relative flex items-center gap-3 rounded-sm border px-3 py-2.5 text-[14.5px] transition-colors ${
                      isActive
                        ? "border-accent/30 bg-gradient-to-r from-accent-soft to-transparent font-semibold text-txt"
                        : "border-transparent font-medium text-muted hover:bg-surface-2 hover:text-txt"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <motion.span
                          layoutId="nav-active-bar"
                          className="absolute -left-px bottom-1 top-1 w-[3px] rounded-full bg-accent"
                        />
                      )}
                      <span
                        className={`inline-flex w-[19px] justify-center transition-colors ${
                          isActive ? "text-accent" : "group-hover:text-txt"
                        }`}
                      >
                        <Icon name={n.icon} size={19} />
                      </span>
                      <span className="hidden sm:inline">{n.label}</span>
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        {/* Footer: Theme-Toggle + Logout */}
        <div className="ml-auto flex items-center gap-3 md:ml-0 md:mt-auto md:flex-col md:items-stretch md:gap-2 md:border-t md:border-border md:pt-4">
          <div className="flex items-center justify-between gap-2">
            <a
              href="/logout"
              className="inline-flex items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] text-faint transition-colors hover:text-danger"
            >
              <Icon name="logout" size={16} /> Abmelden
            </a>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {/* Inhalt */}
      <main className="w-full min-w-0 max-w-[1120px] px-6 py-8 pb-20 md:px-10">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <Outlet />
        </motion.div>
      </main>
    </div>
  );
}
