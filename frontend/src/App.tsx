import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { isLoggedIn } from './auth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import MetricsDashboard from './pages/MetricsDashboard'
import Incidents from './pages/Incidents'
import Runbooks from './pages/Runbooks'
import ServerDetail from './pages/ServerDetail'
import ChatPanel from './components/ChatPanel'
import Forecasts from './pages/Forecasts'

function RequireAuth({ children }: { children: JSX.Element }) {
  return isLoggedIn() ? children : <Navigate to="/login" replace />
}

function ChatOverlay() {
  const { pathname } = useLocation()
  if (pathname === '/login') return null
  if (!isLoggedIn()) return null
  return <ChatPanel />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login"       element={<Login />} />
        <Route path="/"            element={<RequireAuth><Dashboard /></RequireAuth>} />
        <Route path="/metrics"     element={<RequireAuth><MetricsDashboard /></RequireAuth>} />
        <Route path="/incidents"   element={<RequireAuth><Incidents /></RequireAuth>} />
        <Route path="/runbooks"    element={<RequireAuth><Runbooks /></RequireAuth>} />
        <Route path="/forecasts"   element={<RequireAuth><Forecasts /></RequireAuth>} />
        <Route path="/servers/:id" element={<RequireAuth><ServerDetail /></RequireAuth>} />
        <Route path="*"            element={<Navigate to="/" replace />} />
      </Routes>
      <ChatOverlay />
    </BrowserRouter>
  )
}
