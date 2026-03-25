export default function SectionWrapper({ children, id, className = '', gray = false }) {
  return (
    <section id={id} className={`px-6 py-20 md:py-28 ${gray ? 'bg-[#FAFAFA]' : 'bg-white'} ${className}`}>
      <div className="mx-auto max-w-site">
        {children}
      </div>
    </section>
  )
}
