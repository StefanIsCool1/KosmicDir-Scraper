import { ArrowRight, ArrowLeft, X } from 'lucide-react'

/**
 * Positions the tooltip relative to the target element's rect.
 * Keeps the tooltip within the viewport.
 */
function tooltipStyle(rect, placement) {
  if (!rect) return {} // centered card, no anchor

  const gap = 16
  const maxWidth = 360
  const vw = window.innerWidth
  const vh = window.innerHeight

  // Default: below the target
  let top = rect.bottom + gap
  let left = rect.left + rect.width / 2

  if (placement === 'top') {
    top = rect.top - gap
    left = rect.left + rect.width / 2
  } else if (placement === 'left') {
    top = rect.top + rect.height / 2
    left = rect.left - gap
  } else if (placement === 'right') {
    top = rect.top + rect.height / 2
    left = rect.right + gap
  }

  // Clamp horizontally
  const halfCard = maxWidth / 2
  if (left - halfCard < 16) left = halfCard + 16
  if (left + halfCard > vw - 16) left = vw - halfCard - 16

  // Clamp vertically
  if (top < 16) top = 16
  if (top > vh - 200) top = vh - 200

  return {
    position: 'fixed',
    top,
    left,
    maxWidth,
    transform: 'translate(-50%, 0)',
  }
}

/**
 * Renders a semi-transparent overlay with a "hole" cut around the target
 * element using the box-shadow trick, plus a positioned tooltip card.
 */
export default function OnboardingTour({ step, currentStep, targetRect, totalSteps, onNext, onPrev, onClose }) {
  if (!currentStep) return null

  const isCenter = currentStep.placement === 'center'
  const isLast = step === totalSteps - 1

  // Spotlight hole via box-shadow
  const spotlightStyle = targetRect && !isCenter ? {
    position: 'fixed',
    top: targetRect.top - 8,
    left: targetRect.left - 8,
    width: targetRect.width + 16,
    height: targetRect.height + 16,
    borderRadius: 12,
    boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.45)',
    pointerEvents: 'none',
    zIndex: 51,
  } : null

  // Backdrop for center steps (no hole)
  const backdropStyle = isCenter ? {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.45)',
    backdropFilter: 'blur(2px)',
    zIndex: 50,
  } : null

  return (
    <>
      {/* Backdrop or spotlight hole */}
      {spotlightStyle && <div style={spotlightStyle} />}
      {backdropStyle && <div style={backdropStyle} />}

      {/* Subtle full-screen overlay behind the hole (pointer-events: none so clicks pass through) */}
      {!isCenter && (
        <div className="fixed inset-0 z-50 pointer-events-none" />
      )}

      {/* Tooltip card */}
      <div
        style={isCenter ? undefined : tooltipStyle(targetRect, currentStep.placement)}
        className={`fixed z-[60] ${isCenter ? 'inset-0 flex items-center justify-center' : ''}`}
      >
        <div className={`relative bg-white rounded-2xl shadow-2xl ${isCenter ? 'mx-4 max-w-md p-8' : 'w-full p-5'}`}>
          {/* Close */}
          <button
            onClick={onClose}
            className="absolute right-3 top-3 rounded-full p-1 text-gray-300 hover:text-gray-500 hover:bg-gray-50 transition-colors"
          >
            <X size={16} />
          </button>

          {/* Step counter */}
          <p className="text-[11px] font-medium text-accent mb-1 tracking-wide uppercase">
            Step {step + 1} of {totalSteps}
          </p>

          <h3 className="text-base font-bold text-gray-900 mb-1.5">
            {currentStep.title}
          </h3>
          <p className="text-sm text-gray-500 leading-relaxed mb-5">
            {currentStep.body}
          </p>

          {/* Buttons */}
          {currentStep.waitForClick ? (
            <p className="text-xs text-accent font-medium text-center animate-pulse">
              ↑ Click the highlighted element above to continue
            </p>
          ) : (
            <div className="flex items-center justify-between">
              <button
                onClick={onPrev}
                disabled={step === 0}
                className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors disabled:invisible"
              >
                <ArrowLeft size={14} />
                Back
              </button>

              <div className="flex gap-2">
                {!isLast && (
                  <button
                    onClick={onClose}
                    className="rounded-lg px-3 py-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors"
                  >
                    Skip
                  </button>
                )}
                <button
                  onClick={isLast ? onClose : onNext}
                  className="flex items-center gap-1.5 rounded-lg bg-gray-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-800 transition-colors"
                >
                  {isLast ? 'Get Started' : 'Next'}
                  {!isLast && <ArrowRight size={14} />}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
