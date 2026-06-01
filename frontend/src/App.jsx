import { Routes, Route, useLocation } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import PageTransition from './components/PageTransition'
import OnboardingTour from './components/OnboardingTour'
import useOnboardingTour from './hooks/useOnboardingTour'
import Landing from './pages/Landing/Landing'
import Playground from './pages/Playground/Playground'
import Agent from './pages/Agent/Agent'
import Pricing from './pages/Pricing/Pricing'
import Docs from './pages/Docs/Docs'

export default function App() {
  const { show, step, currentStep, targetRect, totalSteps, next, prev, complete } = useOnboardingTour()
  const location = useLocation()

  return (
    <>
      {show && (
        <OnboardingTour
          step={step}
          currentStep={currentStep}
          targetRect={targetRect}
          totalSteps={totalSteps}
          onNext={next}
          onPrev={prev}
          onClose={complete}
        />
      )}
      <Navbar />
      <main>
        {/* Keyed by pathname so each route remounts and fades in on navigation. */}
        <PageTransition key={location.pathname}>
          <Routes location={location}>
            <Route path="/" element={<Landing />} />
            <Route path="/playground" element={<Playground />} />
            <Route path="/agent" element={<Agent />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/docs" element={<Docs />} />
          </Routes>
        </PageTransition>
      </main>
      <Footer />
    </>
  )
}
