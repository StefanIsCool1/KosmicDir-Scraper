// Section padding is structural: 96px, stepping to 128px on desktop.
// `gray` swaps the ground for the one allowed surface tone.
export default function SectionWrapper({ children, id, className = '', gray = false }) {
  return (
    <section id={id} className={`px-6 py-24 md:py-32 lg:px-16 ${gray ? 'bg-surface' : 'bg-white'} ${className}`}>
      <div className="mx-auto max-w-site">
        {children}
      </div>
    </section>
  )
}
