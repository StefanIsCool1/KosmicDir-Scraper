export default function SocialProof() {
  const placeholders = ['DataCo', 'BuildOps', 'ScaleAI', 'ReachLabs', 'NexaHQ']

  return (
    <section className="border-y border-gray-100 bg-white px-6 py-10">
      <div className="mx-auto max-w-site">
        <p className="mb-6 text-center text-xs font-medium uppercase tracking-widest text-gray-400">
          Built for marketing teams, lead gen agencies, and data engineers
        </p>
        <div className="flex flex-wrap items-center justify-center gap-8 md:gap-14">
          {placeholders.map((name) => (
            <span key={name} className="text-lg font-semibold tracking-tight text-gray-200 select-none">
              {name}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}
