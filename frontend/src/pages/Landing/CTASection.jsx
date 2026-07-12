import Button from '../../components/Button'

// One closing action, stated plainly on the surface tone.
export default function CTASection() {
  return (
    <section className="border-t border-hairline bg-surface px-6 py-24 md:py-32 lg:px-16">
      <div className="mx-auto flex max-w-site flex-col items-start gap-12 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-3xl font-semibold tracking-tighter text-black sm:text-4xl">
            Scrape your first directory.
          </h2>
          <p className="mt-4 max-w-md text-gray-500">
            Paste a URL and watch it work. No account required.
          </p>
        </div>
        <Button to="/playground">Open the scraper</Button>
      </div>
    </section>
  )
}
