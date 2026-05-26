import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import Landing from './pages/Landing/Landing'
import Playground from './pages/Playground/Playground'
import Agent from './pages/Agent/Agent'
import Pricing from './pages/Pricing/Pricing'
import Docs from './pages/Docs/Docs'

export default function App() {
  return (
    <BrowserRouter>
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/agent" element={<Agent />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/docs" element={<Docs />} />
        </Routes>
      </main>
      <Footer />
    </BrowserRouter>
  )
}
