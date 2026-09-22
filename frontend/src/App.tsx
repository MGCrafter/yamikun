import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { ToastProvider } from "./components/ui/Toast";
// Landing ist die häufigste Einstiegsseite → bleibt im Haupt-Bundle (kein
// zusätzlicher Roundtrip beim ersten Laden). Alle übrigen Seiten werden per
// Code-Splitting nur bei Bedarf nachgeladen.
import Landing from "./pages/Landing";

const GuildPicker = lazy(() => import("./pages/GuildPicker"));
const Layout = lazy(() => import("./pages/Layout"));
const Overview = lazy(() => import("./pages/Overview"));
const Cards = lazy(() => import("./pages/Cards"));
const Yami = lazy(() => import("./pages/Yami"));
const Economy = lazy(() => import("./pages/Economy"));
const Inventory = lazy(() => import("./pages/Inventory"));
const Games = lazy(() => import("./pages/Games"));
const ReactionRoles = lazy(() => import("./pages/ReactionRoles"));
const Welcome = lazy(() => import("./pages/Welcome"));
const Boost = lazy(() => import("./pages/Boost"));
const Twitch = lazy(() => import("./pages/Twitch"));
const TwitchChat = lazy(() => import("./pages/TwitchChat"));
const AutoRoles = lazy(() => import("./pages/AutoRoles"));
const Automod = lazy(() => import("./pages/Automod"));
const Voice = lazy(() => import("./pages/Voice"));
const Levelup = lazy(() => import("./pages/Levelup"));
const BotProfile = lazy(() => import("./pages/BotProfile"));
const Announce = lazy(() => import("./pages/Announce"));
const Audit = lazy(() => import("./pages/Audit"));
const Tickets = lazy(() => import("./pages/Tickets"));
const UserGuildPicker = lazy(() => import("./pages/UserGuildPicker"));
const UserDashboard = lazy(() => import("./pages/UserDashboard"));
const Achievements = lazy(() => import("./pages/Achievements"));
const Support = lazy(() => import("./pages/Support"));

function PageFallback() {
  return (
    <div className="grid min-h-screen place-items-center text-muted">Lädt…</div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <div className="app-bg" aria-hidden />
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/twitch" element={<TwitchChat />} />
          <Route path="/app" element={<GuildPicker />} />
          <Route path="/me" element={<UserGuildPicker />} />
          <Route path="/u/:gid" element={<UserDashboard />} />
          <Route path="/u/:gid/achievements" element={<Achievements />} />
          <Route path="/u/:gid/support" element={<Support />} />
          <Route path="/g/:gid" element={<Layout />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<Overview />} />
            <Route path="cards" element={<Cards />} />
            <Route path="yami" element={<Yami />} />
            <Route path="economy" element={<Economy />} />
            <Route path="inventory" element={<Inventory />} />
            <Route path="reactionroles" element={<ReactionRoles />} />
            <Route path="welcome" element={<Welcome />} />
            <Route path="boost" element={<Boost />} />
            <Route path="twitch" element={<Twitch />} />
            <Route path="autoroles" element={<AutoRoles />} />
            <Route path="automod" element={<Automod />} />
            <Route path="voice" element={<Voice />} />
            <Route path="tickets" element={<Tickets />} />
            <Route path="audit" element={<Audit />} />
            <Route path="games" element={<Games />} />
            <Route path="levelup" element={<Levelup />} />
            <Route path="botprofile" element={<BotProfile />} />
            <Route path="announce" element={<Announce />} />
            <Route path="support" element={<Support />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ToastProvider>
  );
}
